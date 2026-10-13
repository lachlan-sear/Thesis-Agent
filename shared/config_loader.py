"""
Config loader. Reads thesis.yaml and provides typed access.
Everything thesis-specific comes from the YAML; nothing is hard-coded here.
"""

import random
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

    if thesis.get("sectors"):
        lines.append("\nSectors:")
        for sec in thesis["sectors"]:
            lines.append(f"  [{sec['id']}] {sec['name']}: {' '.join((sec.get('description') or '').split())}")

    if thesis.get("frameworks"):
        lines.append("\nAnalytical lenses:")
        for fw in thesis["frameworks"]:
            lines.append(f"  - {fw['name']}: {fw['text']}")

    if thesis.get("portfolio_exemplars"):
        lines.append("\nPortfolio Exemplars:")
        for ex in thesis.get("portfolio_exemplars", []):
            lines.append(f"  • {ex['name']}: {ex['why']}")

    lines.append(f"\nEvaluation Rubric:")
    for k, v in thesis.get("evaluation_rubric", {}).items():
        lines.append(f"  {k}: {v}")

    # Evaluation weights (if thesis specifies custom weights)
    eval_weights = thesis.get("evaluation_weights", {})
    if eval_weights:
        lines.append(f"\nEvaluation Weights (fund-specific):")
        for k, v in eval_weights.items():
            lines.append(f"  {k}: {v}")

    autopilot = thesis.get("autopilot_lens", {})
    if autopilot.get("enabled"):
        lines.append(f"\nAutopilot Lens:\n{autopilot.get('description', '')}")

    return "\n".join(lines)


def sector_map(config: dict) -> dict[str, dict]:
    """Sector id -> sector config, in thesis order."""
    return {s["id"]: s for s in config["thesis"].get("sectors", [])}


def exclusions(config: dict) -> set[str]:
    """Lower-cased names the fund never wants scored, published or commented on."""
    return {n.lower().strip() for n in config.get("exclude_from_views") or []}


DEFAULT_TEMPLATES = [
    "{vertical} startup seed Series A 2026 Europe",
    "{vertical} startup raised funding 2026",
    "{vertical} regulation change 2026",
    "former operator founded {vertical} company",
    "{vertical} legacy software replacement AI-native",
]


def get_search_queries(config: dict) -> list[str]:
    """
    Scout's web-search queries, built entirely from thesis.yaml.

    Templates (sourcing.templates, or a neutral default set) run round-robin
    across every sector keyword, so --max-queries N gives breadth before depth.
    sourcing.thesis_queries are appended as written. Nothing here is specific
    to any one thesis: swap the YAML and the searches follow.
    """
    thesis = config["thesis"]
    sourcing = config.get("sourcing", {})
    templates = sourcing.get("templates") or DEFAULT_TEMPLATES

    keywords: list[str] = []
    for s in thesis.get("sectors", []):
        keywords.extend(s.get("keywords") or [s.get("name", "")])
    if not keywords:  # older theses without sectors
        tv = thesis.get("target_verticals", {})
        keywords = tv.get("primary", []) + tv.get("emerging", [])
    seen, ordered = set(), []
    for k in keywords:
        if k and k.lower() not in seen:
            seen.add(k.lower())
            ordered.append(k)
    random.shuffle(ordered)

    templated = [t.format(vertical=k) for t in templates for k in ordered]
    extra = list(sourcing.get("thesis_queries", []))
    # Interleave so a small --max-queries still runs some thesis-specific searches.
    queries = []
    while templated or extra:
        if extra:
            queries.append(extra.pop(0))
        queries.extend(templated[:2])
        templated = templated[2:]
    return queries
