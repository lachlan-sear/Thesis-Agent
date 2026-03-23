"""
Config loader. Reads thesis.yaml and provides typed access.
"""

import yaml
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).parent.parent / "config" / "thesis.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load and return the thesis configuration."""
    with open(path) as f:
        return yaml.safe_load(f)


def get_thesis_text(config: dict) -> str:
    """Format the thesis config as readable text for Claude prompts."""
    thesis = config["thesis"]
    lines = [
        f"Fund: {thesis.get('fund', 'N/A')}",
        f"Thesis: {thesis.get('name', 'N/A')}",
        f"\nCore Belief:\n{thesis.get('core_belief', '')}",
        f"\nTarget Verticals (Primary): {', '.join(thesis.get('target_verticals', {}).get('primary', []))}",
        f"Target Verticals (Secondary): {', '.join(thesis.get('target_verticals', {}).get('secondary', []))}",
        f"Target Verticals (Emerging): {', '.join(thesis.get('target_verticals', {}).get('emerging', []))}",
        f"\nStage Focus: {thesis.get('stage_focus', {}).get('sweet_spot', 'N/A')}",
        f"Geography: {', '.join(thesis.get('geography', {}).get('primary', []))}",
        "\nPositive Signals:",
    ]
    for s in thesis.get("signals_positive", []):
        lines.append(f"  + {s}")
    lines.append("\nNegative Signals:")
    for s in thesis.get("signals_negative", []):
        lines.append(f"  - {s}")

    lines.append("\nPortfolio Exemplars:")
    for ex in thesis.get("portfolio_exemplars", []):
        lines.append(f"  • {ex['name']}: {ex['why']}")

    lines.append(f"\nEvaluation Rubric:")
    for k, v in thesis.get("evaluation_rubric", {}).items():
        lines.append(f"  {k}: {v}")

    autopilot = thesis.get("autopilot_lens", {})
    if autopilot.get("enabled"):
        lines.append(f"\nAutopilot Lens (Sequoia Framework):\n{autopilot.get('description', '')}")

    return "\n".join(lines)


def get_search_queries(config: dict) -> list[str]:
    """
    Generate search queries from thesis verticals.
    Produces targeted queries for Claude web search.
    """
    thesis = config["thesis"]
    queries = []

    all_verticals = (
        thesis.get("target_verticals", {}).get("primary", [])
        + thesis.get("target_verticals", {}).get("emerging", [])
    )

    query_templates = [
        "{vertical} startup seed funding 2026",
        "{vertical} AI startup series A 2025 2026",
        "{vertical} startup Europe UK funding",
        "new {vertical} company launch 2026",
        "{vertical} digital transformation startup",
    ]

    for vertical in all_verticals:
        for tmpl in query_templates:
            queries.append(tmpl.format(vertical=vertical))

    return queries
