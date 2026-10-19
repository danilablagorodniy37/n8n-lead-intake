"""Draft the reply the owner will approve. A template without a key, a model with one.

Whatever writes the draft, the figures guard runs after it: a reply must not contain a pound
amount or a percentage that was not in the enquiry itself. An invented fee never reaches the owner
as a ready draft; the template takes over and the lead is marked `guard_triggered`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from .config import Settings, get_settings
from .normalise import Normalised
from .scoring import Score

FIGURE_RE = re.compile(r"(?i)(?:£|gbp\s?)\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m)?\b|\b\d+(?:\.\d+)?\s?%")

TYPE_LABEL = {
    "valuation": "a valuation",
    "sell": "selling your property",
    "buy": "buying in the area",
    "let": "letting your property",
    "rent": "renting",
    "other": "your enquiry",
}
MISSING_LABEL = {
    "email": "an email address",
    "phone": "a phone number",
    "area": "the area or postcode",
    "budget": "a rough budget",
    "what they want": "a line on what you are looking for",
}


@dataclass
class Draft:
    subject: str
    text: str
    provider: str = "fake"
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    guard_triggered: bool = False
    notes: list[str] = field(default_factory=list)


class Drafter(Protocol):
    name: str
    model: str

    def draft(self, n: Normalised, sc: Score, criteria: dict) -> Draft: ...


def first_name(n: Normalised) -> str:
    return n.name.split(" ")[0] if n.name and n.name != "there" else "there"


def template_reply(n: Normalised, sc: Score, criteria: dict) -> tuple[str, str]:
    biz = criteria.get("business", {})
    label = TYPE_LABEL.get(n.enquiry_type, TYPE_LABEL["other"])
    where = f" in {n.area}" if n.area else ""
    subject = f"Your enquiry about {label}" if n.enquiry_type != "other" else "Your enquiry"
    lines = [f"Hi {first_name(n)},", "", f"Thanks for getting in touch about {label}{where}."]
    asks = [MISSING_LABEL[m] for m in sc.missing if m in MISSING_LABEL]
    if asks:
        lines.append(f"So we can help properly, could you let us know {_join(asks)}?")
    next_step = criteria.get("reply_rules", {}).get(
        "next_step", "a 15-minute call or a visit, whichever suits"
    )
    lines.append(
        f"The quickest next step is {next_step}. "
        "Would this week or early next week suit you better?"
    )
    reply_by = biz.get("reply_by", "the next working day")
    lines += ["", f"We will come back to you by {reply_by} at the latest.", ""]
    lines.append(biz.get("signature", "Kind regards").rstrip())
    return subject, "\n".join(lines)


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


class FakeDrafter:
    name = "fake"
    model = "template"

    def draft(self, n: Normalised, sc: Score, criteria: dict) -> Draft:
        subject, text = template_reply(n, sc, criteria)
        return Draft(subject=subject, text=text, provider=self.name, model=self.model)


def _system_prompt(criteria: dict) -> str:
    biz = criteria.get("business", {})
    rules = criteria.get("reply_rules", {})
    never = "\n".join(f"- never {r}" for r in rules.get("never", []))
    always = "\n".join(f"- always {r}" for r in rules.get("always", []))
    return (
        f"You write short, warm, plain-English replies to website enquiries on behalf of "
        f"{biz.get('name', 'the business')}. British spelling. "
        f"At most {rules.get('max_words', 120)} "
        f"words in the body. No em dashes, no exclamation marks, no bullet points.\n"
        f"Rules:\n{never}\n{always}\n"
        f"End the body with exactly this signature:\n{biz.get('signature', 'Kind regards')}"
    )


def _user_prompt(n: Normalised, sc: Score) -> str:
    asks = [MISSING_LABEL[m] for m in sc.missing if m in MISSING_LABEL]
    return json.dumps(
        {
            "enquiry": {
                "name": n.name,
                "type": n.enquiry_type,
                "area": n.area,
                "budget_gbp": n.budget_gbp,
                "message": n.message or "(empty)",
            },
            "lead_qualification": sc.qualification,
            "details_to_ask_for": asks,
            "address_them_as": first_name(n),
        },
        ensure_ascii=False,
    )


_TOOL = {
    "name": "write_reply",
    "description": "The reply email to the enquiry.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Email subject, under 60 characters"},
            "body": {"type": "string", "description": "Plain-text email body with the signature"},
        },
        "required": ["subject", "body"],
    },
}


class AnthropicDrafter:
    name = "anthropic"

    def __init__(self, settings: Settings, client=None):
        self.model = settings.draft_model
        self._prices = settings.price_for(self.model)
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._client = client

    def draft(self, n: Normalised, sc: Score, criteria: dict) -> Draft:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=700,
            system=_system_prompt(criteria),
            messages=[{"role": "user", "content": _user_prompt(n, sc)}],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "write_reply"},
        )
        payload = next(
            (b.input for b in response.content if getattr(b, "type", "") == "tool_use"), None
        )
        if not payload:
            raise RuntimeError("model returned no write_reply tool call")
        tokens_in = int(getattr(response.usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(response.usage, "output_tokens", 0) or 0)
        return Draft(
            subject=str(payload.get("subject", "Your enquiry")).strip()[:200],
            text=str(payload.get("body", "")).strip(),
            provider=self.name,
            model=self.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=(tokens_in * self._prices[0] + tokens_out * self._prices[1]) / 1_000_000,
        )


class OpenAIDrafter:
    name = "openai"

    def __init__(self, settings: Settings, client=None):
        self.model = (
            settings.draft_model if settings.draft_model.startswith("gpt") else "gpt-4.1-mini"
        )
        self._prices = settings.price_for(self.model)
        if client is None:
            import openai  # optional dependency: pip install "leadintake[openai]"

            client = openai.OpenAI(api_key=settings.openai_api_key)
        self._client = client

    def draft(self, n: Normalised, sc: Score, criteria: dict) -> Draft:
        response = self._client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": _system_prompt(criteria)
                    + '\nReply as JSON: {"subject": "...", "body": "..."}',
                },
                {"role": "user", "content": _user_prompt(n, sc)},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        return Draft(
            subject=str(payload.get("subject", "Your enquiry")).strip()[:200],
            text=str(payload.get("body", "")).strip(),
            provider=self.name,
            model=self.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=(tokens_in * self._prices[0] + tokens_out * self._prices[1]) / 1_000_000,
        )


def get_drafter(settings: Settings | None = None) -> Drafter:
    s = settings or get_settings()
    provider = s.llm_provider.lower()
    if provider == "auto":
        if s.anthropic_api_key:
            provider = "anthropic"
        elif s.openai_api_key:
            provider = "openai"
        else:
            provider = "fake"
    if provider == "anthropic":
        return AnthropicDrafter(s)
    if provider == "openai":
        return OpenAIDrafter(s)
    return FakeDrafter()


def unsupported_figures(text: str, allowed_sources: list[str]) -> list[str]:
    """Pound amounts and percentages in `text` that do not appear in any of the allowed sources."""
    allowed = " ".join(allowed_sources).lower()
    allowed_digits = set(re.findall(r"\d[\d,]*(?:\.\d+)?", allowed))
    allowed_digits |= {d.replace(",", "") for d in allowed_digits}
    bad = []
    for match in FIGURE_RE.findall(text):
        digits = re.search(r"\d[\d,]*(?:\.\d+)?", match)
        if not digits:
            continue
        value = digits.group(0)
        if value not in allowed_digits and value.replace(",", "") not in allowed_digits:
            bad.append(match.strip())
    return bad


def draft_with_guard(drafter: Drafter, n: Normalised, sc: Score, criteria: dict) -> Draft:
    d = drafter.draft(n, sc, criteria)
    sources = [
        n.message,
        str(n.budget_gbp or ""),
        criteria.get("business", {}).get("signature", ""),
    ]
    bad = unsupported_figures(d.text, sources)
    if bad or not d.text.strip():
        subject, text = template_reply(n, sc, criteria)
        d.notes.append(
            "guard: replaced draft, unsupported figures " + ", ".join(bad)
            if bad
            else "guard: empty draft replaced by template"
        )
        d.subject, d.text, d.guard_triggered = subject, text, True
    return d
