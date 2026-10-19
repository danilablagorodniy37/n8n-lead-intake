"""HubSpot CRM v3 adapter: search by email or phone, create or patch the contact, one open deal.

Needs a private app token with crm.objects.contacts and crm.objects.deals read/write scopes.
Every call raises CRMError on a non-2xx response so n8n's retry and error workflow see it.
"""

from __future__ import annotations

import httpx

from ..normalise import Normalised
from .base import ContactRef, CRMError

DEAL_TO_CONTACT = 3  # HubSpot-defined association type id


class HubSpotCRM:
    name = "hubspot"

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.hubapi.com",
        pipeline: str = "default",
        dealstage: str = "appointmentscheduled",
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.pipeline = pipeline
        self.dealstage = dealstage
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 300:
            raise CRMError(
                f"HubSpot {method} {path} -> {response.status_code}: {response.text[:300]}"
            )
        return response.json() if response.content else {}

    def find_contact(self, email: str | None, phone: str | None) -> ContactRef | None:
        groups = []
        if email:
            groups.append(
                {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
            )
        if phone:
            groups.append(
                {"filters": [{"propertyName": "phone", "operator": "EQ", "value": phone}]}
            )
        if not groups:
            return None
        data = self._request(
            "POST",
            "/crm/v3/objects/contacts/search",
            json={"filterGroups": groups, "properties": ["email", "phone"], "limit": 1},
        )
        results = data.get("results") or []
        return ContactRef(id=str(results[0]["id"])) if results else None

    def create_contact(self, n: Normalised) -> ContactRef:
        data = self._request(
            "POST", "/crm/v3/objects/contacts", json={"properties": self._properties(n)}
        )
        return ContactRef(id=str(data["id"]), created=True)

    def update_contact(self, contact_id: str, n: Normalised) -> ContactRef:
        props = {k: v for k, v in self._properties(n).items() if v}
        self._request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json={"properties": props})
        return ContactRef(id=contact_id)

    def find_open_deal(self, contact_id: str) -> str | None:
        data = self._request(
            "POST",
            "/crm/v3/objects/deals/search",
            json={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "associations.contact",
                                "operator": "EQ",
                                "value": contact_id,
                            },
                            {"propertyName": "hs_is_closed", "operator": "EQ", "value": "false"},
                        ]
                    }
                ],
                "properties": ["dealname"],
                "limit": 1,
            },
        )
        results = data.get("results") or []
        return str(results[0]["id"]) if results else None

    def create_deal(self, contact_id: str, title: str, amount: int | None, source: str) -> str:
        props = {"dealname": title, "pipeline": self.pipeline, "dealstage": self.dealstage}
        if amount:
            props["amount"] = str(amount)
        data = self._request(
            "POST",
            "/crm/v3/objects/deals",
            json={
                "properties": props,
                "associations": [
                    {
                        "to": {"id": contact_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": DEAL_TO_CONTACT,
                            }
                        ],
                    }
                ],
            },
        )
        return str(data["id"])

    @staticmethod
    def _properties(n: Normalised) -> dict[str, str]:
        first, _, last = (n.name if n.name != "there" else "").partition(" ")
        return {
            "email": n.email or "",
            "phone": n.phone or "",
            "firstname": first,
            "lastname": last,
            "hs_lead_status": "NEW",
        }
