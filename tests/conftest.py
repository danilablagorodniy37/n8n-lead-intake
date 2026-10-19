from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 't.sqlite').as_posix()}")
    monkeypatch.setenv("CRM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("API_TOKEN", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CRITERIA_PATH", str(ROOT / "criteria.yaml"))
    monkeypatch.setenv("SEED_PATH", str(ROOT / "seed" / "enquiries.jsonl"))
    from leadintake import db
    from leadintake.config import get_settings

    get_settings.cache_clear()
    db.reset_engine()
    yield
    get_settings.cache_clear()
    db.reset_engine()


@pytest.fixture
def session():
    from leadintake.db import session_factory

    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from leadintake.api import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def criteria():
    from leadintake.scoring import load_criteria

    return load_criteria(str(ROOT / "criteria.yaml"))


@pytest.fixture
def seed_rows():
    from leadintake.seed import generate

    return generate(200)


def enquiry(**overrides) -> dict:
    base = {
        "name": "tom hughes",
        "email": "Tom.Hughes@Example.com",
        "phone": "07700 900123",
        "enquiry_type": "valuation",
        "area": "Staines-upon-Thames",
        "message": "Could you value my 3-bed semi? Thinking of selling this week.",
    }
    return base | overrides
