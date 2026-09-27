"""Asynchronous repository for CRM entities (Leads, Accounts, Contacts, Deals, Activities)."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from celerlite.persistence.models import (
    AccountModel,
    ActivityModel,
    ContactModel,
    DealModel,
    LeadModel,
    utcnow,
)


class CRMRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def seed_demo_data_if_empty(self) -> None:
        """Populate initial realistic enterprise CRM data if database tables are empty."""
        stmt = select(func.count(LeadModel.id))
        res = await self.session.execute(stmt)
        if res.scalar_one() > 0:
            return

        # Seed Accounts
        accounts = [
            AccountModel(
                id="acc-001",
                name="Apex Global Technologies",
                industry="Enterprise Software",
                annual_revenue=12500000,
                employees=450,
                website="https://apexglobal.tech",
                phone="+1 (555) 234-5678",
                billing_city="San Francisco",
                billing_country="USA",
                tier="Strategic",
            ),
            AccountModel(
                id="acc-002",
                name="Nordic Cloud Logistics",
                industry="Supply Chain & Logistics",
                annual_revenue=8400000,
                employees=280,
                website="https://nordiccloud.io",
                phone="+46 8 123 4567",
                billing_city="Stockholm",
                billing_country="Sweden",
                tier="Enterprise",
            ),
            AccountModel(
                id="acc-003",
                name="Vanguard BioHealth Systems",
                industry="Healthcare & Life Sciences",
                annual_revenue=24000000,
                employees=850,
                website="https://vanguardbio.com",
                phone="+1 (555) 876-5432",
                billing_city="Boston",
                billing_country="USA",
                tier="Strategic",
            ),
            AccountModel(
                id="acc-004",
                name="Horizon FinTech Partners",
                industry="Financial Services",
                annual_revenue=6200000,
                employees=140,
                website="https://horizonfintech.co",
                phone="+44 20 7946 0912",
                billing_city="London",
                billing_country="UK",
                tier="Mid-Market",
            ),
            AccountModel(
                id="acc-005",
                name="Quantum Industrial Robotics",
                industry="Automated Manufacturing",
                annual_revenue=18500000,
                employees=600,
                website="https://quantumrobotics.de",
                phone="+49 30 9876 543",
                billing_city="Munich",
                billing_country="Germany",
                tier="Enterprise",
            ),
        ]
        for a in accounts:
            self.session.add(a)

        # Seed Contacts
        contacts = [
            ContactModel(
                id="cnt-001",
                account_id="acc-001",
                account_name="Apex Global Technologies",
                first_name="Elena",
                last_name="Rostova",
                email="elena.rostova@apexglobal.tech",
                phone="+1 (555) 234-5679",
                title="VP of Engineering & Cloud Ops",
                department="Technology",
                is_primary=True,
            ),
            ContactModel(
                id="cnt-002",
                account_id="acc-002",
                account_name="Nordic Cloud Logistics",
                first_name="Lars",
                last_name="Lindqvist",
                email="lars.l@nordiccloud.io",
                phone="+46 8 123 4568",
                title="Chief Technology Officer",
                department="Engineering",
                is_primary=True,
            ),
            ContactModel(
                id="cnt-003",
                account_id="acc-003",
                account_name="Vanguard BioHealth Systems",
                first_name="Dr. Marcus",
                last_name="Vance",
                email="m.vance@vanguardbio.com",
                phone="+1 (555) 876-5433",
                title="Head of Clinical Infrastructure",
                department="Operations",
                is_primary=True,
            ),
            ContactModel(
                id="cnt-004",
                account_id="acc-004",
                account_name="Horizon FinTech Partners",
                first_name="Chloe",
                last_name="Sinclair",
                email="chloe.s@horizonfintech.co",
                phone="+44 20 7946 0913",
                title="Director of Platform Architecture",
                department="Architecture",
                is_primary=True,
            ),
        ]
        for c in contacts:
            self.session.add(c)

        # Seed Leads
        leads = [
            LeadModel(
                id="lead-001",
                first_name="Julian",
                last_name="Mercer",
                company="Starlight Quantum Media",
                title="Director of Data Infrastructure",
                email="julian.m@starlightmedia.io",
                phone="+1 (555) 443-8901",
                status="Qualified",
                lead_source="Inbound Web",
                score=92,
                annual_revenue=5500000,
                notes="Looking to replace legacy Celery with CelerLite for 50k+ daily media transcode jobs.",
                owner="Alex Chen",
            ),
            LeadModel(
                id="lead-002",
                first_name="Amara",
                last_name="Okonkwo",
                company="Kigali Health Logistics",
                title="Chief Information Officer",
                email="amara@kigalilabs.health",
                phone="+250 788 123 456",
                status="Working",
                lead_source="Referral",
                score=85,
                annual_revenue=3200000,
                notes="Needs priority queues and DLQ replay for critical diagnostic delivery pipelines.",
                owner="Sarah Connor",
            ),
            LeadModel(
                id="lead-003",
                first_name="Hiroshi",
                last_name="Tanaka",
                company="Tokyo HyperScale Trading",
                title="Lead SRE & Distributed Systems",
                email="h.tanaka@tokyotrading.jp",
                phone="+81 3 5555 0142",
                status="New",
                lead_source="Partner Event",
                score=78,
                annual_revenue=14000000,
                notes="High-frequency order processing; requires sub-millisecond dispatch.",
                owner="Alex Chen",
            ),
            LeadModel(
                id="lead-004",
                first_name="Camila",
                last_name="Alvarez",
                company="Solaria Fintech LatAm",
                title="VP of Backend Engineering",
                email="camila.alvarez@solariafin.com",
                phone="+52 55 1234 5678",
                status="Contacted",
                lead_source="Cold Outreach",
                score=64,
                annual_revenue=2800000,
                notes="Evaluating distributed rate limiting for banking partner API compliance.",
                owner="Michael Scott",
            ),
            LeadModel(
                id="lead-005",
                first_name="David",
                last_name="Sterling",
                company="Sterling Aerospace Dynamics",
                title="Principal Software Architect",
                email="d.sterling@sterlingaero.com",
                phone="+1 (555) 902-3341",
                status="Working",
                lead_source="Organic Search",
                score=88,
                annual_revenue=32000000,
                notes="Telemetry pipeline integration for autonomous flight diagnostics.",
                owner="Sarah Connor",
            ),
        ]
        for l in leads:
            self.session.add(l)

        # Seed Deals (Opportunities across sales pipeline)
        deals = [
            DealModel(
                id="deal-001",
                account_id="acc-001",
                account_name="Apex Global Technologies",
                name="Apex Global - Enterprise Platform Rollout",
                stage="Negotiation",
                amount=185000,
                probability=90,
                close_date="2026-10-15",
                deal_type="New Business",
                owner="Alex Chen",
                next_step="Final security review and MSA sign-off",
            ),
            DealModel(
                id="deal-002",
                account_id="acc-002",
                account_name="Nordic Cloud Logistics",
                name="Nordic Cloud - Real-Time Queue Infrastructure",
                stage="Proposal/Price Quote",
                amount=95000,
                probability=75,
                close_date="2026-10-28",
                deal_type="New Business",
                owner="Sarah Connor",
                next_step="Review multi-region Redis cluster pricing model",
            ),
            DealModel(
                id="deal-003",
                account_id="acc-003",
                account_name="Vanguard BioHealth Systems",
                name="Vanguard BioHealth - HIPAA Processing Fleet",
                stage="Qualification",
                amount=320000,
                probability=40,
                close_date="2026-11-20",
                deal_type="Expansion",
                owner="Alex Chen",
                next_step="Architectural review with compliance team",
            ),
            DealModel(
                id="deal-004",
                account_id="acc-004",
                account_name="Horizon FinTech Partners",
                name="Horizon FinTech - Rate Limiter & DLQ Suite",
                stage="Needs Analysis",
                amount=68000,
                probability=50,
                close_date="2026-11-05",
                deal_type="New Business",
                owner="Michael Scott",
                next_step="Deliver benchmark report on 10k req/sec throughput",
            ),
            DealModel(
                id="deal-005",
                account_id="acc-005",
                account_name="Quantum Industrial Robotics",
                name="Quantum Robotics - Factory Floor Event Bus",
                stage="Closed Won",
                amount=240000,
                probability=100,
                close_date="2026-09-15",
                deal_type="New Business",
                owner="Sarah Connor",
                next_step="Deployment kicked off in European data center",
            ),
            DealModel(
                id="deal-006",
                account_id="acc-001",
                account_name="Apex Global Technologies",
                name="Apex Global - Premium Support & SLA Add-On",
                stage="Prospecting",
                amount=45000,
                probability=20,
                close_date="2026-12-10",
                deal_type="Expansion",
                owner="Alex Chen",
                next_step="Follow-up call post initial rollout",
            ),
        ]
        for d in deals:
            self.session.add(d)

        # Seed Activities
        activities = [
            ActivityModel(
                id="act-001",
                entity_type="deal",
                entity_id="deal-001",
                entity_name="Apex Global - Enterprise Platform Rollout",
                type="Meeting",
                subject="Executive Security & Legal Review",
                description="Reviewed SOC2 compliance docs and SLA terms with Head of Procurement.",
                due_date="2026-09-28",
                status="Pending",
            ),
            ActivityModel(
                id="act-002",
                entity_type="lead",
                entity_id="lead-001",
                entity_name="Julian Mercer (Starlight Quantum)",
                type="Call",
                subject="Technical Discovery Call & Architecture Demo",
                description="Demonstrated CelerLite priority scheduling and zero-loss crash recovery.",
                due_date="2026-09-26",
                status="Completed",
            ),
            ActivityModel(
                id="act-003",
                entity_type="deal",
                entity_id="deal-002",
                entity_name="Nordic Cloud - Real-Time Queue Infrastructure",
                type="Task",
                subject="Send customized throughput benchmark report",
                description="Include P99 latency comparisons under 6,000 tasks/sec load.",
                due_date="2026-09-29",
                status="Pending",
            ),
            ActivityModel(
                id="act-004",
                entity_type="lead",
                entity_id="lead-002",
                entity_name="Amara Okonkwo (Kigali Health)",
                type="Email",
                subject="Sent pilot deployment guide & Docker Compose files",
                description="Shared step-by-step instructions for on-prem test deployment.",
                due_date="2026-09-27",
                status="Completed",
            ),
        ]
        for act in activities:
            self.session.add(act)

        await self.session.commit()

    # --- Leads ---
    async def list_leads(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        await self.seed_demo_data_if_empty()
        stmt = select(LeadModel).order_by(LeadModel.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(LeadModel.status == status)
        result = await self.session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def create_lead(self, data: dict) -> dict:
        lead = LeadModel(
            id=data.get("id") or str(uuid.uuid4()),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            company=data.get("company", ""),
            title=data.get("title"),
            email=data.get("email", ""),
            phone=data.get("phone"),
            status=data.get("status", "New"),
            lead_source=data.get("lead_source", "Web"),
            score=data.get("score", 70),
            annual_revenue=data.get("annual_revenue"),
            notes=data.get("notes"),
            owner=data.get("owner", "Alex Chen"),
        )
        self.session.add(lead)
        await self.session.commit()
        return lead.to_dict()

    async def update_lead(self, lead_id: str, data: dict) -> Optional[dict]:
        lead = await self.session.get(LeadModel, lead_id)
        if not lead:
            return None
        for k, v in data.items():
            if hasattr(lead, k) and v is not None:
                setattr(lead, k, v)
        lead.updated_at = utcnow()
        await self.session.commit()
        return lead.to_dict()

    async def delete_lead(self, lead_id: str) -> bool:
        stmt = delete(LeadModel).where(LeadModel.id == lead_id)
        res = await self.session.execute(stmt)
        await self.session.commit()
        return res.rowcount > 0

    # --- Accounts ---
    async def list_accounts(self, limit: int = 50) -> list[dict]:
        await self.seed_demo_data_if_empty()
        stmt = select(AccountModel).order_by(AccountModel.annual_revenue.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def create_account(self, data: dict) -> dict:
        acc = AccountModel(
            id=data.get("id") or str(uuid.uuid4()),
            name=data.get("name", ""),
            industry=data.get("industry", "Technology"),
            annual_revenue=data.get("annual_revenue", 1000000),
            employees=data.get("employees", 50),
            website=data.get("website"),
            phone=data.get("phone"),
            billing_city=data.get("billing_city"),
            billing_country=data.get("billing_country"),
            tier=data.get("tier", "Enterprise"),
        )
        self.session.add(acc)
        await self.session.commit()
        return acc.to_dict()

    # --- Contacts ---
    async def list_contacts(self, account_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        await self.seed_demo_data_if_empty()
        stmt = select(ContactModel).order_by(ContactModel.last_name.asc()).limit(limit)
        if account_id:
            stmt = stmt.where(ContactModel.account_id == account_id)
        result = await self.session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def create_contact(self, data: dict) -> dict:
        cnt = ContactModel(
            id=data.get("id") or str(uuid.uuid4()),
            account_id=data.get("account_id"),
            account_name=data.get("account_name"),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            email=data.get("email", ""),
            phone=data.get("phone"),
            title=data.get("title"),
            department=data.get("department"),
            is_primary=data.get("is_primary", False),
        )
        self.session.add(cnt)
        await self.session.commit()
        return cnt.to_dict()

    # --- Deals / Opportunities ---
    async def list_deals(self, stage: Optional[str] = None, limit: int = 100) -> list[dict]:
        await self.seed_demo_data_if_empty()
        stmt = select(DealModel).order_by(DealModel.amount.desc()).limit(limit)
        if stage:
            stmt = stmt.where(DealModel.stage == stage)
        result = await self.session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def create_deal(self, data: dict) -> dict:
        deal = DealModel(
            id=data.get("id") or str(uuid.uuid4()),
            account_id=data.get("account_id"),
            account_name=data.get("account_name", "Enterprise Account"),
            name=data.get("name", ""),
            stage=data.get("stage", "Prospecting"),
            amount=data.get("amount", 50000),
            probability=data.get("probability", 20),
            close_date=data.get("close_date", datetime.now().strftime("%Y-%m-%d")),
            deal_type=data.get("deal_type", "New Business"),
            owner=data.get("owner", "Alex Chen"),
            next_step=data.get("next_step"),
        )
        self.session.add(deal)
        await self.session.commit()
        return deal.to_dict()

    async def update_deal(self, deal_id: str, data: dict) -> Optional[dict]:
        deal = await self.session.get(DealModel, deal_id)
        if not deal:
            return None
        for k, v in data.items():
            if hasattr(deal, k) and v is not None:
                setattr(deal, k, v)
        deal.updated_at = utcnow()
        await self.session.commit()
        return deal.to_dict()

    async def delete_deal(self, deal_id: str) -> bool:
        stmt = delete(DealModel).where(DealModel.id == deal_id)
        res = await self.session.execute(stmt)
        await self.session.commit()
        return res.rowcount > 0

    # --- Activities ---
    async def list_activities(self, entity_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        await self.seed_demo_data_if_empty()
        stmt = select(ActivityModel).order_by(ActivityModel.created_at.desc()).limit(limit)
        if entity_id:
            stmt = stmt.where(ActivityModel.entity_id == entity_id)
        result = await self.session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def create_activity(self, data: dict) -> dict:
        act = ActivityModel(
            id=data.get("id") or str(uuid.uuid4()),
            entity_type=data.get("entity_type", "deal"),
            entity_id=data.get("entity_id", "deal-001"),
            entity_name=data.get("entity_name"),
            type=data.get("type", "Task"),
            subject=data.get("subject", ""),
            description=data.get("description"),
            due_date=data.get("due_date"),
            status=data.get("status", "Pending"),
        )
        self.session.add(act)
        await self.session.commit()
        return act.to_dict()

    async def toggle_activity(self, activity_id: str) -> Optional[dict]:
        act = await self.session.get(ActivityModel, activity_id)
        if not act:
            return None
        act.status = "Completed" if act.status == "Pending" else "Pending"
        await self.session.commit()
        return act.to_dict()

    # --- CRM Executive Dashboard Aggregates ---
    async def get_crm_stats(self) -> dict:
        await self.seed_demo_data_if_empty()
        # Leads count
        leads_res = await self.session.execute(select(func.count(LeadModel.id)))
        total_leads = leads_res.scalar_one()

        # Deals aggregates
        deals_res = await self.session.execute(
            select(
                func.count(DealModel.id),
                func.sum(DealModel.amount),
            )
        )
        deal_count, total_pipeline_amount = deals_res.one()
        total_pipeline_amount = total_pipeline_amount or 0

        # Closed Won amount
        won_res = await self.session.execute(
            select(func.sum(DealModel.amount)).where(DealModel.stage == "Closed Won")
        )
        closed_won_amount = won_res.scalar_one() or 0

        # Accounts & Contacts
        acc_res = await self.session.execute(select(func.count(AccountModel.id)))
        total_accounts = acc_res.scalar_one()

        contacts_res = await self.session.execute(select(func.count(ContactModel.id)))
        total_contacts = contacts_res.scalar_one()

        # Pipeline by stage
        stages_res = await self.session.execute(
            select(DealModel.stage, func.count(DealModel.id), func.sum(DealModel.amount)).group_by(DealModel.stage)
        )
        stage_breakdown = [
            {"stage": row[0], "count": row[1], "value": row[2]} for row in stages_res.all()
        ]

        win_rate = (closed_won_amount / total_pipeline_amount * 100) if total_pipeline_amount > 0 else 0

        return {
            "total_pipeline": total_pipeline_amount,
            "closed_won": closed_won_amount,
            "total_deals": deal_count,
            "total_leads": total_leads,
            "total_accounts": total_accounts,
            "total_contacts": total_contacts,
            "win_rate_percent": round(win_rate, 1),
            "stage_breakdown": stage_breakdown,
        }
