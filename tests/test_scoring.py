from leadintake.normalise import normalise
from leadintake.scoring import score
from tests.conftest import enquiry


def test_hot_lead_in_core_area_with_urgency(criteria):
    sc = score(normalise(enquiry()), criteria)
    assert sc.qualification == "hot"
    assert sc.points >= 70
    assert any("core patch" in r for r in sc.reasons)
    assert any("urgent" in r for r in sc.reasons)
    assert sc.missing == []


def test_buyer_below_minimum_budget_is_cold_or_warm(criteria):
    sc = score(
        normalise(
            enquiry(
                enquiry_type="buy",
                budget="£180k",
                area="Reading",
                message="Looking to buy at some point",
            )
        ),
        criteria,
    )
    assert sc.qualification in ("cold", "warm")
    assert any("below" in r for r in sc.reasons)
    assert any("outside" in r for r in sc.reasons)


def test_missing_details_are_listed(criteria):
    sc = score(
        normalise({"name": "x", "email": "x@example.com", "message": "Looking to buy"}), criteria
    )
    assert "phone" in sc.missing
    assert "area" in sc.missing
    assert "budget" in sc.missing


def test_empty_message_asks_what_they_want(criteria):
    sc = score(normalise({"name": "x", "email": "x@example.com", "message": ""}), criteria)
    assert "what they want" in sc.missing


def test_points_never_exceed_100(criteria):
    sc = score(normalise(enquiry(message="urgent asap this week")), criteria)
    assert 0 <= sc.points <= 100
