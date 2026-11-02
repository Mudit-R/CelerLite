"""Authentication boundaries for the private workspace."""
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
import base64
import hashlib

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from types import SimpleNamespace

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
        unavailable = await client.get('/auth/session')
        assert unavailable.status_code == 200 and unavailable.json()['auth_configured'] is False
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


async def test_google_pkce_login_and_allowlist(auth_config, monkeypatch):
    exchange = AsyncMock(return_value=httpx.Response(200, json={'access_token': 'valid', 'expires_in': 3600}))
    monkeypatch.setattr(auth, 'exchange_code', exchange)
    verify = AsyncMock(return_value={'id': 'approved-id'})
    monkeypatch.setattr(auth, 'verified_user', verify)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://localhost') as client:
        start = await client.get('/auth/google/start')
        params = parse_qs(urlsplit(start.headers['location']).query)
        verifier = client.cookies.get(auth.PKCE_COOKIE)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        assert params['provider'] == ['google'] and params['code_challenge'] == [challenge]
        assert params['redirect_to'] == ['http://localhost/auth/google/callback']
        assert 'HttpOnly' in start.headers['set-cookie'] and 'SameSite=lax' in start.headers['set-cookie']
        result = await client.get('/auth/google/callback?code=one-time-code')
        assert result.headers['location'] == '/' and client.cookies.get(auth.COOKIE) == 'valid'
        exchange.assert_awaited_once_with('one-time-code', verifier)
        assert auth.PKCE_COOKIE not in client.cookies
        client.cookies.clear()
        result = await client.get('/auth/google/callback?code=one-time-code')
        assert result.headers['location'] == '/?auth_error=failed'
        assert exchange.await_count == 1
        await client.get('/auth/google/start')
        verify.return_value = None
        result = await client.get('/auth/google/callback?code=other')
        assert result.headers['location'] == '/?auth_error=unapproved' and auth.COOKIE not in client.cookies


async def test_read_only_demo_blocks_api_writes(monkeypatch):
    monkeypatch.setattr(config, 'AUTH_REQUIRED', False)
    monkeypatch.setattr(config, 'DEMO_READ_ONLY', True)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url='http://localhost') as client:
        session = await client.get('/auth/session')
        assert session.json()['read_only'] is True
        response = await client.post('/api/v1/crm/leads', json={})
        assert response.status_code == 403 and response.json()['detail'] == 'This public demo is read-only'
        assert (await client.get('/api/v1/not-a-route')).status_code == 404


def test_demo_database_rejects_private_database_even_with_different_driver_and_credentials(monkeypatch):
    from celerlite.persistence import database as db_mod

    monkeypatch.setattr(db_mod, 'engine', SimpleNamespace(url=URL.create(
        'postgresql+asyncpg', username='private_user', password='private_pass',
        host='db.example.test', port=5432, database='celerlite')))
    monkeypatch.setattr(config, 'DEMO_DATABASE_URL',
                        'postgresql://another_user:another_pass@db.example.test:5432/celerlite')
    assert db_mod.demo_database_isolated() is False

    monkeypatch.setattr(config, 'DEMO_DATABASE_URL',
                        'postgresql://demo_user:demo_pass@db.example.test:5432/celerlite_demo')
    assert db_mod.demo_database_isolated() is True


def test_demo_database_isolation_survives_private_postgres_fallback(monkeypatch):
    from celerlite.persistence import database as db_mod

    # A failed private Postgres connection swaps the active engine to SQLite.
    # The original private URL must still be considered when validating demo.
    monkeypatch.setattr(db_mod, "engine", SimpleNamespace(url=URL.create(
        "sqlite+aiosqlite", database="./celerlite_dev.db")))
    monkeypatch.setattr(db_mod, "_initial_db_url",
                        "postgresql+asyncpg://private:secret@internal.example/celerlite")
    monkeypatch.setattr(config, "DATABASE_URL",
                        "postgresql+asyncpg://private:secret@internal.example/celerlite")
    monkeypatch.setattr(config, "DEMO_DATABASE_URL",
                        "postgresql://demo:secret@external.example/celerlite")
    assert db_mod.demo_database_isolated() is False

    # The SQLite fallback path is also reserved for private records, even
    # before startup has replaced the configured Postgres engine.
    monkeypatch.setattr(db_mod, "engine", SimpleNamespace(url=URL.create(
        "postgresql+asyncpg", host="internal.example", database="celerlite")))
    monkeypatch.setattr(config, "DEMO_DATABASE_URL",
                        "sqlite+aiosqlite:///./celerlite_dev.db")
    assert db_mod.demo_database_isolated() is False


def test_demo_start_rate_limit_is_bounded_and_expires(monkeypatch):
    auth._demo_attempts.clear()
    monkeypatch.setattr(auth.time, "monotonic", lambda: 100.0)
    for _ in range(auth._DEMO_ATTEMPT_LIMIT):
        assert auth._allow_demo_attempt("203.0.113.1") is True
    assert auth._allow_demo_attempt("203.0.113.1") is False

    monkeypatch.setattr(auth.time, "monotonic", lambda: 100.0 + auth._DEMO_ATTEMPT_WINDOW_SECONDS + 1)
    assert auth._allow_demo_attempt("203.0.113.1") is True
    auth._demo_attempts.clear()


async def test_recruiter_demo_is_read_only_and_uses_isolated_synthetic_database(auth_config, monkeypatch, tmp_path):
    from celerlite.persistence.models import Base
    from celerlite.persistence.crm_repository import CRMRepository
    from celerlite.persistence import database as db_mod

    private_engine = create_async_engine('sqlite+aiosqlite:///:memory:', echo=False)
    async with private_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    private_sessions = async_sessionmaker(private_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_mod, 'engine', private_engine)
    monkeypatch.setattr(db_mod, 'AsyncSessionLocal', private_sessions)
    monkeypatch.setattr(db_mod, '_db_initialized', True)
    monkeypatch.setattr(config, 'DEMO_ENABLED', True)
    monkeypatch.setattr(config, 'DEMO_SESSION_TTL', 300)
    monkeypatch.setattr(config, 'DEMO_DATABASE_URL', str(URL.create(
        'sqlite+aiosqlite', database=str(tmp_path / 'synthetic-demo.sqlite'))))
    monkeypatch.setattr(auth, 'verified_user', AsyncMock(side_effect=lambda token: (
        {'id': 'approved-id', 'email': 'owner@example.org'} if token == 'valid' else None
    )))

    async with private_sessions() as private_session:
        await CRMRepository(private_session).create_lead({
            'first_name': 'Private', 'last_name': 'Record', 'company': 'Owner Only',
            'email': 'private@example.org',
        })

    async with AsyncClient(transport=ASGITransport(app=create_app(serverless=True)), base_url='http://localhost') as client:
        anonymous = await client.get('/auth/session')
        assert anonymous.status_code == 200
        assert anonymous.json()['user'] is None
        assert anonymous.json()['demo_available'] is True

        demo = await client.post('/auth/demo', headers={'Origin': 'http://localhost'})
        assert demo.status_code == 200
        assert demo.json()['read_only'] is True
        cookie = client.cookies.get(auth.DEMO_COOKIE)
        assert cookie and 'HttpOnly' in demo.headers['set-cookie'] and 'SameSite=strict' in demo.headers['set-cookie']

        demo_leads = await client.get('/api/v1/crm/leads')
        assert demo_leads.status_code == 200
        demo_emails = {lead['email'] for lead in demo_leads.json()['leads']}
        assert 'private@example.org' not in demo_emails
        blocked = await client.post('/api/v1/crm/leads', headers={'Origin': 'http://localhost'}, json={})
        assert blocked.status_code == 403
        assert (await client.get('/api/v1/tasks')).status_code == 403

        await client.post('/auth/logout', headers={'Origin': 'http://localhost'})
        client.cookies.set(auth.COOKIE, 'valid')
        private_leads = await client.get('/api/v1/crm/leads')
        assert private_leads.status_code == 200
        assert 'private@example.org' in {lead['email'] for lead in private_leads.json()['leads']}

    await private_engine.dispose()


def test_demo_rejects_markup_and_unsafe_websites(monkeypatch):
    from pydantic import ValidationError
    from celerlite.api.routes.crm import CreateLeadRequest, CreateAccountRequest
    monkeypatch.setattr(config, 'AUTH_REQUIRED', False)
    with pytest.raises(ValidationError):
        CreateLeadRequest(first_name='<img>', last_name='Test', company='Demo', email='test@example.com')
    with pytest.raises(ValidationError):
        CreateAccountRequest(name='Demo', website='javascript:alert(1)')
    assert CreateLeadRequest(first_name='Demo', last_name='User', company='Example', email='test@example.com').first_name == 'Demo'
