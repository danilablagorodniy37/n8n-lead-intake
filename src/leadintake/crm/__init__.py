"""CRM adapters. `fake` keeps contacts and deals in the engine's own database so the demo and the
tests can count duplicates; `hubspot` talks to HubSpot's v3 API. A Pipedrive adapter is the same
five methods."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from .base import CRM, ContactRef, CRMError
from .fake import FakeCRM
from .hubspot import HubSpotCRM

__all__ = ["CRM", "CRMError", "ContactRef", "FakeCRM", "HubSpotCRM", "get_crm"]


def get_crm(session: Session, settings: Settings | None = None) -> CRM:
    s = settings or get_settings()
    if s.crm_provider.lower() == "hubspot":
        if not s.hubspot_access_token:
            raise CRMError("CRM_PROVIDER=hubspot but HUBSPOT_ACCESS_TOKEN is empty")
        return HubSpotCRM(
            token=s.hubspot_access_token,
            base_url=s.hubspot_base_url,
            pipeline=s.hubspot_pipeline,
            dealstage=s.hubspot_dealstage,
        )
    return FakeCRM(session)
