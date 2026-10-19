import pytest
from sqlalchemy import select

from leadintake import pipeline
from leadintake.models import Contact, Deal, Lead
from leadintake.report import build_report, expected_contacts
from leadintake.seed import as_form_payload
from tests.conftest import enquiry


def test_same_person_three_ways_is_one_contact_and_one_deal(session):
    a = pipeline.intake(enquiry(), session)
    b = pipeline.intake(
        enquiry(email=" TOM.HUGHES@example.com ", phone="", message="Any news?"), session
    )
    c = pipeline.intake(
        enquiry(email="", phone="+44 (0)7700 900123", message="Still waiting"), session
    )
    assert a.contact_id == b.contact_id == c.contact_id
    assert a.deal_id == b.deal_id == c.deal_id
    assert (a.is_duplicate, b.is_duplicate, c.is_duplicate) == (False, True, True)
    assert session.scalar(select(Contact).where(Contact.id == a.contact_id)).enquiries == 3
    assert len(session.scalars(select(Deal)).all()) == 1


def test_double_submission_is_flagged_as_repeat(session):
    a = pipeline.intake(enquiry(), session)
    b = pipeline.intake(enquiry(), session)
    assert b.repeat_of == a.id
    assert a.repeat_of is None


def test_new_phone_for_known_email_updates_the_contact(session):
    a = pipeline.intake(enquiry(phone=""), session)
    b = pipeline.intake(enquiry(phone="07700 900999"), session)
    contact = session.get(Contact, a.contact_id)
    assert b.contact_id == a.contact_id
    assert contact.phone == "+447700900999"


def test_no_contact_details_creates_separate_contacts(session):
    a = pipeline.intake({"name": "Anon", "message": "hello"}, session)
    b = pipeline.intake({"name": "Anon", "message": "hello again"}, session)
    assert a.contact_id != b.contact_id
    assert "no_contact_details" in a.problems


def test_seed_of_200_produces_zero_duplicate_contacts(session, seed_rows):
    for row in seed_rows:
        pipeline.intake(as_form_payload(row), session)
    expected = expected_contacts(seed_rows)
    contacts = session.scalars(select(Contact)).all()
    assert len(contacts) == expected["identifiable_people"] + expected["unmatched_submissions"]
    r = build_report(session, seed_path="/nonexistent")  # report without the seed file
    assert r["leads"] == len(seed_rows)
    assert r["duplicates_flagged"] > 30
    assert all(ld.status == "pending_approval" for ld in session.scalars(select(Lead)))


def test_state_machine_refuses_to_send_without_a_decision(session):
    lead = pipeline.intake(enquiry(), session)
    with pytest.raises(pipeline.InvalidTransition):
        pipeline.mark_sent(session, lead.id)
    pipeline.decide(session, lead.id, "approve", by="owner")
    sent = pipeline.mark_sent(session, lead.id)
    assert sent.status == "sent" and sent.final_text == sent.draft_text
    with pytest.raises(pipeline.InvalidTransition):
        pipeline.decide(session, lead.id, "reject")


def test_reject_and_edit_paths(session):
    a = pipeline.intake(enquiry(), session)
    pipeline.decide(session, a.id, "reject")
    with pytest.raises(pipeline.InvalidTransition):
        pipeline.mark_sent(session, a.id)
    b = pipeline.intake(enquiry(email="b@example.com", phone=""), session)
    with pytest.raises(pipeline.InvalidTransition):
        pipeline.decide(session, b.id, "edit", text="")
    edited = pipeline.decide(session, b.id, "edit", text="Hi Tom, call me on Monday.")
    assert edited.status == "edited" and edited.final_text.startswith("Hi Tom, call me")
    assert pipeline.mark_sent(session, b.id).status == "sent"


def test_approval_message_carries_the_lead_marker(session):
    lead = pipeline.intake(enquiry(), session)
    text = pipeline.approval_message(lead)
    assert text.startswith("<b>HOT lead, score")
    assert f"#lead {lead.id}" in text
    assert "Draft reply" in text


def test_approval_message_is_safe_for_telegram_html(session):
    lead = pipeline.intake(
        enquiry(name="Tom <script> & Co", message="Is 3 < 4 & 5 > 2? <b>bold</b>"), session
    )
    text = pipeline.approval_message(lead)
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "&amp;" in text and "<b>bold</b>" not in text
    # the only tags are the bold ones we add ourselves
    import re

    assert set(re.findall(r"</?([a-z]+)>", text)) == {"b"}
