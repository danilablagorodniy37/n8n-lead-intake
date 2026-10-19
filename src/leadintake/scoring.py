"""Score a lead against the owner's criteria in `criteria.yaml`. Deterministic, no model involved.

The owner edits a YAML file, not a prompt: which areas they cover, what budget is worth a visit,
which enquiry types pay, which words mean "this week". Every point comes with a reason so the
Telegram message can say why a lead is hot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .normalise import Normalised

HOT, WARM, COLD = "hot", "warm", "cold"


@dataclass
class Score:
    points: int
    qualification: str
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@lru_cache
def load_criteria(path: str = "criteria.yaml") -> dict:
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("weights", {})
    data.setdefault("thresholds", {"hot": 70, "warm": 40})
    data.setdefault("areas", {"preferred": [], "acceptable": []})
    data.setdefault("budget_gbp", {"min": 0, "sweet_spot": [0, 10**9]})
    data.setdefault("enquiry_types", {})
    data.setdefault("urgency_keywords", {"high": [], "medium": []})
    return data


def _area_points(n: Normalised, c: dict, weight: int) -> tuple[int, str | None, str | None]:
    if not n.area:
        return 0, None, "area"
    area = n.area.lower()
    preferred = [a.lower() for a in c["areas"].get("preferred", [])]
    acceptable = [a.lower() for a in c["areas"].get("acceptable", [])]
    if any(p in area or area in p for p in preferred):
        return weight, f"area {n.area}: core patch", None
    if any(a in area or area in a for a in acceptable):
        return weight // 2, f"area {n.area}: covered, not core", None
    return 0, f"area {n.area}: outside the patch", None


def _budget_points(n: Normalised, c: dict, weight: int) -> tuple[int, str | None, str | None]:
    if n.enquiry_type in ("valuation", "sell", "let"):
        # the vendor's budget is irrelevant; the property value is unknown until the visit
        return weight // 2, None, None
    if n.budget_gbp is None:
        return 0, None, "budget"
    minimum = int(c["budget_gbp"].get("min", 0))
    low, high = c["budget_gbp"].get("sweet_spot", [0, 10**9])
    if n.budget_gbp < minimum:
        return 0, f"budget £{n.budget_gbp:,}: below the £{minimum:,} minimum", None
    if low <= n.budget_gbp <= high:
        return weight, f"budget £{n.budget_gbp:,}: in the sweet spot", None
    return weight // 2, f"budget £{n.budget_gbp:,}: workable", None


def _type_points(n: Normalised, c: dict, weight: int) -> tuple[int, str | None]:
    table = c["enquiry_types"]
    if not table:
        return weight // 2, None
    top = max(table.values()) or 1
    value = int(table.get(n.enquiry_type, 0))
    points = round(weight * value / top)
    return points, f"{n.enquiry_type}: {value}/{top} on the owner's list"


def _urgency_points(n: Normalised, c: dict, weight: int) -> tuple[int, str | None]:
    text = n.message.lower()
    if any(w.lower() in text for w in c["urgency_keywords"].get("high", [])):
        return weight, "urgent wording"
    if any(w.lower() in text for w in c["urgency_keywords"].get("medium", [])):
        return weight // 2, "wants to move soon"
    return 0, None


def _completeness_points(n: Normalised, weight: int) -> tuple[int, str | None, list[str]]:
    missing = []
    if not n.email:
        missing.append("email")
    if not n.phone:
        missing.append("phone")
    if not missing:
        return weight, "email and phone given", missing
    if len(missing) == 1:
        return weight // 2, None, missing
    return 0, "no usable contact details", missing


def score(n: Normalised, criteria: dict | None = None) -> Score:
    c = criteria or load_criteria()
    w = {"area": 25, "budget": 25, "type": 30, "urgency": 10, "completeness": 10} | c["weights"]
    reasons: list[str] = []
    missing: list[str] = []
    total = 0

    pts, why, miss = _area_points(n, c, int(w["area"]))
    total += pts
    reasons += [why] if why else []
    missing += [miss] if miss else []

    pts, why, miss = _budget_points(n, c, int(w["budget"]))
    total += pts
    reasons += [why] if why else []
    missing += [miss] if miss else []

    pts, why = _type_points(n, c, int(w["type"]))
    total += pts
    reasons += [why] if why else []

    pts, why = _urgency_points(n, c, int(w["urgency"]))
    total += pts
    reasons += [why] if why else []

    pts, why, miss = _completeness_points(n, int(w["completeness"]))
    total += pts
    reasons += [why] if why else []
    missing += miss

    if "empty_message" in n.problems:
        missing.append("what they want")

    thresholds = c["thresholds"]
    if total >= int(thresholds.get("hot", 70)):
        qualification = HOT
    elif total >= int(thresholds.get("warm", 40)):
        qualification = WARM
    else:
        qualification = COLD
    return Score(
        points=min(total, 100), qualification=qualification, reasons=reasons, missing=missing
    )
