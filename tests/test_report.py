from leadintake import pipeline
from leadintake.report import build_report, to_markdown
from leadintake.seed import as_form_payload, generate, write


def test_report_counts_duplicates_against_the_seed(session, tmp_path):
    rows = generate(120)
    seed_file = write(rows, tmp_path / "seed.jsonl")
    for row in rows:
        lead = pipeline.intake(as_form_payload(row), session)
        if lead.qualification == "hot":
            pipeline.decide(session, lead.id, "approve")
            pipeline.mark_sent(session, lead.id)
    r = build_report(session, seed_path=str(seed_file))
    assert r["leads"] == 120
    assert r["duplicate_contacts_created"] == 0
    assert r["expected"]["identifiable_people"] > 0
    assert r["form_to_reply_s"]["n"] == r["by_status"].get("sent", 0) > 0
    md = to_markdown(r)
    assert "**Duplicate contacts created** | **0**" in md
    assert "Enquiries processed | 120" in md


def test_seed_is_deterministic_and_messy():
    a, b = generate(200), generate(200)
    assert a == b
    assert len(a) == 200
    kinds = {r["dup_kind"] for r in a}
    assert {
        "first",
        "same_email_diff_case",
        "same_phone_diff_format",
        "double_click",
        "no_contact",
    } <= kinds
    assert sum(1 for r in a if not r["email"] and not r["phone"]) >= 4
