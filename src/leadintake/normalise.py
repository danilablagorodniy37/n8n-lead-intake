"""Turn whatever the form sent into one shape: lower-case email, E.164 phone, a budget in pounds.

Deduplication is only as good as this step. "07700 900123", "+44 (0)7700 900 123" and
"0044 7700900123" are the same person; so are "Tom@Example.com " and "tom@example.com".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import phonenumbers

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MONEY_RE = re.compile(
    r"(?i)(?:£|gbp)?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|m|thousand|million)?"
)
WS_RE = re.compile(r"\s+")
UK_MOBILE_SHAPE = re.compile(r"^7\d{9}$")

TYPE_SYNONYMS = {
    "valuation": (
        "valuation",
        "value my",
        "valued",
        "how much is my",
        "appraisal",
        "market appraisal",
    ),
    "sell": ("sell", "selling", "sale of my", "put my house on", "put our house on", "list my"),
    "buy": ("buy", "buying", "purchase", "looking for a house", "looking for a flat", "viewing"),
    "let": ("landlord", "let my", "letting my", "rent out", "rent my", "tenant find", "manage my"),
    "rent": ("rent", "renting", "to let", "tenancy", "looking to rent"),
}
CANONICAL_TYPES = ("valuation", "sell", "buy", "let", "rent", "other")


@dataclass
class Normalised:
    name: str = ""
    email: str | None = None
    phone: str | None = None
    message: str = ""
    budget_gbp: int | None = None
    area: str | None = None
    enquiry_type: str = "other"
    source: str = "website"
    problems: list[str] = field(default_factory=list)

    @property
    def dedup_key(self) -> str | None:
        return self.email or self.phone


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return WS_RE.sub(" ", str(value)).strip()


def clean_name(value: object) -> str:
    name = clean_text(value)
    if not name:
        return ""
    if name.islower() or name.isupper():
        name = " ".join(part.capitalize() for part in name.split(" "))
    return name[:120]


def clean_email(value: object) -> str | None:
    email = clean_text(value).lower().removeprefix("mailto:")
    if not email:
        return None
    return email if EMAIL_RE.match(email) else None


def clean_phone(value: object, region: str = "GB") -> str | None:
    raw = clean_text(value)
    if not raw:
        return None
    candidate = raw.replace("(0)", "")
    try:
        number = phonenumbers.parse(candidate, region)
    except phonenumbers.NumberParseException:
        return None
    if phonenumbers.is_valid_number(number):
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    # Ofcom reserves 07700 900000-900999 for fiction; libphonenumber calls them "possible" but not
    # "valid". A ten-digit UK number starting with 7 is a mobile shape, so keep it.
    national = phonenumbers.national_significant_number(number)
    if (
        phonenumbers.is_possible_number(number)
        and phonenumbers.region_code_for_number(number) in (region, None)
        and UK_MOBILE_SHAPE.match(national)
    ):
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    return None


def parse_budget(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value) if value > 0 else None
    text = clean_text(value).lower()
    if not text:
        return None
    match = MONEY_RE.search(text)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    if unit in ("k", "thousand"):
        amount *= 1_000
    elif unit in ("m", "million"):
        amount *= 1_000_000
    elif amount < 10_000 and "k" not in text:
        # "250" on a property form almost always means thousands of pounds
        amount *= 1_000
    return int(amount) if amount > 0 else None


def infer_type(explicit: object, message: str) -> str:
    text = clean_text(explicit).lower()
    if text in CANONICAL_TYPES:
        return text
    haystack = f"{text} {message.lower()}"
    for canonical, words in TYPE_SYNONYMS.items():
        if any(w in haystack for w in words):
            return canonical
    return "other"


def normalise(raw: dict, region: str = "GB") -> Normalised:
    """Accept the usual form field names and a few aliases; never raise on bad input."""
    get = _getter(raw)
    message = clean_text(get("message", "enquiry", "comments", "notes", "body"))
    n = Normalised(
        name=clean_name(get("name", "full_name", "fullname")),
        email=clean_email(get("email", "e-mail", "mail")),
        phone=clean_phone(get("phone", "telephone", "mobile", "tel"), region),
        message=message,
        budget_gbp=parse_budget(get("budget", "budget_gbp", "price")),
        area=clean_text(get("area", "postcode", "location", "town")) or None,
        enquiry_type=infer_type(get("enquiry_type", "type", "reason", "subject"), message),
        source=clean_text(get("source")) or "website",
    )
    if get("email", "e-mail", "mail") and not n.email:
        n.problems.append("email_invalid")
    if get("phone", "telephone", "mobile", "tel") and not n.phone:
        n.problems.append("phone_invalid")
    if not n.email and not n.phone:
        n.problems.append("no_contact_details")
    if not n.message:
        n.problems.append("empty_message")
    if not n.name:
        n.name = "there"
        n.problems.append("no_name")
    return n


def _getter(raw: dict):
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}

    def get(*keys: str) -> object:
        for key in keys:
            value = lowered.get(key)
            if value not in (None, ""):
                return value
        return None

    return get
