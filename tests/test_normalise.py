import pytest

from leadintake.normalise import (
    clean_email,
    clean_name,
    clean_phone,
    infer_type,
    normalise,
    parse_budget,
)


@pytest.mark.parametrize(
    "raw",
    [
        "07700 900123",
        "+44 7700 900 123",
        "+44 (0)7700 900123",
        "00447700900123",
        "07700-900123",
        "7700900123",
    ],
)
def test_same_uk_mobile_in_six_spellings(raw):
    assert clean_phone(raw) == "+447700900123"


def test_landline_and_foreign_numbers():
    assert clean_phone("020 7946 0000") == "+442079460000"
    assert clean_phone("+1 202 555 0143") == "+12025550143"


@pytest.mark.parametrize("raw", ["12345", "call me", "0770", "", None, "+44 0000"])
def test_rubbish_phones_become_none(raw):
    assert clean_phone(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["tom@example.com", " Tom@Example.com ", "TOM@EXAMPLE.COM", "mailto:tom@example.com"],
)
def test_email_variants_collapse(raw):
    assert clean_email(raw) == "tom@example.com"


def test_bad_emails_become_none():
    assert clean_email("tom at example dot com") is None
    assert clean_email("@example.com") is None
    assert clean_email("") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("£250k", 250_000),
        ("250k", 250_000),
        ("£250,000", 250_000),
        ("250000", 250_000),
        ("around 1.2m", 1_200_000),
        ("up to £450K", 450_000),
        ("350", 350_000),
        (420000, 420_000),
        ("", None),
        ("no idea", None),
    ],
)
def test_budget_parsing(raw, expected):
    assert parse_budget(raw) == expected


def test_names():
    assert clean_name("  tom   hughes ") == "Tom Hughes"
    assert clean_name("TOM HUGHES") == "Tom Hughes"
    assert clean_name("Fiona McDonald") == "Fiona McDonald"


def test_type_inference_from_message():
    assert infer_type("", "Could you value my flat?") == "valuation"
    assert infer_type("", "I am a landlord and want to rent out my house") == "let"
    assert infer_type("sell", "") == "sell"
    assert infer_type("", "Do you handle commercial units?") == "other"


def test_normalise_records_problems_without_raising():
    n = normalise({"name": "", "email": "nope", "phone": "123", "message": "   "})
    assert n.name == "there"
    assert n.email is None and n.phone is None
    assert set(n.problems) >= {
        "email_invalid",
        "phone_invalid",
        "no_contact_details",
        "empty_message",
        "no_name",
    }


def test_normalise_accepts_field_aliases():
    n = normalise(
        {
            "Full_Name": "amelia khan",
            "E-mail": "A@Example.org",
            "Mobile": "07700 900001",
            "Comments": "Valuation please",
            "Postcode": "TW18",
        }
    )
    assert (n.name, n.email, n.phone, n.area, n.enquiry_type) == (
        "Amelia Khan",
        "a@example.org",
        "+447700900001",
        "TW18",
        "valuation",
    )
