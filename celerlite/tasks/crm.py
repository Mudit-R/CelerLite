"""Queue-backed CRM workflows with inspectable, deterministic results.

These handlers intentionally use an explicit scoring rubric and never send
email or call a third-party service. Their results are stored by the task
engine so a user can inspect each workflow run from the dashboard.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from celerlite.api.insights import pipeline_insights
from celerlite.persistence.crm_repository import CRMRepository
from celerlite.persistence.database import get_session


def _lead_fit_score(lead: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Return a transparent 0–100 lead score and the points behind it."""
    factors: list[dict[str, Any]] = []
    revenue = max(0, int(lead.get("annual_revenue") or 0))
    revenue_points = 25 if revenue >= 10_000_000 else 18 if revenue >= 1_000_000 else 10 if revenue >= 250_000 else 5 if revenue else 0
    factors.append({"name": "Company revenue", "points": revenue_points})

    title = re.sub(r"[^a-z ]", " ", str(lead.get("title") or "").lower())
    title_points = 25 if re.search(r"\b(ceo|cto|cio|cfo|chief|founder|president|vp|vice president)\b", title) else 20 if re.search(r"\b(director|head)\b", title) else 12 if "manager" in title else 4 if title.strip() else 0
    factors.append({"name": "Decision-maker seniority", "points": title_points})

    source = str(lead.get("lead_source") or "").strip().lower()
    source_points = 20 if source in {"referral", "partner", "partner event"} else 15 if source in {"inbound web", "inbound", "web"} else 8 if source in {"organic search", "organic"} else 5 if source in {"cold outreach", "cold"} else 0
    factors.append({"name": "Acquisition source", "points": source_points})

    completeness_points = sum((4 if lead.get(key) else 0) for key in ("company", "email", "title"))
    factors.append({"name": "Profile completeness", "points": completeness_points})

    score = min(100, 18 + sum(factor["points"] for factor in factors))
    return score, factors


async def score_leads(target_id: str | None = None) -> dict[str, Any]:
    """Apply the visible fit rubric to active leads and return a compact audit."""
    async with get_session() as session:
        repo = CRMRepository(session)
        leads = await repo.list_leads(limit=500)
        if target_id:
            leads = [lead for lead in leads if lead["id"] == target_id]
            if not leads:
                raise ValueError("Lead not found")
        else:
            leads = [lead for lead in leads if lead.get("status") not in {"Converted", "Disqualified"}]

        ranked = []
        updated = 0
        for lead in leads:
            score, factors = _lead_fit_score(lead)
            if score != lead.get("score"):
                await repo.update_lead(lead["id"], {"score": score})
                updated += 1
            ranked.append({
                "lead_id": lead["id"],
                "name": lead.get("name", ""),
                "company": lead.get("company", ""),
                "score": score,
                "factors": factors,
            })

    ranked.sort(key=lambda item: (-item["score"], item["company"].casefold()))
    return {
        "workflow": "lead_fit_scoring",
        "method": "transparent_rules_v1",
        "processed": len(ranked),
        "updated": updated,
        "top_leads": ranked[:5],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


async def build_pipeline_forecast() -> dict[str, Any]:
    """Create an explainable forecast snapshot from stage, amount and close date."""
    async with get_session() as session:
        deals = await CRMRepository(session).list_deals(limit=500)

    open_deals = [deal for deal in deals if deal.get("stage") not in ("Closed Won", "Closed Lost")]
    insight = pipeline_insights(deals)
    by_stage: dict[str, dict[str, int]] = {}
    for deal in deals:
        stage = str(deal.get("stage") or "Unknown")
        bucket = by_stage.setdefault(stage, {"deals": 0, "amount": 0, "weighted_amount": 0})
        amount = max(0, int(deal.get("amount") or 0))
        probability = min(100, max(0, int(deal.get("probability") or 0)))
        bucket["deals"] += 1
        bucket["amount"] += amount
        bucket["weighted_amount"] += round(amount * probability / 100)

    return {
        "workflow": "pipeline_forecast",
        "method": "stage_probability_snapshot",
        "open_deals": len(open_deals),
        "open_pipeline": sum(max(0, int(deal.get("amount") or 0)) for deal in open_deals),
        "weighted_pipeline": insight["weighted_pipeline"],
        "overdue_count": insight["overdue_count"],
        "missing_next_step_count": insight["missing_next_step_count"],
        "by_stage": by_stage,
        "attention": insight["attention"],
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "note": "Uses the probability entered on each opportunity; it does not predict or change win rates.",
    }


async def create_followup_tasks(target_id: str | None = None) -> dict[str, Any]:
    """Create idempotent CRM activity tasks for active leads without an open task."""
    due_date = date.today() + timedelta(days=2)
    created: list[dict[str, str]] = []
    skipped = 0
    async with get_session() as session:
        repo = CRMRepository(session)
        leads = await repo.list_leads(limit=500)
        if target_id:
            leads = [lead for lead in leads if lead["id"] == target_id]
            if not leads:
                raise ValueError("Lead not found")
        else:
            leads = [lead for lead in leads if lead.get("status") in {"New", "Working", "Contacted"}]

        for lead in leads:
            activities = await repo.list_activities(entity_id=lead["id"], limit=100)
            if any(activity.get("type") == "Task" and activity.get("status") == "Pending" for activity in activities):
                skipped += 1
                continue

            activity_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"celerlite:follow-up:{lead['id']}:{due_date.isoformat()}",
            ))
            if any(activity.get("id") == activity_id for activity in activities):
                skipped += 1
                continue

            name = lead.get("name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
            activity = await repo.create_activity({
                "id": activity_id,
                "entity_type": "lead",
                "entity_id": lead["id"],
                "entity_name": f"{name} · {lead.get('company', '')}",
                "type": "Task",
                "subject": f"Follow up with {name}",
                "description": "Created by CelerLite's follow-up workflow. Review the lead record before contacting them.",
                "due_date": due_date.isoformat(),
                "status": "Pending",
            })
            created.append({"activity_id": activity["id"], "lead_id": lead["id"], "subject": activity["subject"]})

    return {
        "workflow": "lead_followups",
        "created": len(created),
        "skipped_existing": skipped,
        "due_date": due_date.isoformat(),
        "activities": created[:25],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def register_crm_tasks() -> None:
    """Register CRM workflows in both the embedded and distributed workers."""
    from celerlite.worker.worker import register_task

    register_task("celerlite.crm.score_leads", score_leads)
    register_task("celerlite.crm.pipeline_forecast", build_pipeline_forecast)
    register_task("celerlite.crm.create_followup_tasks", create_followup_tasks)
