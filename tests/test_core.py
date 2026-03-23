"""
Tests for thesis-agent core logic.
Run with: python -m pytest tests/ -v
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.models import Evaluation, Action, RawCandidate, Stage, EnrichedCompany


class TestEvaluationScoring:
    """Test the composite score calculation."""

    def test_composite_with_all_scores(self):
        """Full scores should produce a weighted average."""
        ev = Evaluation(
            company_name="TestCo",
            customer_durability=8,
            unit_economics=7,
            regulation_moat=9,
            growth_inflection=6,
            founder_quality=8,
            thesis_fit=9,
            autopilot_potential=7,
        )
        score = ev.compute_composite()
        assert 7.0 <= score <= 9.0, f"Expected 7-9, got {score}"
        assert ev.composite_score == score

    def test_composite_with_partial_scores(self):
        """Missing scores should be excluded from the average."""
        ev = Evaluation(
            company_name="PartialCo",
            thesis_fit=8,
            regulation_moat=9,
            # All others are None
        )
        score = ev.compute_composite()
        assert score > 0, "Partial scores should still produce a composite"
        assert 8.0 <= score <= 9.0, f"Expected ~8.5, got {score}"

    def test_composite_with_no_scores(self):
        """No scores should return 0."""
        ev = Evaluation(company_name="EmptyCo")
        score = ev.compute_composite()
        assert score == 0.0

    def test_action_defaults_to_skip(self):
        """Default action should be skip."""
        ev = Evaluation(company_name="DefaultCo")
        assert ev.action == Action.SKIP

    def test_high_score_suggests_track(self):
        """A manually set track action should persist."""
        ev = Evaluation(
            company_name="GoodCo",
            action=Action.TRACK,
            thesis_fit=9,
            regulation_moat=8,
        )
        assert ev.action == Action.TRACK


class TestRawCandidate:
    """Test raw candidate model."""

    def test_candidate_creation(self):
        c = RawCandidate(
            name="Lupa Pets",
            url="https://lupapets.com",
            description="AI-native veterinary PMS",
            source="web_search",
        )
        assert c.name == "Lupa Pets"
        assert c.source == "web_search"
        assert c.discovered_at is not None

    def test_candidate_without_url(self):
        c = RawCandidate(
            name="StealthCo",
            description="Pre-launch stealth company",
            source="companies_house",
        )
        assert c.url is None


class TestEnrichedCompany:
    """Test enriched company model."""

    def test_enriched_with_evaluation(self):
        ev = Evaluation(
            company_name="TestCo",
            thesis_fit=8,
            action=Action.TRACK,
            one_liner="Test company doing test things",
        )
        ev.compute_composite()

        company = EnrichedCompany(
            name="TestCo",
            description="Test company",
            vertical="healthcare AI",
            stage=Stage.SEED,
            evaluation=ev,
            source="enriched",
        )
        assert company.vertical == "healthcare AI"
        assert company.evaluation.composite_score > 0


class TestConfigLoader:
    """Test thesis config loading."""

    def test_config_loads(self):
        from shared.config_loader import load_config
        config = load_config()
        assert "thesis" in config
        assert "name" in config["thesis"]

    def test_search_queries_generated(self):
        from shared.config_loader import load_config, get_search_queries
        config = load_config()
        queries = get_search_queries(config)
        assert len(queries) > 0, "Should generate at least one search query"
        # Verify queries contain thesis-relevant terms
        all_queries = " ".join(queries).lower()
        assert any(term in all_queries for term in ["healthcare", "legal", "dental", "veterinary"]), \
            "Queries should contain thesis vertical terms"

    def test_thesis_text_formatting(self):
        from shared.config_loader import load_config, get_thesis_text
        config = load_config()
        text = get_thesis_text(config)
        assert len(text) > 100, "Thesis text should be substantial"
        assert "Positive Signals" in text


class TestDatabase:
    """Test database operations."""

    def test_init_db(self):
        from shared.db import init_db
        init_db()  # Should not raise

    def test_seen_tracking(self):
        from shared.db import init_db, is_seen, mark_seen
        init_db()
        assert not is_seen("UniqueTestCompany12345")
        mark_seen("UniqueTestCompany12345", source="test")
        assert is_seen("UniqueTestCompany12345")


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
