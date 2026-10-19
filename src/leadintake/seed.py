"""Synthetic enquiries: 200 submissions from about 120 people, with the mess a real form produces.

Duplicates come in the shapes that break naive de-duplication: the same email in a different case
with spaces around it, the same mobile written four ways, a second enquiry weeks later with a new
phone, and the double click that posts the same message twice. Some enquiries have no usable
contact details at all. `person_id` is the ground truth `leadintake report` checks against.
Phone numbers use Ofcom's drama range 07700 900xxx; email domains are example.com / example.org.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

FIRST = [
    "Tom",
    "Amelia",
    "Olu",
    "Priya",
    "Jack",
    "Sophie",
    "Daniel",
    "Hannah",
    "Marek",
    "Chloe",
    "Ravi",
    "Grace",
    "Liam",
    "Fatima",
    "George",
    "Isla",
    "Kasia",
    "Harry",
    "Nadia",
    "Ben",
    "Yusuf",
    "Ella",
    "Oscar",
    "Zara",
    "Adam",
    "Lucy",
    "Mo",
    "Ivy",
    "Sam",
    "Rosa",
]
LAST = [
    "Hughes",
    "Patel",
    "Okafor",
    "Nowak",
    "Walsh",
    "Khan",
    "Bennett",
    "Rossi",
    "Clarke",
    "Singh",
    "Murphy",
    "Ahmed",
    "Taylor",
    "Kowalski",
    "Morgan",
    "Shah",
    "Reid",
    "Dubois",
    "Carter",
    "Ali",
]
PREFERRED = [
    "Staines-upon-Thames",
    "Staines",
    "Egham",
    "Ashford",
    "Sunbury",
    "Shepperton",
    "Laleham",
]
ACCEPTABLE = ["Feltham", "Twickenham", "Weybridge", "Chertsey", "Windsor"]
OUTSIDE = ["Reading", "Croydon", "Guildford", "Slough", "Kingston"]
TYPES = ["valuation", "sell", "buy", "let", "rent", "other"]
MESSAGES = {
    "valuation": [
        "Hi, could you value my 3-bed semi in {area}? Thinking of selling {when}.",
        "We would like a market appraisal of our house in {area}. {when_cap}, if possible.",
        "How much is my flat in {area} worth? Two bedrooms, leasehold, {when}.",
    ],
    "sell": [
        "Looking to put our house in {area} on the market {when}. What do you need from us?",
        "I want to sell my 2-bed terrace in {area}. Can someone call me?",
        "Selling a 4-bed detached in {area}, probate sale, {when}. Please get in touch.",
    ],
    "buy": [
        "Looking for a 3-bed house in {area}, budget around {budget}. Anything coming up?",
        "First-time buyer, {budget}, looking in {area} or nearby. Can I register with you?",
        "We are relocating and need a family home in {area}, up to {budget}, {when}.",
    ],
    "let": [
        "I am a landlord with a 2-bed flat in {area}. Do you do tenant find and full management?",
        "Want to rent out my house in {area} from next month. What are the steps?",
    ],
    "rent": [
        "Looking to rent a 1-bed in {area}, {budget} a month max, {when}.",
        "Do you have any 2-bed flats to let in {area}? Moving {when}.",
    ],
    "other": [
        "Do you handle commercial units? I have a shop in {area}.",
        "Hello, I am a local plumber, do you need trades for your managed properties?",
        "Can you recommend a solicitor for a sale in {area}?",
        "",
    ],
}
WHEN = [
    "as soon as possible",
    "this week",
    "next month",
    "in the coming weeks",
    "soon",
    "at some point next year",
    "",
]
BUDGET_FORMATS = ["£{k}k", "{k}k", "£{full:,}", "{full}", "around {k}k", "up to £{k}K"]
RENT_BUDGETS = [1200, 1500, 1800, 2200]


def _phone_variants(core: str) -> list[str]:
    """core like '7700900123' -> the ways people type it."""
    local = "0" + core
    return [
        f"{local[:5]} {local[5:]}",
        f"+44 {core[:4]} {core[4:7]} {core[7:]}",
        f"+44 (0){core}",
        f"0044{core}",
        local,
        f"{local[:5]}-{local[5:]}",
    ]


def _email_variants(email: str) -> list[str]:
    user, _, domain = email.partition("@")
    return [email, f" {email} ", email.upper(), f"{user.capitalize()}@{domain}", f"mailto:{email}"]


def generate(count: int = 200, seed: int = 20261019) -> list[dict]:
    rng = random.Random(seed)
    people = []
    for i in range(int(count * 0.6)):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        core = f"7700900{i:03d}"
        domain = rng.choice(["example.com", "example.org"])
        people.append(
            {
                "person_id": f"p{i:03d}",
                "name": f"{first} {last}",
                "email": f"{first}.{last}{i}@{domain}".lower(),
                "phone_core": core,
                "enquiry_type": rng.choices(TYPES, weights=[25, 22, 25, 10, 10, 8])[0],
                "area": rng.choices(
                    [rng.choice(PREFERRED), rng.choice(ACCEPTABLE), rng.choice(OUTSIDE)],
                    weights=[60, 25, 15],
                )[0],
            }
        )

    start = datetime(2026, 10, 1, 8, 0)
    rows: list[dict] = []
    t = start
    for p in people:
        t += timedelta(minutes=rng.randint(20, 240))
        rows.append(_submission(rng, p, t, variant=0))

    # duplicates and repeats until we reach `count`, leaving room for the unidentifiable ones
    anonymous = max(4, count // 40)
    while len(rows) < count - anonymous:
        p = rng.choice(people)
        kind = rng.choices(
            [
                "same_email_diff_case",
                "same_phone_diff_format",
                "double_click",
                "new_phone",
                "later",
            ],
            weights=[25, 30, 15, 10, 20],
        )[0]
        if kind == "double_click":
            original = next((r for r in rows if r["person_id"] == p["person_id"]), None)
            if original is None:
                continue
            copy = dict(original)
            copy["submitted_at"] = (
                datetime.fromisoformat(original["submitted_at"])
                + timedelta(seconds=rng.randint(5, 90))
            ).isoformat()
            copy["dup_kind"] = kind
            rows.append(copy)
            continue
        t += timedelta(minutes=rng.randint(20, 240))
        rows.append(_submission(rng, p, t, variant=rng.randint(1, 5), kind=kind))

    # a few enquiries with no usable contact details, and some with broken fields
    for _ in range(anonymous):
        t += timedelta(minutes=rng.randint(20, 240))
        p = rng.choice(people)
        row = _submission(rng, p, t, variant=0, kind="no_contact")
        row["email"], row["phone"] = "", rng.choice(["12345", "call me", "0770", ""])
        row["person_id"] = f"anon{len(rows):03d}"
        rows.append(row)
    rows.sort(key=lambda r: r["submitted_at"])
    return rows[:count] if len(rows) > count else rows


def _submission(
    rng: random.Random, p: dict, when: datetime, variant: int, kind: str = "first"
) -> dict:
    etype = p["enquiry_type"]
    budget = ""
    if etype == "buy":
        k = rng.choice([180, 240, 275, 320, 360, 420, 480, 550, 640, 720, 850, 1100])
        budget = rng.choice(BUDGET_FORMATS).format(k=k, full=k * 1000)
    elif etype == "rent":
        budget = f"£{rng.choice(RENT_BUDGETS):,}"
    w = rng.choice(WHEN)
    template = rng.choice(MESSAGES[etype])
    message = template.format(
        area=p["area"], when=w, when_cap=w.capitalize(), budget=budget or "my budget"
    )
    phone = _phone_variants(p["phone_core"])[variant % 6]
    email = _email_variants(p["email"])[variant % 5]
    if kind == "new_phone":
        phone = _phone_variants(f"7700901{rng.randint(0, 999):03d}")[0]
    if kind == "later":
        email = rng.choice(["", email])  # sometimes only the phone comes back
    if rng.random() < 0.08:
        phone = ""  # people skip the phone field
    name = p["name"]
    if variant % 4 == 1:
        name = name.lower()
    elif variant % 4 == 2:
        name = name.upper()
    return {
        "person_id": p["person_id"],
        "submitted_at": when.isoformat(),
        "name": name,
        "email": email,
        "phone": phone,
        "enquiry_type": etype if rng.random() < 0.7 else "",
        "area": p["area"] if rng.random() < 0.85 else "",
        "budget": budget,
        "message": message.strip(),
        "source": rng.choice(["website", "website", "website", "facebook_form"]),
        "dup_kind": kind,
    }


def write(rows: list[dict], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out


def load(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def as_form_payload(row: dict) -> dict:
    """What the website form actually posts: no ground-truth fields, no timestamp (the engine
    stamps its own, so latency figures mean something)."""
    return {k: v for k, v in row.items() if k not in ("person_id", "dup_kind", "submitted_at")}
