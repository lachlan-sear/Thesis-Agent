"""
Config loader. Reads thesis.yaml and provides typed access.
Generates sophisticated, VC-grade search queries — not generic Google searches.
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
        lines.append(f"\nAutopilot Lens (Sequoia Framework):\n{autopilot.get('description', '')}")

    return "\n".join(lines)


def get_search_queries(config: dict) -> list[str]:
    """
    Generate sophisticated, VC-grade search queries from thesis config.

    Five query categories that mirror how top analysts actually source:
    1. Regulatory triggers — new rules creating new moats
    2. Talent signals — strong founders entering a vertical
    3. Incumbent failure — demand signal from user frustration
    4. Budget movement — outsourced spend being automated (Sequoia wedge)
    5. Investor activity — smart money validating timing
    6. Category creation — autopilot companies emerging
    7. European ecosystem — Sifted, EU-Startups, local signals
    """
    thesis = config["thesis"]
    queries = []

    primary = thesis.get("target_verticals", {}).get("primary", [])
    secondary = thesis.get("target_verticals", {}).get("secondary", [])
    emerging = thesis.get("target_verticals", {}).get("emerging", [])
    all_verticals = primary + emerging

    # --- 1. Regulatory triggers ---
    # New regulation = new moat for first movers
    regulatory_templates = [
        "{vertical} regulation change 2026",
        "{vertical} compliance new requirements Europe UK",
        "{vertical} AI regulation approval 2026",
    ]

    # --- 2. Talent signals ---
    # Ex-McKinsey, ex-Google, ex-Big4 founding in regulated verticals
    talent_templates = [
        "ex-McKinsey ex-BCG founded {vertical} startup",
        "former Google DeepMind engineer {vertical} company",
        "{vertical} startup founded by doctors lawyers operators",
    ]

    # --- 3. Incumbent failure ---
    # Hatred of status quo = demand signal
    incumbent_templates = [
        "{vertical} software complaints frustration switching",
        "{vertical} legacy system replacement AI-native",
        "replacing {vertical} practice management software",
    ]

    # --- 4. Budget movement (Sequoia wedge) ---
    # Outsourced work being automated
    budget_templates = [
        "{vertical} outsourcing automation AI agent",
        "{vertical} managed services AI replacement",
        "autonomous {vertical} workflow no human",
    ]

    # --- 5. Investor activity ---
    # Smart money moving into verticals
    investor_templates = [
        "seed series A {vertical} AI startup 2025 2026 funded",
        "Sequoia a16z {vertical} AI investment 2026",
        "European {vertical} startup funding round 2026",
    ]

    # --- 6. Category creation ---
    # New autopilot companies
    category_templates = [
        "AI-native {vertical} company launch 2026",
        "{vertical} autopilot AI startup outcomes",
        "{vertical} AI replacing outsourced services",
    ]

    # --- 7. European ecosystem ---
    european_templates = [
        "{vertical} startup Europe UK seed Series A 2026",
        "{vertical} AI company London Berlin Paris 2026",
    ]

    # Generate queries ROUND-ROBIN across verticals so that --max-queries N
    # gives breadth (one query per vertical) rather than depth (all queries
    # for the first vertical).  Shuffle vertical order each run so the same
    # vertical isn't always first.
    all_templates = (
        regulatory_templates
        + talent_templates
        + incumbent_templates
        + budget_templates
        + investor_templates
        + category_templates
        + european_templates
    )

    shuffled_verticals = list(all_verticals)
    random.shuffle(shuffled_verticals)

    for tmpl in all_templates:
        for vertical in shuffled_verticals:
            queries.append(tmpl.format(vertical=vertical))

    # --- 8. Funding intelligence — who just raised, who's about to ---
    shuffled_primary = list(primary)
    random.shuffle(shuffled_primary)
    for vertical in shuffled_primary[:3]:
        queries.append(f"{vertical} startup Series A Series B funding 2026 Europe")
        queries.append(f"{vertical} startup raised seed round 2026 UK")

    # --- Thesis-specific queries (not vertical-dependent) ---
    thesis_queries = [
        # Sequoia framework signals
        "services as software AI startup 2026",
        "AI agent replacing professional services 2026",
        "autopilot AI company seed funding Europe",
        "copilot to autopilot AI transition startup",

        # Vertical AI specific
        "vertical AI startup defensible moat 2026",
        "domain-specific AI company regulated industry",
        "vertical AI seed round Europe UK 2026",

        # Competitive intelligence
        "Y Combinator W2026 healthcare legal fintech AI",
        "Entrepreneur First London cohort 2026",
        "Antler Seedcamp portfolio 2026 AI",

        # Data flywheel / moat signals
        "AI startup proprietary dataset regulated industry",
        "healthcare legal dental AI data advantage",

        # Workforce crisis = automation opportunity
        "accountant shortage AI automation",
        "nurse doctor shortage digital health solution",
        "lawyer shortage legal AI automation UK",
        "veterinary workforce crisis technology solution",
    ]

    queries.extend(thesis_queries)

    return queries
