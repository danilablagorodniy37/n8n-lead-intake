import json

import httpx
import pytest

from leadintake.crm.base import CRMError
from leadintake.crm.hubspot import HubSpotCRM
from leadintake.normalise import normalise
from tests.conftest import enquiry


def make_crm(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://hub.test")
    return HubSpotCRM(token="t", base_url="https://hub.test", client=client)


def test_search_matches_on_email_or_phone_and_creates_deal_with_association():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/crm/v3/objects/contacts/search":
            groups = body["filterGroups"]
            assert [g["filters"][0]["propertyName"] for g in groups] == ["email", "phone"]
            return httpx.Response(200, json={"results": []})
        if request.url.path == "/crm/v3/objects/contacts":
            assert body["properties"]["email"] == "tom.hughes@example.com"
            assert body["properties"]["phone"] == "+447700900123"
            return httpx.Response(201, json={"id": "101"})
        if request.url.path == "/crm/v3/objects/deals/search":
            return httpx.Response(200, json={"results": []})
        if request.url.path == "/crm/v3/objects/deals":
            assert body["associations"][0]["to"]["id"] == "101"
            assert body["associations"][0]["types"][0]["associationTypeId"] == 3
            return httpx.Response(201, json={"id": "555"})
        return httpx.Response(404)

    crm = make_crm(handler)
    n = normalise(enquiry())
    assert crm.find_contact(n.email, n.phone) is None
    ref = crm.create_contact(n)
    assert ref.id == "101" and ref.created
    assert crm.find_open_deal("101") is None
    assert crm.create_deal("101", "Valuation: Tom Hughes", None, "website") == "555"
    assert [c[1] for c in calls] == [
        "/crm/v3/objects/contacts/search",
        "/crm/v3/objects/contacts",
        "/crm/v3/objects/deals/search",
        "/crm/v3/objects/deals",
    ]


def test_existing_contact_is_patched_not_created():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/crm/v3/objects/contacts/search":
            return httpx.Response(200, json={"results": [{"id": "7"}]})
        if request.method == "PATCH" and request.url.path == "/crm/v3/objects/contacts/7":
            body = json.loads(request.content)
            assert "email" in body["properties"] and "lastname" in body["properties"]
            return httpx.Response(200, json={"id": "7"})
        return httpx.Response(500, text="unexpected")

    crm = make_crm(handler)
    n = normalise(enquiry())
    found = crm.find_contact(n.email, n.phone)
    assert found is not None and found.id == "7"
    assert crm.update_contact("7", n).id == "7"


def test_errors_surface_as_crm_error_for_n8n_retries():
    crm = make_crm(lambda request: httpx.Response(429, text="rate limited"))
    with pytest.raises(CRMError, match="429"):
        crm.find_contact("a@example.com", None)
