"""The numbers in the README come from here, not from a prompt.

Duplicates: the seed file knows which submissions belong to the same person. A person with a usable
email or phone must end up as exactly one CRM contact, however many times they wrote in. Someone who
left no usable contact details cannot be matched to anyone, so each of those is its own contact and
is counted separately as "unmatched".
"""

from __future__ import annotations

import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Contact, Deal, Incident, Lead
from .normalise import clean_email, clean_phone
from .seed import load


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, round((len(values) - 1) * p)))
    return values[k]


def _seconds(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def expected_contacts(seed_rows: list[dict], region: str = "GB") -> dict[str, int]:
    """How many contacts a correct CRM holds after the seed: one per identifiable person, plus one
    per unidentifiable submission."""
    identifiable: set[str] = set()
    unmatched = 0
    for row in seed_rows:
        if clean_email(row.get("email")) or clean_phone(row.get("phone"), region):
            identifiable.add(row["person_id"])
        else:
            unmatched += 1
    return {"identifiable_people": len(identifiable), "unmatched_submissions": unmatched}


def build_report(session: Session, seed_path: str | None = None) -> dict[str, Any]:
    s = get_settings()
    leads = session.scalars(select(Lead).order_by(Lead.received_at)).all()
    contacts = session.scalars(select(Contact)).all()
    deals = session.scalars(select(Deal)).all()
    incidents = session.scalars(select(Incident)).all()

    by_status: dict[str, int] = {}
    for lead in leads:
        by_status[lead.status] = by_status.get(lead.status, 0) + 1

    draft_latency = [
        x for x in (_seconds(ld.received_at, ld.draft_ready_at) for ld in leads) if x is not None
    ]
    reply_latency = [
        x for x in (_seconds(ld.received_at, ld.sent_at) for ld in leads) if x is not None
    ]
    costs = [ld.cost_usd for ld in leads]

    seed_rows = load(seed_path or s.seed_path)
    expected = expected_contacts(seed_rows, s.default_region) if seed_rows else None
    duplicates_created: int | None = None
    if expected and s.crm_provider == "fake":
        duplicates_created = (
            len(contacts) - expected["identifiable_people"] - expected["unmatched_submissions"]
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "crm_provider": s.crm_provider,
        "llm_provider": leads[-1].draft_provider if leads else s.llm_provider,
        "draft_model": leads[-1].draft_model if leads else s.draft_model,
        "leads": len(leads),
        "by_status": by_status,
        "duplicates_flagged": sum(1 for ld in leads if ld.is_duplicate),
        "double_submissions": sum(1 for ld in leads if ld.repeat_of),
        "no_contact_details": sum(1 for ld in leads if "no_contact_details" in (ld.problems or [])),
        "crm_contacts": len(contacts) if s.crm_provider == "fake" else None,
        "crm_deals": len(deals) if s.crm_provider == "fake" else None,
        "expected": expected,
        "duplicate_contacts_created": duplicates_created,
        "qualification": {
            q: sum(1 for ld in leads if ld.qualification == q) for q in ("hot", "warm", "cold")
        },
        "guard_triggered": sum(1 for ld in leads if ld.guard_triggered),
        "draft_latency_s": {
            "p50": _pct(draft_latency, 0.5),
            "p95": _pct(draft_latency, 0.95),
            "n": len(draft_latency),
        },
        "form_to_reply_s": {
            "p50": _pct(reply_latency, 0.5),
            "p95": _pct(reply_latency, 0.95),
            "n": len(reply_latency),
        },
        "cost_usd": {
            "per_lead_mean": round(statistics.fmean(costs), 6) if costs else 0.0,
            "total": round(sum(costs), 4),
        },
        "incidents": len(incidents),
    }


def to_markdown(r: dict[str, Any]) -> str:
    def secs(v: float | None) -> str:
        if v is None:
            return "n/a"
        if v < 1:
            return f"{v * 1000:.0f} ms"
        return f"{v:.1f} s" if v < 120 else f"{v / 60:.1f} min"

    exp = r.get("expected") or {}
    lines = [
        "# leadintake report",
        "",
        f"Generated {r['generated_at']} · CRM `{r['crm_provider']}` · "
        f"drafts by `{r['llm_provider']}` "
        f"(`{r['draft_model']}`)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Enquiries processed | {r['leads']} |",
        f"| Flagged as a known contact (de-duplicated) | {r['duplicates_flagged']} |",
        f"| Double submissions (same message within the window) | {r['double_submissions']} |",
        f"| Enquiries with no usable contact details | {r['no_contact_details']} |",
    ]
    if r.get("crm_contacts") is not None:
        lines.append(f"| Contacts in CRM | {r['crm_contacts']} |")
        lines.append(f"| Open deals in CRM | {r['crm_deals']} |")
    if exp:
        lines.append(
            f"| Expected contacts (people with an email or phone + unmatched submissions) | "
            f"{exp['identifiable_people']} + {exp['unmatched_submissions']} |"
        )
    if r.get("duplicate_contacts_created") is not None:
        lines.append(f"| **Duplicate contacts created** | **{r['duplicate_contacts_created']}** |")
    q = r["qualification"]
    lines += [
        f"| Hot / warm / cold | {q['hot']} / {q['warm']} / {q['cold']} |",
        f"| Drafts replaced by the figures guard | {r['guard_triggered']} |",
        "| Form to draft ready, p50 / p95 | "
        f"{secs(r['draft_latency_s']['p50'])} / {secs(r['draft_latency_s']['p95'])} |",
        f"| Form to reply sent, p50 / p95 (n={r['form_to_reply_s']['n']}) | "
        f"{secs(r['form_to_reply_s']['p50'])} / {secs(r['form_to_reply_s']['p95'])} |",
        f"| LLM cost per lead, mean | ${r['cost_usd']['per_lead_mean']:.4f} |",
        f"| LLM cost, total | ${r['cost_usd']['total']:.2f} |",
        f"| Incidents logged by the error workflow | {r['incidents']} |",
        "",
        "Status: " + ", ".join(f"{k} {v}" for k, v in sorted(r["by_status"].items())),
        "",
    ]
    return "\n".join(lines)


def write_markdown(r: dict[str, Any], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_markdown(r), encoding="utf-8")
    return out
