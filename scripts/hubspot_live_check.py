"""Run a slice of the seed through the engine against a real HubSpot portal and count duplicates.

    HUBSPOT_ACCESS_TOKEN=... python scripts/hubspot_live_check.py --markdown docs/hubspot.md

Use a developer test account, not a client's portal: the script creates real contacts and deals.
It picks two people for every kind of repeat in the seed plus eight one-off enquirers, tags every
email (name+run@example.org) and shifts the last three digits of every phone, so each run starts
clean without deleting anything. The seed's phones sit in Ofcom's drama range (07700 900000 to
900999), so the shift is chosen to collide with no phone already in the portal; otherwise a "new"
person would rightly be matched to an earlier run's contact. Then it posts the enquiries back to
back. That is harsher than real
traffic: a double click lands while HubSpot's search index still trails the first write. Drafting
uses the template drafter, so no model is called and nothing is spent.

After the run it waits for the index, then asks HubSpot how many contacts match each person's
email or phone, and how many deals each contact has. A correct run is one contact and one deal
per person.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def pick(rows: list[dict], per_kind: int = 2, singles: int = 8) -> list[dict]:
    """Every enquiry of two people per kind of repeat, plus `singles` one-off enquirers."""
    by_person: dict[str, list[int]] = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by_person[r["person_id"]].append(i)
    kinds: dict[str, list[str]] = collections.defaultdict(list)
    for pid, idx in by_person.items():
        for i in idx[1:]:
            if pid not in kinds[rows[i]["dup_kind"]]:
                kinds[rows[i]["dup_kind"]].append(pid)
    chosen: list[str] = []
    for pids in kinds.values():
        for pid in pids[:per_kind]:
            if pid not in chosen:
                chosen.append(pid)
    chosen += [pid for pid, idx in by_person.items() if len(idx) == 1][:singles]
    return [rows[i] for i in sorted(i for pid in chosen for i in by_person[pid])]


def tag(row: dict, run: str, offset: int) -> dict:
    """Same person structure, new identifiers: email gets +run, the phone's last 3 digits shift."""
    out = dict(row)
    email = row.get("email") or ""
    if "@" in email:
        local, _, domain = email.partition("@")
        out["email"] = f"{local}+{run}@{domain}"

    def shift(m: re.Match) -> str:
        return f"{(int(m.group(1)) + offset) % 1000:03d}{m.group(2)}"

    out["phone"] = re.sub(r"(\d{3})(\D*)$", shift, row.get("phone") or "")
    return out


def existing_phones(crm) -> set[str]:
    """Every phone already in the portal, so the run's shifted phones can avoid them."""
    from leadintake.normalise import clean_phone

    phones: set[str] = set()
    after = None
    while True:
        params = {"limit": 100, "properties": "phone"} | ({"after": after} if after else {})
        data = crm._request("GET", "/crm/v3/objects/contacts", params=params)
        for r in data.get("results") or []:
            if p := clean_phone((r.get("properties") or {}).get("phone"), "GB"):
                phones.add(p)
        after = ((data.get("paging") or {}).get("next") or {}).get("after")
        if not after:
            return phones


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", default=str(ROOT / "seed" / "enquiries.jsonl"))
    ap.add_argument("--run", default=datetime.now(UTC).strftime("r%m%d%H%M"))
    ap.add_argument("--index-wait", type=float, default=30, help="seconds before counting")
    ap.add_argument("--markdown", help="write the result table to this file")
    args = ap.parse_args()
    if not os.environ.get("HUBSPOT_ACCESS_TOKEN"):
        print("set HUBSPOT_ACCESS_TOKEN (a developer test account's service key)", file=sys.stderr)
        return 2

    db = Path(tempfile.mkdtemp()) / "live.sqlite"
    os.environ.update(
        CRM_PROVIDER="hubspot",
        LLM_PROVIDER="fake",
        DATABASE_URL=f"sqlite:///{db.as_posix()}",
        CRITERIA_PATH=str(ROOT / "criteria.yaml"),
    )
    from leadintake.crm.hubspot import HubSpotCRM
    from leadintake.db import session_scope
    from leadintake.normalise import clean_email, clean_phone
    from leadintake.pipeline import intake
    from leadintake.report import expected_contacts
    from leadintake.seed import as_form_payload

    rows = [json.loads(line) for line in Path(args.seed).read_text(encoding="utf-8").splitlines()]
    picked = pick(rows)

    class Counting(HubSpotCRM):
        """Counts which layer recognised each repeat."""

        conflicts = 0  # search missed it, the create answered 409 with the existing id
        searched_none = False

        def find_contact(self, email, phone):
            ref = super().find_contact(email, phone)
            Counting.searched_none = ref is None
            return ref

        def create_contact(self, n):
            ref = super().create_contact(n)
            Counting.conflicts += not ref.created
            return ref

    crm = Counting(
        token=os.environ["HUBSPOT_ACCESS_TOKEN"],
        base_url=os.environ.get("HUBSPOT_BASE_URL", "https://api.hubapi.com"),
    )
    taken = existing_phones(crm)
    start = int(hashlib.sha1(args.run.encode()).hexdigest(), 16) % 999
    for step in range(999):
        offset = 1 + (start + step) % 999
        sample = [tag(r, args.run, offset) for r in picked]
        if not {clean_phone(r.get("phone"), "GB") for r in sample} & taken:
            break
    else:
        print("no phone offset is free of existing contacts", file=sys.stderr)
        return 2
    print(f"{len(taken)} phones already in the portal; phone offset {offset}")

    run_started = datetime.now(UTC)
    started = time.monotonic()
    caught = collections.Counter()
    false_merges = 0
    with session_scope() as session:
        for i, row in enumerate(sample, 1):
            before = Counting.conflicts
            lead = intake(as_form_payload(row), session, crm=crm)
            false_merges += lead.is_duplicate and row["dup_kind"] == "first"
            if lead.is_duplicate:
                if not Counting.searched_none:
                    caught["search"] += 1
                elif Counting.conflicts > before:
                    caught["409"] += 1
                else:
                    caught["engine"] += 1
            flag = "dup " if lead.is_duplicate else "    "
            print(
                f"{i:3d} {flag}{row['dup_kind']:24s} contact {lead.contact_id} deal {lead.deal_id}"
            )
    elapsed = time.monotonic() - started

    print(f"waiting {args.index_wait:.0f} s for HubSpot's search index")
    time.sleep(args.index_wait)

    keys: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for row in sample:
        e, p = clean_email(row.get("email")), clean_phone(row.get("phone"), "GB")
        keys[row["person_id"]].update(k for k in (("email", e), ("phone", p)) if k[1])

    found: dict[str, set[str]] = {}
    older = 0  # contacts that existed before the run: a sign of a false merge
    for pid, pairs in keys.items():
        if not pairs:
            continue
        groups = [
            {"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}
            for prop, value in sorted(pairs)
        ]
        data = crm._request(
            "POST",
            "/crm/v3/objects/contacts/search",
            json={"filterGroups": groups[:5], "properties": ["createdate"], "limit": 10},
        )
        results = data.get("results") or []
        found[pid] = {str(r["id"]) for r in results}
        older += sum(
            1
            for r in results
            if datetime.fromisoformat(r["properties"]["createdate"].replace("Z", "+00:00"))
            < run_started
        )

    contact_ids = {cid for ids in found.values() for cid in ids}
    deal_counts = {}
    for cid in contact_ids:
        assoc = crm._request("GET", f"/crm/v4/objects/contacts/{cid}/associations/deals")
        deal_counts[cid] = len(assoc.get("results") or [])

    exp = expected_contacts(sample)
    dup_people = [pid for pid, ids in found.items() if len(ids) > 1]
    repeats = collections.Counter(r["dup_kind"] for r in sample if r["dup_kind"] != "first")
    lines = [
        "# HubSpot live run",
        "",
        f"Run `{args.run}` on {datetime.now(UTC):%d %b %Y %H:%M} UTC against a HubSpot developer "
        "test account, with `scripts/hubspot_live_check.py`. Enquiries posted back to back; "
        "template drafter, so no model calls. Engine fallback window "
        f"`CRM_SEARCH_LAG_SECONDS={os.environ.get('CRM_SEARCH_LAG_SECONDS', '120')}`.",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Enquiries / people | {len(sample)} / {len(keys)} |",
        f"| Repeats in the sample | {sum(repeats.values())} |",
        f"| Contacts in HubSpot / expected | {len(contact_ids)} / {exp['identifiable_people']} |",
        f"| People with more than one contact | {len(dup_people)} |",
        f"| First enquiries merged into someone else's contact | {false_merges} |",
        f"| Matched contacts created before this run | {older} |",
        f"| Contacts with more than one deal | {sum(1 for n in deal_counts.values() if n > 1)} |",
        f"| Contacts without a deal | {sum(1 for n in deal_counts.values() if n == 0)} |",
        f"| Repeats found by HubSpot search | {caught['search']} |",
        f"| Repeats the search missed, caught by the engine's own record | {caught['engine']} |",
        f'| Repeats the search missed, caught by the 409 "already exists" | {caught["409"]} |',
        f"| Time per enquiry, engine and HubSpot API | {elapsed / len(sample):.2f} s |",
        "",
        "Repeats by kind: " + ", ".join(f"{k} {v}" for k, v in repeats.items()) + ".",
        "",
    ]
    md = "\n".join(lines)
    print(md)
    if args.markdown:
        Path(args.markdown).write_text(md, encoding="utf-8")
        print(f"written to {args.markdown}")
    ok = (
        not dup_people
        and not false_merges
        and not older
        and len(contact_ids) == exp["identifiable_people"]
        and all(n == 1 for n in deal_counts.values())
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
