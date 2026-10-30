"""Authentication boundaries for the private workspace."""
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from celerlite.api import auth
from celerlite.api.app import create_app
from celerlite.config import config


@pytest.fixture
def auth_config(monkeypatch):
    monkeypatch.setattr(config, 'AUTH_REQUIRED', True)
    monkeypatch.setattr(config, 'SUPABASE_URL', 'https://project.supabase.co')
    monkeypatch.setattr(config, 'SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test')
    monkeypatch.setattr(config, 'AUTH_ALLOWED_USER_IDS', 'approved-id')
    monkeypatch.setattr(config, 'AUTH_PUBLIC_ORIGIN', 'http://localhost')
    monkeypatch.setattr(config, 'AUTH_COOKIE_SECURE', False)


async def test_api_requires_verified_session_and_same_origin(auth_config, monkeypatch):
    verify = AsyncMock(side_effect=lambda token: {'id': 'approved-id'} if token == 'valid' else None)
    monkeypatch.setattr(auth, 'verified_user', verify)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/v1/tasks')).status_code == 401
        client.cookies.set(auth.COOKIE, 'invalid')
        assert (await client.get('/api/v1/tasks')).status_code == 401
        client.cookies.set(auth.COOKIE, 'valid')
        assert (await client.get('/api/v1/not-a-route')).status_code == 404
        assert (await client.post('/api/v1/tasks/submit', headers={'Origin': 'http://evil'}, json={})).status_code == 403


async def test_login_cookie_and_logout(auth_config, monkeypatch):
    monkeypatch.setattr(auth, 'password_grant', AsyncMock(return_value=httpx.Response(200, json={'access_token': 'valid', 'expires_in': 3600})))
    monkeypatch.setattr(auth, 'verified_user', AsyncMock(return_value={'id': 'approved-id', 'email': 'test@example.org'}))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        payload = {'email': 'test@example.org', 'password': 'test-password'}
        assert (await client.post('/auth/login', json=payload, headers={'Origin': 'http://evil'})).status_code == 403
        response = await client.post('/auth/login', json=payload, headers={'Origin': 'http://localhost'})
        assert response.status_code == 200
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert (await client.get('/auth/session')).status_code == 200
        assert (await client.post('/auth/logout', headers={'Origin': 'http://localhost'})).status_code == 200
        assert auth.COOKIE not in client.cookies


async def test_unapproved_user_and_missing_configuration_fail_closed(auth_config, monkeypatch):
    monkeypatch.setattr(auth, 'password_grant', AsyncMock(return_value=httpx.Response(200, json={'access_token': 'other'})))
    monkeypatch.setattr(auth, 'verified_user', AsyncMock(return_value=None))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/auth/login', json={'email': 'test@example.org', 'password': 'test'}, headers={'Origin': 'http://localhost'})
        assert response.status_code == 403 and auth.COOKIE not in client.cookies
        monkeypatch.setattr(config, 'AUTH_ALLOWED_USER_IDS', '')
        assert (await client.get('/auth/session')).status_code == 503
        assert (await client.get('/api/v1/tasks')).status_code == 401


def test_configuration_rejects_secret_keys_and_insecure_public_origins(auth_config, monkeypatch):
    assert auth.is_configured()
    monkeypatch.setattr(config, 'SUPABASE_PUBLISHABLE_KEY', 'sb_secret_forbidden')
    assert not auth.is_configured()
    monkeypatch.setattr(config, 'SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test')
    monkeypatch.setattr(config, 'AUTH_PUBLIC_ORIGIN', 'http://public.example.org')
    assert not auth.is_configured()


@pytest.mark.parametrize('user,allowed', [
    ({'id': 'approved-id', 'email': 'test@example.org', 'email_confirmed_at': '2026-01-01'}, True),
    ({'id': 'other-id', 'email_confirmed_at': '2026-01-01'}, False),
    ({'id': 'approved-id', 'email_confirmed_at': None}, False),
    ({'id': 'approved-id', 'email_confirmed_at': '2026-01-01', 'is_anonymous': True}, False),
])
async def test_server_verified_identity_must_be_confirmed_and_approved(auth_config, monkeypatch, user, allowed):
    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, headers):
            assert url == 'https://project.supabase.co/auth/v1/user'
            assert headers['Authorization'] == 'Bearer signed-token'
            return httpx.Response(200, json=user)
    monkeypatch.setattr(auth.httpx, 'AsyncClient', lambda **kwargs: FakeClient())
    assert bool(await auth.verified_user('signed-token')) is allowed


def test_websocket_rejects_unauthenticated_clients(auth_config, monkeypatch):
    monkeypatch.setattr(auth, 'verified_user', AsyncMock(return_value=None))
    client = TestClient(create_app())
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/ws/events', headers={'Origin': 'http://localhost'}):
            pass
