"""Settings. Everything is an environment variable or a line in `.env`; see `.env.example`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# USD per million tokens [input, output]. Configured values, not a price list: check the provider's
# pricing page and override with MODEL_PRICES in .env.
DEFAULT_MODEL_PRICES: dict[str, list[float]] = {
    "claude-haiku-5-5": [0.10, 0.50],
    "claude-sonnet-5-5": [3.0, 15.0],
    "gpt-4.1-mini": [0.40, 1.60],
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # storage
    database_url: str = "sqlite:///data/leadintake.sqlite"

    # CRM: fake (tables in the same database, counted by `leadintake report`) | hubspot
    crm_provider: str = "fake"
    hubspot_access_token: str = ""
    hubspot_pipeline: str = "default"
    hubspot_dealstage: str = "appointmentscheduled"
    hubspot_base_url: str = "https://api.hubapi.com"

    # drafting: anthropic | openai | fake | auto (anthropic if keyed, else openai, else fake)
    llm_provider: str = "auto"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    draft_model: str = "claude-haiku-5-5"
    model_prices: dict[str, list[float]] = DEFAULT_MODEL_PRICES

    # behaviour
    criteria_path: str = "criteria.yaml"
    default_region: str = "GB"
    duplicate_window_hours: int = 24
    # A CRM's search can trail its writes (HubSpot: seconds). For this long after the engine wrote
    # a contact, a repeat with the same email or phone reuses it even if the search misses it.
    crm_search_lag_seconds: int = 120
    api_token: str = ""  # if set, every request must carry "Authorization: Bearer <token>"
    seed_path: str = "seed/enquiries.jsonl"

    def price_for(self, model: str) -> tuple[float, float]:
        p = self.model_prices.get(model) or [0.0, 0.0]
        return float(p[0]), float(p[1])

    def ensure_data_dir(self) -> None:
        if self.database_url.startswith("sqlite:///"):
            path = self.database_url.removeprefix("sqlite:///")
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_data_dir()
    return s
