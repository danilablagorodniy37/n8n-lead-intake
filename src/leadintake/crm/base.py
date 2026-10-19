from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..normalise import Normalised


class CRMError(RuntimeError):
    pass


@dataclass
class ContactRef:
    id: str
    created: bool = False


class CRM(Protocol):
    name: str

    def find_contact(self, email: str | None, phone: str | None) -> ContactRef | None: ...

    def create_contact(self, n: Normalised) -> ContactRef: ...

    def update_contact(self, contact_id: str, n: Normalised) -> ContactRef: ...

    def find_open_deal(self, contact_id: str) -> str | None: ...

    def create_deal(self, contact_id: str, title: str, amount: int | None, source: str) -> str: ...
