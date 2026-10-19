"""Intake and the approval state machine.

intake():   normalise -> find the same person -> upsert contact -> one open deal -> score -> draft
decide():   pending_approval -> approved | edited | rejected   (a person, via Telegram)
mark_sent() approved | edited -> sent                          (n8n, after the email node succeeds)
mark_failed() any -> failed                                     (n8n error workflow)

`mark_sent` refuses any lead that was not approved or edited. That is the whole human-in-the-loop
guarantee on the engine side; `tests/test_workflows_json.py` checks the n8n side.
"""

from __future__ import annotations

import html
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .crm import CRM, ContactRef, get_crm
from .draft import Drafter, draft_with_guard, get_drafter
from .models import APPROVED, EDITED, FAILED, PENDING, REJECTED, SENT, Lead, utcnow
from .normalise import Normalised, normalise
from .scoring import load_criteria, score


class InvalidTransition(ValueError):
    pass


class NotFound(LookupError):
    pass


def intake(
    raw: dict,
    session: Session,
    *,
    crm: CRM | None = None,
    drafter: Drafter | None = None,
    settings: Settings | None = None,
    criteria: dict | None = None,
) -> Lead:
    s = settings or get_settings()
    crm = crm or get_crm(session, s)
    drafter = drafter or get_drafter(s)
    c = criteria or load_criteria(s.criteria_path)

    received = utcnow()
    n = normalise(raw, s.default_region)
    existing = crm.find_contact(n.email, n.phone) or _just_written(
        session, n, s.crm_search_lag_seconds
    )
    if existing:
        contact = crm.update_contact(existing.id, n)
        is_duplicate = True
    else:
        contact = crm.create_contact(n)
        is_duplicate = not contact.created  # the CRM already had it (HubSpot 409)
        if is_duplicate:
            contact = crm.update_contact(contact.id, n)

    deal_id = crm.find_open_deal(contact.id)
    if deal_id is None:
        deal_id = crm.create_deal(contact.id, _deal_title(n), n.budget_gbp, n.source)

    repeat_of = _recent_repeat(session, contact.id, n, s.duplicate_window_hours)
    sc = score(n, c)
    d = draft_with_guard(drafter, n, sc, c)

    lead = Lead(
        received_at=received,
        source=n.source,
        raw=raw,
        name=n.name,
        email=n.email,
        phone=n.phone,
        message=n.message,
        budget_gbp=n.budget_gbp,
        area=n.area,
        enquiry_type=n.enquiry_type,
        problems=n.problems,
        contact_id=contact.id,
        deal_id=deal_id,
        is_duplicate=is_duplicate,
        repeat_of=repeat_of,
        score=sc.points,
        qualification=sc.qualification,
        reasons=sc.reasons,
        missing=sc.missing,
        draft_subject=d.subject,
        draft_text=d.text,
        draft_provider=d.provider,
        draft_model=d.model,
        tokens_in=d.tokens_in,
        tokens_out=d.tokens_out,
        cost_usd=d.cost_usd,
        guard_triggered=d.guard_triggered,
        draft_ready_at=utcnow(),
        status=PENDING,
    )
    if received_at := raw.get("received_at"):
        try:
            from datetime import datetime

            lead.received_at = datetime.fromisoformat(str(received_at)).replace(tzinfo=None)
        except ValueError:
            pass
    session.add(lead)
    session.commit()
    return lead


def _deal_title(n: Normalised) -> str:
    kind = n.enquiry_type if n.enquiry_type != "other" else "enquiry"
    where = f", {n.area}" if n.area else ""
    return f"{kind.capitalize()}: {n.name}{where}"


def _just_written(session: Session, n: Normalised, seconds: int) -> ContactRef | None:
    """A contact this engine wrote moments ago, which the CRM's search may not return yet.

    `draft_ready_at` is stamped by the engine at intake (unlike `received_at`, which can come from
    the form), so it is the time the engine wrote the contact.
    """
    clauses = []
    if n.email:
        clauses.append(Lead.email == n.email)
    if n.phone:
        clauses.append(Lead.phone == n.phone)
    if seconds <= 0 or not clauses:
        return None
    since = utcnow() - timedelta(seconds=seconds)
    row = session.scalars(
        select(Lead)
        .where(or_(*clauses), Lead.contact_id.is_not(None), Lead.draft_ready_at >= since)
        .order_by(Lead.draft_ready_at.desc())
    ).first()
    return ContactRef(id=row.contact_id) if row else None


def _recent_repeat(session: Session, contact_id: str, n: Normalised, hours: int) -> str | None:
    """Same person, same message, within the window: a double click, not a second enquiry."""
    since = utcnow() - timedelta(hours=hours)
    rows = session.scalars(
        select(Lead)
        .where(Lead.contact_id == contact_id, Lead.received_at >= since)
        .order_by(Lead.received_at.desc())
    ).all()
    for row in rows:
        if row.message.strip().lower() == n.message.strip().lower():
            return row.id
    return None


def get_lead(session: Session, lead_id: str) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise NotFound(lead_id)
    return lead


def decide(session: Session, lead_id: str, action: str, text: str = "", by: str = "") -> Lead:
    lead = get_lead(session, lead_id)
    if lead.status != PENDING:
        raise InvalidTransition(f"lead {lead_id} is {lead.status}, not {PENDING}")
    action = action.lower().strip()
    if action == "approve":
        lead.status, lead.final_text = APPROVED, lead.draft_text
    elif action == "edit":
        if not text.strip():
            raise InvalidTransition("edit needs the new text")
        lead.status, lead.final_text = EDITED, text.strip()
    elif action == "reject":
        lead.status, lead.final_text = REJECTED, ""
    else:
        raise InvalidTransition(f"unknown action {action!r}")
    lead.decided_at, lead.decided_by = utcnow(), by
    session.commit()
    return lead


def mark_sent(session: Session, lead_id: str) -> Lead:
    lead = get_lead(session, lead_id)
    if lead.status not in (APPROVED, EDITED):
        raise InvalidTransition(
            f"lead {lead_id} is {lead.status}; only approved or edited leads can be sent"
        )
    lead.status, lead.sent_at = SENT, utcnow()
    session.commit()
    return lead


def mark_failed(session: Session, lead_id: str, error: str) -> Lead:
    lead = get_lead(session, lead_id)
    lead.status, lead.failed_at, lead.error = FAILED, utcnow(), error[:2000]
    session.commit()
    return lead


def approval_message(lead: Lead) -> str:
    """Text for the Telegram message, HTML-escaped (the nodes send with parse_mode HTML) with the
    first line in bold. The `#lead` line lets the Edit flow find the lead."""
    flag = {"hot": "HOT", "warm": "WARM", "cold": "COLD"}.get(lead.qualification, "LEAD")
    e = html.escape
    who = e(lead.name)
    if lead.email:
        who += f", {e(lead.email)}"
    if lead.phone:
        who += f", {e(lead.phone)}"
    headline = f"{flag} lead, score {lead.score}/100: {e(lead.enquiry_type)}" + (
        f" in {e(lead.area)}" if lead.area else ""
    )
    lines = [f"<b>{headline}</b>", who]
    if lead.budget_gbp:
        lines.append(f"Budget: £{lead.budget_gbp:,}")
    if lead.is_duplicate:
        lines.append("Known contact: updated in CRM, no second deal opened")
    if lead.repeat_of:
        lines.append("Same message already received today (double submission)")
    if lead.reasons:
        lines.append("Why: " + e("; ".join(lead.reasons)))
    if lead.missing:
        lines.append("Missing: " + e(", ".join(lead.missing)))
    if lead.guard_triggered:
        lines.append(
            "Draft came from the template: the model's draft contained an unsupported figure"
        )
    message = (lead.message[:500] + ("..." if len(lead.message) > 500 else "")) or "(empty message)"
    lines += [
        "",
        "<b>They wrote:</b>",
        e(message),
        "",
        f"<b>Draft reply</b>, subject: {e(lead.draft_subject)}",
        e(lead.draft_text),
        "",
        f"#lead {lead.id}",
    ]
    return "\n".join(lines)
