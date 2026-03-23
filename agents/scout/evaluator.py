"""
Scout Evaluator.
Takes raw candidates and scores them against the thesis using Claude.
Returns structured evaluations with composite scores and recommendations.
"""

import json
from shared.claude_client import get_client
from shared.config_loader import get_thesis_text
from shared.models import RawCandidate, Evaluation, Action


EVALUATOR_SYSTEM = """You are a senior investment analyst at {fund_name}.
Your job is to evaluate startup companies against the fund's investment thesis.
Be rigorous. A 7+ composite means you'd recommend the partner take a first meeting.
Most companies should score 4-6. Reserve 8+ for exceptional thesis fit.

THESIS:
{thesis_text}

CRITICAL RULES:
- Score only on available information. If data is insufficient, say so.
- Never hallucinate investors, funding amounts, or team backgrounds.
- If you don't know something, score that dimension as null.
- Be especially attentive to the 'autopilot potential' dimension — is this
  company selling the work (outcome) or selling the tool?
- Compare against portfolio exemplars for calibration.

Return ONLY valid JSON matching the schema below. No markdown, no preamble."""


EVALUATOR_SCHEMA = """{
  "company_name": "string",
  "customer_durability": int or null,    // 1-10
  "unit_economics": int or null,         // 1-10
  "regulation_moat": int or null,        // 1-10
  "growth_inflection": int or null,      // 1-10
  "founder_quality": int or null,        // 1-10
  "thesis_fit": int or null,             // 1-10
  "autopilot_potential": int or null,    // 1-10
  "one_liner": "string — what they do and why it matters, one sentence",
  "bull_case": "string — 2 sentences max",
  "bear_case": "string — 2 sentences max",
  "action": "track" | "watch" | "skip",
  "reasoning": "string — 3 sentences max on why this action"
}"""


def evaluate_candidate(
    candidate: RawCandidate,
    config: dict,
) -> Evaluation:
    """Evaluate a single candidate against the thesis."""
    client = get_client()
    thesis = config["thesis"]

    system = EVALUATOR_SYSTEM.format(
        fund_name=thesis.get("fund", "the fund"),
        thesis_text=get_thesis_text(config),
    )

    prompt = f"""Evaluate this company:

Name: {candidate.name}
URL: {candidate.url or 'N/A'}
Description: {candidate.description}
Source: {candidate.source}
Additional context: {candidate.raw_context or 'None'}

Return your evaluation as JSON matching this schema:
{EVALUATOR_SCHEMA}"""

    try:
        result = client.complete_json(
            task_type="evaluate",
            system=system,
            prompt=prompt,
        )

        eval_obj = Evaluation(
            company_name=result.get("company_name", candidate.name),
            customer_durability=result.get("customer_durability"),
            unit_economics=result.get("unit_economics"),
            regulation_moat=result.get("regulation_moat"),
            growth_inflection=result.get("growth_inflection"),
            founder_quality=result.get("founder_quality"),
            thesis_fit=result.get("thesis_fit"),
            autopilot_potential=result.get("autopilot_potential"),
            one_liner=result.get("one_liner", ""),
            bull_case=result.get("bull_case", ""),
            bear_case=result.get("bear_case", ""),
            action=Action(result.get("action", "skip")),
            reasoning=result.get("reasoning", ""),
        )
        eval_obj.compute_composite()
        return eval_obj

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # Fallback: return a skip evaluation
        return Evaluation(
            company_name=candidate.name,
            action=Action.SKIP,
            reasoning=f"Evaluation failed: {str(e)}",
        )


def evaluate_batch(
    candidates: list[RawCandidate],
    config: dict,
) -> list[Evaluation]:
    """Evaluate a batch of candidates. Returns sorted by composite score."""
    evaluations = []
    for candidate in candidates:
        ev = evaluate_candidate(candidate, config)
        evaluations.append(ev)
        print(f"  [{ev.action.value.upper():5s}] {ev.composite_score:4.1f} — {candidate.name}: {ev.one_liner[:80]}")

    evaluations.sort(key=lambda e: e.composite_score, reverse=True)
    return evaluations
