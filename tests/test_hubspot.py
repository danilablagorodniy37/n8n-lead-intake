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
        if request.url.path == "/crm/v4/objects/contacts/101/associations/deals":
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
        "/crm/v4/objects/contacts/101/associations/deals",
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


def test_create_conflict_returns_the_existing_contact():
    # What a live portal does on a double click: the search has not indexed the first contact yet,
    # so the create runs and HubSpot answers 409 with the contact's id.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/crm/v3/objects/contacts":
            return httpx.Response(
                409,
                json={
                    "status": "error",
                    "message": "Contact already exists. Existing ID: 895935814889",
                    "category": "CONFLICT",
                },
            )
        return httpx.Response(500, text="unexpected")

    ref = make_crm(handler).create_contact(normalise(enquiry()))
    assert ref.id == "895935814889" and not ref.created


def test_other_conflicts_still_raise():
    crm = make_crm(lambda request: httpx.Response(409, json={"message": "something else"}))
    with pytest.raises(CRMError, match="409") as e:
        crm.create_contact(normalise(enquiry()))
    assert e.value.status == 409


def test_open_deal_is_read_through_associations_and_skips_closed_deals():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/crm/v4/objects/contacts/7/associations/deals":
            return httpx.Response(200, json={"results": [{"toObjectId": 1}, {"toObjectId": 2}]})
        if request.url.path == "/crm/v3/objects/deals/batch/read":
            body = json.loads(request.content)
            assert [i["id"] for i in body["inputs"]] == ["1", "2"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "1", "properties": {"hs_is_closed": "true", "createdate": "b"}},
                        {"id": "2", "properties": {"hs_is_closed": "false", "createdate": "a"}},
                    ]
                },
            )
        return httpx.Response(500, text="unexpected")

    assert make_crm(handler).find_open_deal("7") == "2"


def test_no_open_deal_when_every_associated_deal_is_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/associations/deals"):
            return httpx.Response(200, json={"results": [{"toObjectId": 1}]})
        return httpx.Response(
            200, json={"results": [{"id": "1", "properties": {"hs_is_closed": "true"}}]}
        )

    assert make_crm(handler).find_open_deal("7") is None
