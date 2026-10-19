from types import SimpleNamespace

from leadintake.config import Settings
from leadintake.draft import (
    AnthropicDrafter,
    FakeDrafter,
    draft_with_guard,
    get_drafter,
    unsupported_figures,
)
from leadintake.normalise import normalise
from leadintake.scoring import score
from tests.conftest import enquiry


def test_template_names_the_person_and_asks_for_missing(criteria):
    n = normalise({"name": "priya patel", "email": "p@example.com", "message": "Looking to buy"})
    d = FakeDrafter().draft(n, score(n, criteria), criteria)
    assert d.text.startswith("Hi Priya,")
    assert (
        "a phone number" in d.text
        and "the area or postcode" in d.text
        and "a rough budget" in d.text
    )
    assert "Hollis & Grey" in d.text
    assert "—" not in d.text


def test_guard_finds_figures_not_in_the_enquiry():
    bad = unsupported_figures(
        "Our fee is 1.5% and valuations start at £350.", ["Budget around £250k"]
    )
    assert bad == ["1.5%", "£350"]
    assert unsupported_figures("Your budget of £250k is fine.", ["Budget around £250k"]) == []


class InventingDrafter:
    name, model = "stub", "stub"

    def draft(self, n, sc, criteria):
        from leadintake.draft import Draft

        return Draft(
            subject="Hi",
            text="We charge 1.5% commission, so about £4,500 for you.",
            provider="stub",
        )


def test_guard_replaces_an_inventing_draft(criteria):
    n = normalise(enquiry())
    d = draft_with_guard(InventingDrafter(), n, score(n, criteria), criteria)
    assert d.guard_triggered
    assert "1.5%" not in d.text and "£4,500" not in d.text
    assert d.text.startswith("Hi Tom,")


def test_auto_provider_falls_back_to_fake_without_keys():
    s = Settings(llm_provider="auto", anthropic_api_key="", openai_api_key="")
    assert get_drafter(s).name == "fake"


def test_anthropic_drafter_parses_tool_call_and_costs_it(criteria):
    class StubMessages:
        def create(self, **kwargs):
            assert kwargs["tool_choice"] == {"type": "tool", "name": "write_reply"}
            block = SimpleNamespace(
                type="tool_use",
                input={"subject": "Your valuation", "body": "Hi Tom,\nThanks.\nKind regards"},
            )
            return SimpleNamespace(
                content=[block], usage=SimpleNamespace(input_tokens=1000, output_tokens=200)
            )

    stub = SimpleNamespace(messages=StubMessages())
    s = Settings(draft_model="claude-haiku-5-5", anthropic_api_key="x")
    d = AnthropicDrafter(s, client=stub).draft(
        normalise(enquiry()), score(normalise(enquiry()), criteria), criteria
    )
    assert d.subject == "Your valuation"
    assert d.tokens_in == 1000 and d.tokens_out == 200
    assert abs(d.cost_usd - (1000 * 0.10 + 200 * 0.50) / 1_000_000) < 1e-9
