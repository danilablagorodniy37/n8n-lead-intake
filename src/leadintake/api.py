"""The HTTP surface n8n talks to. Five routes do the work; the rest is reporting."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import __version__, pipeline
from .config import get_settings
from .db import session_factory
from .models import Incident, Lead
from .report import build_report


class DecisionIn(BaseModel):
    action: str = Field(description="approve | edit | reject")
    text: str = ""
    by: str = ""


class FailedIn(BaseModel):
    error: str = ""


class IncidentIn(BaseModel):
    workflow: str = ""
    node: str = ""
    message: str = ""
    lead_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def lead_out(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "status": lead.status,
        "received_at": lead.received_at.isoformat(),
        "draft_ready_at": lead.draft_ready_at.isoformat() if lead.draft_ready_at else None,
        "source": lead.source,
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        "message": lead.message,
        "budget_gbp": lead.budget_gbp,
        "area": lead.area,
        "enquiry_type": lead.enquiry_type,
        "problems": lead.problems,
        "contact_id": lead.contact_id,
        "deal_id": lead.deal_id,
        "is_duplicate": lead.is_duplicate,
        "repeat_of": lead.repeat_of,
        "score": lead.score,
        "qualification": lead.qualification,
        "reasons": lead.reasons,
        "missing": lead.missing,
        "draft_subject": lead.draft_subject,
        "draft_text": lead.draft_text,
        "draft_provider": lead.draft_provider,
        "draft_model": lead.draft_model,
        "cost_usd": round(lead.cost_usd, 6),
        "guard_triggered": lead.guard_triggered,
        "approval_message": pipeline.approval_message(lead),
    }


def decision_out(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "status": lead.status,
        "send": lead.status in ("approved", "edited"),
        "reply_to": lead.email,
        "reply_name": lead.name,
        "reply_subject": lead.draft_subject,
        "reply_text": lead.final_text,
        "decided_at": lead.decided_at.isoformat() if lead.decided_at else None,
    }


def create_app() -> FastAPI:
    app = FastAPI(title="leadintake", version=__version__)

    def get_session() -> Iterator[Session]:
        session = session_factory()()
        try:
            yield session
        finally:
            session.close()

    def require_token(authorization: str | None = Header(default=None)) -> None:
        token = get_settings().api_token
        if token and authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="missing or wrong bearer token")

    deps = [Depends(require_token)]

    @app.get("/healthz")
    def healthz() -> dict:
        s = get_settings()
        return {"ok": True, "version": __version__, "crm": s.crm_provider, "llm": s.llm_provider}

    @app.post("/leads", dependencies=deps, status_code=201)
    async def create_lead(request: Request, session: Session = Depends(get_session)) -> dict:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="body must be a JSON object")
        # n8n's webhook node wraps the form in {"body": {...}, "headers": ..., "query": ...}
        if isinstance(raw.get("body"), dict) and "headers" in raw:
            raw = raw["body"]
        lead = pipeline.intake(raw, session)
        return lead_out(lead)

    @app.get("/leads/{lead_id}", dependencies=deps)
    def read_lead(lead_id: str, session: Session = Depends(get_session)) -> dict:
        return lead_out(_lead(session, lead_id))

    @app.post("/leads/{lead_id}/decision", dependencies=deps)
    def decision(lead_id: str, body: DecisionIn, session: Session = Depends(get_session)) -> dict:
        try:
            lead = pipeline.decide(session, lead_id, body.action, body.text, body.by)
        except pipeline.NotFound:
            raise HTTPException(status_code=404, detail="lead not found") from None
        except pipeline.InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return decision_out(lead)

    @app.post("/leads/{lead_id}/sent", dependencies=deps)
    def sent(lead_id: str, session: Session = Depends(get_session)) -> dict:
        try:
            lead = pipeline.mark_sent(session, lead_id)
        except pipeline.NotFound:
            raise HTTPException(status_code=404, detail="lead not found") from None
        except pipeline.InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return {"id": lead.id, "status": lead.status, "sent_at": lead.sent_at.isoformat()}

    @app.post("/leads/{lead_id}/failed", dependencies=deps)
    def failed(lead_id: str, body: FailedIn, session: Session = Depends(get_session)) -> dict:
        try:
            lead = pipeline.mark_failed(session, lead_id, body.error)
        except pipeline.NotFound:
            raise HTTPException(status_code=404, detail="lead not found") from None
        return {"id": lead.id, "status": lead.status}

    @app.post("/incidents", dependencies=deps, status_code=201)
    def incident(body: IncidentIn, session: Session = Depends(get_session)) -> dict:
        row = Incident(
            workflow=body.workflow,
            node=body.node,
            message=body.message[:4000],
            lead_id=body.lead_id,
            payload=body.payload,
        )
        session.add(row)
        session.commit()
        return {"id": row.id, "created_at": row.created_at.isoformat()}

    @app.get("/report", dependencies=deps)
    def report(session: Session = Depends(get_session)) -> dict:
        return build_report(session)

    return app


def _lead(session: Session, lead_id: str) -> Lead:
    try:
        return pipeline.get_lead(session, lead_id)
    except pipeline.NotFound:
        raise HTTPException(status_code=404, detail="lead not found") from None


app = create_app()
