"""
Tests for the weekly pipeline: source checks, the tracker, refresh and publish.
No network and no API calls: pages and the model are faked.
Run with: python -m pytest tests/ -v
"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import verify, tracker  # noqa: E402
from shared.config_loader import load_config, get_search_queries, sector_map  # noqa: E402

PAGE = ("Isembard raises $50 million Series A led by Union Square Ventures. "
        "La Fraise raises €3,2M. Legora acquires Wexler, the London litigation start-up.")


def fake_fetch(url):
    return verify.normalise(PAGE) if "good" in url else None


class TestAmounts:
    @pytest.mark.parametrize("text,expected", [
        ("$50M", ("USD", 50.0)), ("$50 million", ("USD", 50.0)), ("€3,2M", ("EUR", 3.2)),
        ("£4.5m", ("GBP", 4.5)), ("$1.5B", ("USD", 1500.0)), ("USD 72.5 million", ("USD", 72.5)),
        ("32 million euros", ("EUR", 32.0)),
    ])
    def test_parse(self, text, expected):
        assert verify.parse_amount(text) == expected

    def test_thousands_separator_is_not_decimal(self):
        assert verify.parse_amount("$1,200M") == ("USD", 1200.0)

    def test_currency_must_match(self):
        assert not verify.amount_in("£50M", "raised $50 million")


class TestSourceCheck:
    def test_round_supported(self):
        ok, _, _ = verify.check("Isembard", {"kind": "round", "amount": "$50M", "source": "https://good"}, [], fake_fetch)
        assert ok

    def test_wrong_amount_held(self):
        ok, reason, _ = verify.check("Isembard", {"kind": "round", "amount": "$60M", "source": "https://good"}, [], fake_fetch)
        assert not ok and "does not state" in reason

    def test_wrong_company_held(self):
        ok, _, _ = verify.check("Neuracore", {"kind": "round", "amount": "$50M", "source": "https://good"}, [], fake_fetch)
        assert not ok

    def test_exit_needs_acquirer(self):
        good = verify.check("Wexler", {"kind": "exit", "acquirer": "Legora", "source": "https://good"}, [], fake_fetch)
        bad = verify.check("Wexler", {"kind": "exit", "acquirer": "Harvey", "source": "https://good"}, [], fake_fetch)
        assert good[0] and not bad[0]

    def test_unreadable_page_falls_back_to_search_quote(self):
        cites = [{"url": "https://paywalled", "cited_text": "Isembard has raised $50m in a Series A"}]
        ok, _, _ = verify.check("Isembard", {"kind": "round", "amount": "$50M", "source": "https://paywalled"}, cites, fake_fetch)
        assert ok

    def test_no_source_is_never_applied(self):
        ok, _, _ = verify.check("Isembard", {"kind": "round", "amount": "$50M"}, [], fake_fetch)
        assert not ok


class TestThesisAndTracker:
    def test_live_tracker_is_valid(self):
        cfg = load_config()
        assert tracker.validate(tracker.load(), set(sector_map(cfg))) == []

    def test_weights_sum_to_one(self):
        w = load_config()["thesis"]["evaluation_weights"]
        assert abs(sum(w.values()) - 1) < 0.01

    def test_queries_cover_every_sector(self):
        cfg = load_config()
        qs = " ".join(get_search_queries(cfg)).lower()
        for s in cfg["thesis"]["sectors"]:
            assert any(k.lower() in qs for k in s["keywords"]), s["id"]

    def test_no_reader_firm_names_in_config(self):
        text = (Path(__file__).parent.parent / "config" / "thesis.yaml").read_text().lower()
        assert "earlybird" not in text

    def test_example_thesis_reorients(self):
        sports = load_config(Path(__file__).parent.parent / "examples" / "theses" / "sports-tech.yaml")
        assert {s["id"] for s in sports["thesis"]["sectors"]} != set(sector_map(load_config()))
        assert get_search_queries(sports)


class FakeClient:
    def __init__(self, answers):
        self.answers = answers

    def search(self, prompt, task_type, system):
        name = prompt.split("\n", 1)[0].replace("Company: ", "")
        return json.dumps(self.answers.get(name, {"changes": [], "summary": "No change found"})), []


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    rows = [
        {"id": 1, "name": "Isembard", "sector": "robotics", "status": "tracking", "description": "x",
         "lastRound": {"round": "Seed", "amount": "$9M", "date": "2025-04", "source": "https://good"},
         "lastVerified": "2026-01-01", "verifiedBy": "manual", "sources": ["https://good"], "raisedUsdM": 9.0},
        {"id": 2, "name": "Wexler", "sector": "regulated", "status": "tracking", "description": "x",
         "lastVerified": "2026-01-01", "verifiedBy": "manual", "sources": ["https://good"]},
        {"id": 3, "name": "Neuracore", "sector": "robotics", "status": "tracking", "description": "x",
         "lastVerified": "2026-01-01", "verifiedBy": "manual", "sources": ["https://good"]},
    ]
    monkeypatch.setattr(tracker, "DATA", tmp_path)
    monkeypatch.setattr(tracker, "TRACKER_PATH", tmp_path / "companies.json")
    import agents.refresh.refresh as refresh
    monkeypatch.setattr(refresh, "REVIEW_PATH", tmp_path / "review.json")
    tracker.save(rows, tmp_path / "companies.json")
    return tmp_path


def test_refresh_applies_only_what_sources_support(sandbox):
    from agents.refresh.refresh import run_refresh
    answers = {
        "Isembard": {"changes": [{"kind": "round", "round": "Series A", "amount": "$50M", "date": "2026-03",
                                  "leads": "Union Square Ventures", "source": "https://good"}]},
        "Wexler": {"changes": [{"kind": "exit", "acquirer": "Legora", "type": "acquisition",
                                "date": "2026-07", "state": "announced", "source": "https://good"}]},
        # A hallucinated round: the cited page says nothing about Neuracore.
        "Neuracore": {"changes": [{"kind": "round", "round": "Seed", "amount": "$50M", "date": "2026-05",
                                   "source": "https://good"}]},
    }
    result = run_refresh(config=load_config(), client=FakeClient(answers), fetch=fake_fetch, today=date(2026, 10, 19))
    rows = {r["name"]: r for r in tracker.load(sandbox / "companies.json")}
    assert rows["Isembard"]["stage"] == "Series A" and rows["Isembard"]["lastRound"]["amount"] == "$50M"
    assert rows["Wexler"]["status"] == "exited" and rows["Wexler"]["exit"]["acquirer"] == "Legora"
    assert rows["Neuracore"].get("lastRound") is None
    held = json.loads((sandbox / "review.json").read_text())
    assert [h["company"] for h in held] == ["Neuracore"]
    assert len(result["applied"]) == 2 and result["held"] == 1


def test_publish_hides_excluded_companies(sandbox, monkeypatch):
    import shared.publish as publish
    for name in ("DATA", "LAST_RUN", "EDITIONS", "OUT", "CANDIDATES", "REVIEW"):
        monkeypatch.setattr(publish, name, sandbox / {"DATA": "", "LAST_RUN": "last_run.json", "EDITIONS": "editions",
                                                      "OUT": "observatory.json", "CANDIDATES": "candidates.json",
                                                      "REVIEW": "review.json"}[name])
    (sandbox / "last_run.json").write_text(json.dumps({"date": "2026-10-19", "checked": 3, "applied": [], "held": 0}))
    cfg = load_config()
    cfg["exclude_from_views"] = ["Neuracore"]
    out = publish.build(cfg)
    assert "Neuracore" not in {c["name"] for c in out["companies"]}
    assert out["edition"]["number"] == 1 and out["method"]["excludedCount"] == 1


def test_provider_follows_whichever_key_is_set(monkeypatch):
    import importlib
    import shared.claude_client as cc
    for k in ("THESIS_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert cc.provider() == "openrouter"
    monkeypatch.setenv("THESIS_PROVIDER", "openai")
    assert cc.provider() == "openai"


def test_openai_citations_never_count_as_source_text():
    """A model's own sentence must not be able to verify itself."""
    cites = [{"url": "https://paywalled", "title": "", "cited_text": ""}]
    ok, _, _ = verify.check("Isembard", {"kind": "round", "amount": "$50M", "source": "https://paywalled"}, cites, fake_fetch)
    assert not ok


class TestFalseAccepts:
    """Cases from the 13 Oct review: common-word names must not pass on unrelated text."""

    def page(self, text):
        return lambda url: verify.normalise(text)

    def test_tony_stark_ceasefire_is_not_a_shutdown(self):
        f = self.page("Tony Stark visited Berlin as the ceasefire talks resumed.")
        assert not verify.check("Stark", {"kind": "shutdown", "source": "https://x"}, [], f)[0]

    def test_anterior_ligament_is_not_a_shutdown(self):
        f = self.page("Anterior cruciate ligament injuries: the Food and Drug Administration approved a brace.")
        assert not verify.check("Anterior", {"kind": "shutdown", "source": "https://x"}, [], f)[0]

    def test_amount_far_from_name_is_rejected(self):
        filler = " lorem" * 120
        f = self.page("Humanoid robots are booming." + filler + " Figure raised $152M last week.")
        assert not verify.check("Humanoid", {"kind": "round", "amount": "$152M", "source": "https://x"}, [], f)[0]

    def test_orca_whale_is_not_orca_ai(self):
        f = self.page("An orca was seen off Norway; the trip raised $72.5M for charity.")
        assert not verify.check("Orca.AI", {"kind": "round", "amount": "$72.5M", "source": "https://x"}, [], f)[0]

    def test_alias_counts(self):
        f = self.page("ConductorOne, now C1, agreed to be acquired by Workday.")
        assert verify.check("C1", {"kind": "exit", "acquirer": "Workday", "source": "https://x"}, [], f, aliases=["ConductorOne"])[0]

    def test_nav_word_listing_is_not_an_exit(self):
        f = self.page("Wexler | Legora | Product listing | Pricing")
        assert not verify.check("Wexler", {"kind": "exit", "acquirer": "Legora", "source": "https://x"}, [], f)[0]

    def test_citation_url_normalised(self):
        cites = [{"url": "https://www.example.com/a/?utm_source=x", "cited_text": "Isembard raised $50m in a Series A"}]
        ok, _, _ = verify.check("Isembard", {"kind": "round", "amount": "$50M", "source": "https://example.com/a"}, cites, lambda u: None)
        assert ok


def test_empty_model_variable_falls_back_to_default(monkeypatch):
    import importlib
    import shared.claude_client as cc
    monkeypatch.setenv("THESIS_MODEL_FAST", "")
    monkeypatch.setenv("THESIS_PROVIDER", "anthropic")
    importlib.reload(cc)
    assert cc.FAST == "claude-sonnet-5-5"


def test_older_round_is_held_not_dropped(sandbox):
    from agents.refresh.refresh import run_refresh
    answers = {"Isembard": {"changes": [{"kind": "round", "round": "Pre-Seed", "amount": "$50M", "date": "2024-01",
                                         "source": "https://good"}]}}
    run_refresh(config=load_config(), client=FakeClient(answers), fetch=fake_fetch, today=date(2026, 10, 19))
    held = json.loads((sandbox / "review.json").read_text())
    assert held and "older" in held[0]["reason"]
