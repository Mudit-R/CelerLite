"""Private workspace authentication using Supabase Auth.

Access is limited to explicit user IDs. This is a single shared workspace,
not a multi-tenant CRM. Every protected request validates the session remotely.
"""
import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from celerlite.config import config

router = APIRouter(prefix='/auth', tags=['Authentication'])
COOKIE = 'celerlite_session'
PKCE_COOKIE = 'celerlite_pkce'


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


def safe_publishable_key(key):
    if key.startswith('sb_publishable_'):
        return True
    # Legacy anon JWTs are accepted for older projects; never accept service roles.
    try:
        parts = key.split('.')
        if len(parts) != 3:
            return False
        payload = parts[1] + '=' * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))['role'] == 'anon'
    except (ValueError, KeyError, TypeError):
        return False


def is_configured():
    url = urlsplit(config.SUPABASE_URL)
    origin = urlsplit(config.AUTH_PUBLIC_ORIGIN)
    cookie_transport_safe = (origin.scheme == 'https' and config.AUTH_COOKIE_SECURE) or (
        origin.scheme == 'http' and origin.hostname in ('localhost', '127.0.0.1', '::1')
        and not config.AUTH_COOKIE_SECURE)
    return bool(url.scheme == 'https' and url.netloc and not url.username and not url.password
                and safe_publishable_key(config.SUPABASE_PUBLISHABLE_KEY)
                and config.AUTH_ALLOWED_USER_IDS.strip() and origin.scheme in ('http', 'https')
                and origin.netloc and not origin.username and not origin.password
                and not origin.path and not origin.query and not origin.fragment and cookie_transport_safe)


def valid_origin(origin):
    return bool(origin and config.AUTH_PUBLIC_ORIGIN and
                hmac.compare_digest(origin, config.AUTH_PUBLIC_ORIGIN.rstrip('/')))


async def verified_user(token):
    if not is_configured() or not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(config.SUPABASE_URL.rstrip('/') + '/auth/v1/user',
                headers={'apikey': config.SUPABASE_PUBLISHABLE_KEY, 'Authorization': f'Bearer {token}'})
        if response.status_code != 200:
            return None
        user = response.json()
        allowed = {value.strip() for value in config.AUTH_ALLOWED_USER_IDS.split(',') if value.strip()}
        if user.get('id') not in allowed or user.get('is_anonymous') or not user.get('email_confirmed_at'):
            return None
        return {'id': user['id'], 'email': user.get('email', '')}
    except (httpx.HTTPError, ValueError, TypeError):
        return None


async def password_grant(email, password):
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        return await client.post(config.SUPABASE_URL.rstrip('/') + '/auth/v1/token?grant_type=password',
            headers={'apikey': config.SUPABASE_PUBLISHABLE_KEY},
            json={'email': email, 'password': password})


async def exchange_code(code, verifier):
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        return await client.post(config.SUPABASE_URL.rstrip('/') + '/auth/v1/token?grant_type=pkce',
            headers={'apikey': config.SUPABASE_PUBLISHABLE_KEY},
            json={'auth_code': code, 'code_verifier': verifier})


@router.get('/google/start')
async def google_start():
    if not is_configured():
        raise HTTPException(503, 'Sign-in is not configured')
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    params = urlencode({'provider': 'google', 'redirect_to': config.AUTH_PUBLIC_ORIGIN + '/auth/google/callback',
                        'code_challenge': challenge, 'code_challenge_method': 's256'})
    response = RedirectResponse(config.SUPABASE_URL.rstrip('/') + '/auth/v1/authorize?' + params, status_code=302)
    response.set_cookie(PKCE_COOKIE, verifier, max_age=300, httponly=True, secure=config.AUTH_COOKIE_SECURE,
                        samesite='lax', path='/auth/google/callback')
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get('/google/callback')
async def google_callback(request: Request, code: str = ''):
    response = RedirectResponse('/?auth_error=failed', status_code=303)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.delete_cookie(PKCE_COOKIE, path='/auth/google/callback', secure=config.AUTH_COOKIE_SECURE,
                           httponly=True, samesite='lax')
    verifier = request.cookies.get(PKCE_COOKIE)
    if not is_configured() or not code or not verifier or len(code) > 4096 or len(verifier) > 128:
        return response
    try:
        result = await exchange_code(code, verifier)
        if result.status_code != 200:
            return response
        payload = result.json()
        token = payload.get('access_token')
        if not await verified_user(token):
            response.headers['location'] = '/?auth_error=unapproved'
            return response
        ttl = min(max(int(payload.get('expires_in', 3600)), 1), 3600)
        response.set_cookie(COOKIE, token, max_age=ttl, httponly=True, secure=config.AUTH_COOKIE_SECURE,
                            samesite='strict', path='/')
        response.headers['location'] = '/'
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return response


@router.post('/login')
async def login(body: LoginRequest, request: Request, response: Response):
    if not is_configured():
        raise HTTPException(503, 'Sign-in is not configured')
    if not valid_origin(request.headers.get('origin')):
        raise HTTPException(403, 'Invalid request origin')
    try:
        result = await password_grant(body.email.strip(), body.password)
        if result.status_code != 200:
            raise HTTPException(401, 'Unable to sign in with those credentials')
        payload = result.json()
        token = payload.get('access_token')
        user = await verified_user(token)
        if not user:
            raise HTTPException(403, 'This account is not approved for this workspace')
        ttl = min(max(int(payload.get('expires_in', 3600)), 1), 3600)
        response.set_cookie(COOKIE, token, max_age=ttl, httponly=True, secure=config.AUTH_COOKIE_SECURE,
                            samesite='strict', path='/')
        response.headers['Cache-Control'] = 'no-store'
        return {'user': user}
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(503, 'Sign-in service unavailable')


@router.get('/session')
async def session(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if not config.AUTH_REQUIRED:
        return {'user': {'email': 'Guest demo'}, 'demo': True, 'read_only': config.DEMO_READ_ONLY}
    if not is_configured():
        raise HTTPException(503, 'Sign-in is not configured')
    user = await verified_user(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, 'Sign in required')
    return {'user': user}


@router.post('/logout')
async def logout(request: Request, response: Response):
    if not valid_origin(request.headers.get('origin')):
        raise HTTPException(403, 'Invalid request origin')
    response.delete_cookie(COOKIE, path='/', secure=config.AUTH_COOKIE_SECURE, httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
    return {'status': 'signed out'}
