"""A CRM in two tables. Enough to prove the upsert is idempotent and to count duplicates."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Contact, Deal, utcnow
from ..normalise import Normalised
from .base import ContactRef


class FakeCRM:
    name = "fake"

    def __init__(self, session: Session):
        self.session = session

    def find_contact(self, email: str | None, phone: str | None) -> ContactRef | None:
        clauses = []
        if email:
            clauses.append(Contact.email == email)
        if phone:
            clauses.append(Contact.phone == phone)
        if not clauses:
            return None
        row = self.session.scalars(
            select(Contact).where(or_(*clauses)).order_by(Contact.created_at)
        ).first()
        return ContactRef(id=row.id) if row else None

    def create_contact(self, n: Normalised) -> ContactRef:
        row = Contact(email=n.email, phone=n.phone, name=n.name, enquiries=1)
        self.session.add(row)
        self.session.flush()
        return ContactRef(id=row.id, created=True)

    def update_contact(self, contact_id: str, n: Normalised) -> ContactRef:
        row = self.session.get(Contact, contact_id)
        if row is None:
            return self.create_contact(n)
        row.email = row.email or n.email
        row.phone = row.phone or n.phone
        if (not row.name or row.name == "there") and n.name:
            row.name = n.name
        row.enquiries += 1
        row.updated_at = utcnow()
        self.session.flush()
        return ContactRef(id=row.id)

    def find_open_deal(self, contact_id: str) -> str | None:
        row = self.session.scalars(
            select(Deal).where(Deal.contact_id == contact_id, Deal.open.is_(True))
        ).first()
        return row.id if row else None

    def create_deal(self, contact_id: str, title: str, amount: int | None, source: str) -> str:
        row = Deal(contact_id=contact_id, title=title, amount=amount, stage=f"new ({source})")
        self.session.add(row)
        self.session.flush()
        return row.id

    # used by `leadintake report`
    def counts(self) -> dict[str, int]:
        contacts = self.session.scalars(select(Contact)).all()
        deals = self.session.scalars(select(Deal)).all()
        return {"contacts": len(contacts), "deals": len(deals)}
