"""Behavior tests for inspectable CRM background workflows."""

from contextlib import asynccontextmanager

import pytest

from celerlite.persistence.crm_repository import CRMRepository
from celerlite.tasks import crm as crm_tasks


def test_lead_fit_score_is_transparent_bounded_and_repeatable():
    lead = {
        "annual_revenue": 15_000_000,
        "title": "Chief Technology Officer",
        "lead_source": "Referral",
        "company": "Example Systems",
        "email": "cto@example.com",
    }
    score, factors = crm_tasks._lead_fit_score(lead)
    assert score == 100
    assert min(100, 18 + sum(item["points"] for item in factors)) == score
    assert crm_tasks._lead_fit_score(lead) == (score, factors)
    assert crm_tasks._lead_fit_score({"lead_source": "unknown"})[0] <= 100


@pytest.mark.asyncio
async def test_scoring_forecast_and_followup_workflows(crm_session, monkeypatch):
    @asynccontextmanager
    async def use_test_session():
        yield crm_session

    monkeypatch.setattr(crm_tasks, "get_session", use_test_session)
    repo = CRMRepository(crm_session)
    await repo.seed_demo_data_if_empty()

    scoring = await crm_tasks.score_leads()
    assert scoring["workflow"] == "lead_fit_scoring"
    assert scoring["method"] == "transparent_rules_v1"
    assert scoring["processed"] >= 4
    assert scoring["top_leads"]
    stored = await repo.list_leads()
    assert all(0 <= lead["score"] <= 100 for lead in stored)

    forecast = await crm_tasks.build_pipeline_forecast()
    assert forecast["workflow"] == "pipeline_forecast"
    assert forecast["weighted_pipeline"] > 0
    assert forecast["by_stage"]
    assert "does not predict" in forecast["note"]

    first_run = await crm_tasks.create_followup_tasks()
    second_run = await crm_tasks.create_followup_tasks()
    assert first_run["created"] >= 1
    assert second_run["created"] == 0
    assert second_run["skipped_existing"] >= first_run["created"]


@pytest.mark.asyncio
async def test_crm_automation_is_allowlisted_and_saved_in_task_history(crm_app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=crm_app), base_url="http://test") as client:
        rejected = await client.post("/api/v1/crm/automate", json={"action": "run_drip_campaign"})
        assert rejected.status_code == 422

        queued = await client.post("/api/v1/crm/automate", json={"action": "pipeline_forecast"})
        assert queued.status_code == 200
        assert queued.json()["task_name"] == "celerlite.crm.pipeline_forecast"
        assert queued.json()["queue"] == "crm"

        history = await client.get("/api/v1/tasks?queue=crm")
        assert history.status_code == 200
        assert any(task["id"] == queued.json()["task_id"] for task in history.json())
