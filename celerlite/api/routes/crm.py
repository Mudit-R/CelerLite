"""CRM API endpoints for Leads, Accounts, Contacts, Deals, and Activities."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from celerlite.api.app import get_broker
from celerlite.broker.redis_broker import RedisBroker
from celerlite.broker.serializer import Serializer, TaskMessage
from celerlite.persistence.crm_repository import CRMRepository
from celerlite.persistence.database import get_session

router = APIRouter()


class CreateLeadRequest(BaseModel):
    first_name: str
    last_name: str
    company: str
    email: str
    title: Optional[str] = None
    phone: Optional[str] = None
    status: str = "New"
    lead_source: str = "Web"
    score: int = 70
    annual_revenue: Optional[int] = None
    notes: Optional[str] = None
    owner: str = "Alex Chen"


class UpdateLeadRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    lead_source: Optional[str] = None
    score: Optional[int] = None
    annual_revenue: Optional[int] = None
    notes: Optional[str] = None
    owner: Optional[str] = None


class CreateAccountRequest(BaseModel):
    name: str
    industry: str = "Technology"
    annual_revenue: int = 1000000
    employees: int = 50
    website: Optional[str] = None
    phone: Optional[str] = None
    billing_city: Optional[str] = None
    billing_country: Optional[str] = None
    tier: str = "Enterprise"


class CreateContactRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    department: Optional[str] = None
    is_primary: bool = False


class CreateDealRequest(BaseModel):
    name: str
    account_name: str
    account_id: Optional[str] = None
    stage: str = "Prospecting"
    amount: int = 50000
    probability: int = 20
    close_date: str
    deal_type: str = "New Business"
    owner: str = "Alex Chen"
    next_step: Optional[str] = None


class UpdateDealRequest(BaseModel):
    name: Optional[str] = None
    account_name: Optional[str] = None
    stage: Optional[str] = None
    amount: Optional[int] = None
    probability: Optional[int] = None
    close_date: Optional[str] = None
    deal_type: Optional[str] = None
    owner: Optional[str] = None
    next_step: Optional[str] = None


class CreateActivityRequest(BaseModel):
    entity_type: str  # lead, deal, account, contact
    entity_id: str
    entity_name: Optional[str] = None
    type: str = "Task"  # Call, Email, Meeting, Task, Note
    subject: str
    description: Optional[str] = None
    due_date: Optional[str] = None


class CRMAutomationRequest(BaseModel):
    action: str  # enrich_leads, run_drip_campaign, calculate_deal_probabilities, sync_crm_cache
    target_id: Optional[str] = None


# --- Stats ---
@router.get("/stats")
async def get_crm_stats():
    async with get_session() as session:
        repo = CRMRepository(session)
        return await repo.get_crm_stats()


# --- Leads ---
@router.get("/leads")
async def list_leads(status: Optional[str] = None, limit: int = Query(50, ge=1, le=100)):
    async with get_session() as session:
        repo = CRMRepository(session)
        leads = await repo.list_leads(status=status, limit=limit)
        return {"leads": leads, "total": len(leads)}


@router.post("/leads")
async def create_lead(body: CreateLeadRequest):
    async with get_session() as session:
        repo = CRMRepository(session)
        created = await repo.create_lead(body.model_dump())
        return created


@router.put("/leads/{lead_id}")
async def update_lead(lead_id: str, body: UpdateLeadRequest):
    async with get_session() as session:
        repo = CRMRepository(session)
        updated = await repo.update_lead(lead_id, body.model_dump(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Lead not found")
        return updated


@router.delete("/leads/{lead_id}")
async def delete_lead(lead_id: str):
    async with get_session() as session:
        repo = CRMRepository(session)
        success = await repo.delete_lead(lead_id)
        if not success:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"status": "deleted", "lead_id": lead_id}


@router.post("/leads/{lead_id}/convert")
async def convert_lead_to_deal(lead_id: str):
    async with get_session() as session:
        repo = CRMRepository(session)
        leads = await repo.list_leads()
        target_lead = next((l for l in leads if l["id"] == lead_id), None)
        if not target_lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        # Mark lead as Qualified
        await repo.update_lead(lead_id, {"status": "Qualified"})

        # Create Opportunity
        deal = await repo.create_deal(
            {
                "name": f"{target_lead['company']} - Enterprise Expansion",
                "account_name": target_lead["company"],
                "stage": "Qualification",
                "amount": target_lead.get("annual_revenue") or 85000,
                "probability": 40,
                "close_date": "2026-11-30",
                "deal_type": "New Business",
                "owner": target_lead.get("owner") or "Alex Chen",
                "next_step": "Schedule technical deep dive with engineering team",
            }
        )
        return {"status": "converted", "deal": deal}


# --- Accounts ---
@router.get("/accounts")
async def list_accounts(limit: int = Query(50, ge=1, le=100)):
    async with get_session() as session:
        repo = CRMRepository(session)
        accounts = await repo.list_accounts(limit=limit)
        return {"accounts": accounts, "total": len(accounts)}


@router.post("/accounts")
async def create_account(body: CreateAccountRequest):
    async with get_session() as session:
        repo = CRMRepository(session)
        created = await repo.create_account(body.model_dump())
        return created


# --- Contacts ---
@router.get("/contacts")
async def list_contacts(account_id: Optional[str] = None, limit: int = Query(50, ge=1, le=100)):
    async with get_session() as session:
        repo = CRMRepository(session)
        contacts = await repo.list_contacts(account_id=account_id, limit=limit)
        return {"contacts": contacts, "total": len(contacts)}


@router.post("/contacts")
async def create_contact(body: CreateContactRequest):
    async with get_session() as session:
        repo = CRMRepository(session)
        created = await repo.create_contact(body.model_dump())
        return created


# --- Deals / Pipeline ---
@router.get("/deals")
async def list_deals(stage: Optional[str] = None, limit: int = Query(100, ge=1, le=200)):
    async with get_session() as session:
        repo = CRMRepository(session)
        deals = await repo.list_deals(stage=stage, limit=limit)
        return {"deals": deals, "total": len(deals)}


@router.post("/deals")
async def create_deal(body: CreateDealRequest):
    async with get_session() as session:
        repo = CRMRepository(session)
        created = await repo.create_deal(body.model_dump())
        return created


@router.put("/deals/{deal_id}")
async def update_deal(deal_id: str, body: UpdateDealRequest):
    async with get_session() as session:
        repo = CRMRepository(session)
        updated = await repo.update_deal(deal_id, body.model_dump(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Deal not found")
        return updated


@router.delete("/deals/{deal_id}")
async def delete_deal(deal_id: str):
    async with get_session() as session:
        repo = CRMRepository(session)
        success = await repo.delete_deal(deal_id)
        if not success:
            raise HTTPException(status_code=404, detail="Deal not found")
        return {"status": "deleted", "deal_id": deal_id}


# --- Activities ---
@router.get("/activities")
async def list_activities(entity_id: Optional[str] = None, limit: int = Query(50, ge=1, le=100)):
    async with get_session() as session:
        repo = CRMRepository(session)
        activities = await repo.list_activities(entity_id=entity_id, limit=limit)
        return {"activities": activities, "total": len(activities)}


@router.post("/activities")
async def create_activity(body: CreateActivityRequest):
    async with get_session() as session:
        repo = CRMRepository(session)
        created = await repo.create_activity(body.model_dump())
        return created


@router.put("/activities/{activity_id}/toggle")
async def toggle_activity(activity_id: str):
    async with get_session() as session:
        repo = CRMRepository(session)
        toggled = await repo.toggle_activity(activity_id)
        if not toggled:
            raise HTTPException(status_code=404, detail="Activity not found")
        return toggled


# --- CRM Automation with CelerLite Task Queue ---
@router.post("/automate")
async def trigger_crm_automation(
    body: CRMAutomationRequest,
    broker: RedisBroker = Depends(get_broker),
):
    """Enqueues an asynchronous background job into the CelerLite distributed task queue."""
    task_name = f"crm.automation.{body.action}"
    task_id = str(uuid.uuid4())
    message = TaskMessage(
        task_id=task_id,
        task_name=task_name,
        args=[body.action, body.target_id],
        kwargs={"triggered_by": "CRM Platform Automation Engine"},
        queue="crm",
        priority=2,  # HIGH priority
        max_retries=3,
        timeout=120,
    )
    raw = Serializer.serialize(message)
    if broker:
        await broker.enqueue("crm", raw, priority=2)

    return {
        "status": "QUEUED",
        "task_id": task_id,
        "task_name": task_name,
        "message": f"CRM background workflow '{body.action}' enqueued to CelerLite engine.",
    }
