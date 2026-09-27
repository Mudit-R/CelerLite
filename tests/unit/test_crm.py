"""Unit & integration tests for CRM repository and API endpoints."""

import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from celerlite.api.app import create_app
from celerlite.persistence.models import Base
from celerlite.persistence.crm_repository import CRMRepository
import celerlite.persistence.database as db_mod
import celerlite.api.routes.crm as crm_route_mod


@pytest_asyncio.fixture
async def crm_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def crm_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def override_get_session():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    db_mod.get_session = override_get_session
    crm_route_mod.get_session = override_get_session

    app = create_app(serverless=True)
    yield app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_crm_repository_crud(crm_session):
    repo = CRMRepository(crm_session)
    await repo.seed_demo_data_if_empty()

    # 1. Leads
    leads = await repo.list_leads()
    assert len(leads) >= 5
    
    new_lead = await repo.create_lead({
        "first_name": "Alan",
        "last_name": "Turing",
        "company": "Bletchley Analytics",
        "email": "alan@bletchley.ac.uk",
        "status": "New",
        "score": 95,
    })
    assert new_lead["first_name"] == "Alan"
    assert new_lead["score"] == 95

    updated_lead = await repo.update_lead(new_lead["id"], {"status": "Qualified"})
    assert updated_lead["status"] == "Qualified"

    # 2. Deals / Opportunities
    deals = await repo.list_deals()
    assert len(deals) >= 6

    new_deal = await repo.create_deal({
        "name": "Bletchley - Enigma Decryption Suite",
        "account_name": "Bletchley Analytics",
        "stage": "Prospecting",
        "amount": 150000,
        "probability": 20,
        "close_date": "2026-12-01",
    })
    assert new_deal["amount"] == 150000

    updated_deal = await repo.update_deal(new_deal["id"], {"stage": "Closed Won", "probability": 100})
    assert updated_deal["stage"] == "Closed Won"

    # 3. Accounts & Contacts
    accounts = await repo.list_accounts()
    assert len(accounts) >= 5

    contacts = await repo.list_contacts()
    assert len(contacts) >= 4

    # 4. Activities
    activities = await repo.list_activities()
    assert len(activities) >= 4

    new_act = await repo.create_activity({
        "entity_type": "deal",
        "entity_id": new_deal["id"],
        "type": "Meeting",
        "subject": "Kickoff with Architecture Team",
    })
    assert new_act["status"] == "Pending"

    toggled = await repo.toggle_activity(new_act["id"])
    assert toggled["status"] == "Completed"

    # 5. Stats
    stats = await repo.get_crm_stats()
    assert stats["total_pipeline"] > 0
    assert stats["total_deals"] >= 7
    assert stats["total_leads"] >= 6


@pytest.mark.asyncio
async def test_crm_api_endpoints(crm_app):
    transport = ASGITransport(app=crm_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Stats
        res = await client.get("/api/v1/crm/stats")
        assert res.status_code == 200
        data = res.json()
        assert "total_pipeline" in data
        assert "win_rate_percent" in data

        # Leads List & Create
        res = await client.get("/api/v1/crm/leads")
        assert res.status_code == 200
        assert len(res.json()["leads"]) > 0

        res = await client.post("/api/v1/crm/leads", json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company": "Analytical Engine Co",
            "email": "ada@lovelace.org",
            "status": "New",
        })
        assert res.status_code == 200
        lead_id = res.json()["id"]

        # Convert Lead
        conv_res = await client.post(f"/api/v1/crm/leads/{lead_id}/convert")
        assert conv_res.status_code == 200
        assert conv_res.json()["status"] == "converted"

        # Deals Kanban List & Update
        deals_res = await client.get("/api/v1/crm/deals")
        assert deals_res.status_code == 200
        assert len(deals_res.json()["deals"]) > 0
        deal_id = deals_res.json()["deals"][0]["id"]

        put_res = await client.put(f"/api/v1/crm/deals/{deal_id}", json={"stage": "Negotiation"})
        assert put_res.status_code == 200
        assert put_res.json()["stage"] == "Negotiation"

        # Automation endpoint
        auto_res = await client.post("/api/v1/crm/automate", json={"action": "calculate_deal_probabilities"})
        assert auto_res.status_code == 200
        assert auto_res.json()["status"] == "QUEUED"
