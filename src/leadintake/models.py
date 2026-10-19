"""Database tables: leads, the fake CRM (contacts, deals) and the incident log."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PENDING = "pending_approval"
APPROVED = "approved"
EDITED = "edited"
REJECTED = "rejected"
SENT = "sent"
FAILED = "failed"
STATUSES = (PENDING, APPROVED, EDITED, REJECTED, SENT, FAILED)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("lead"))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(40), default="website")
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    # normalised
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str | None] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    budget_gbp: Mapped[int | None] = mapped_column(Integer)
    area: Mapped[str | None] = mapped_column(String(80))
    enquiry_type: Mapped[str] = mapped_column(String(20), default="other")
    problems: Mapped[list] = mapped_column(JSON, default=list)

    # crm
    contact_id: Mapped[str | None] = mapped_column(String(64), index=True)
    deal_id: Mapped[str | None] = mapped_column(String(64))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_of: Mapped[str | None] = mapped_column(String(24))

    # scoring and draft
    score: Mapped[int] = mapped_column(Integer, default=0)
    qualification: Mapped[str] = mapped_column(String(8), default="cold")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    missing: Mapped[list] = mapped_column(JSON, default=list)
    draft_subject: Mapped[str] = mapped_column(String(200), default="")
    draft_text: Mapped[str] = mapped_column(Text, default="")
    draft_provider: Mapped[str] = mapped_column(String(20), default="fake")
    draft_model: Mapped[str] = mapped_column(String(60), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    guard_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    draft_ready_at: Mapped[datetime | None] = mapped_column(DateTime)

    # human decision and delivery
    status: Mapped[str] = mapped_column(String(20), default=PENDING, index=True)
    final_text: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_by: Mapped[str] = mapped_column(String(80), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str] = mapped_column(Text, default="")


class Contact(Base):
    """The fake CRM's contact. With CRM_PROVIDER=hubspot this table is not used."""

    __tablename__ = "crm_contacts"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("ct"))
    email: Mapped[str | None] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    enquiries: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Deal(Base):
    __tablename__ = "crm_deals"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("deal"))
    contact_id: Mapped[str] = mapped_column(String(24), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(40), default="new")
    open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Incident(Base):
    """One row per failure reported by the n8n error workflow (or by the engine itself)."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default=lambda: new_id("inc"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    workflow: Mapped[str] = mapped_column(String(120), default="")
    node: Mapped[str] = mapped_column(String(120), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    lead_id: Mapped[str | None] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
