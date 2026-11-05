"""
Scout Evaluator.
Takes raw candidates and scores them against the thesis using Claude.
Returns structured evaluations with composite scores and recommendations.

The lenses and the scoring dimensions both come from thesis.yaml,
so a different fund gets a different evaluator without touching code.
"""

import json
from shared.claude_client import get_client
from shared.config_loader import get_thesis_text
from shared.models import RawCandidate, Evaluation, Action


EVALUATOR_SYSTEM = """You are a senior investment analyst at a venture fund.
Your job: decide whether a company deserves a first meeting with a partner,
judged against THIS fund's thesis and nothing else.

THESIS:
{thesis_text}

SCORE EACH DIMENSION 1-10 (null when there is not enough information):
{rubric}

SCORING CALIBRATION:
- 1-3 weak or off-thesis; 4-6 interesting but not meeting-ready;
- 7 strong, clear thesis fit; 8-9 exceptional; 10 almost never.
Most companies score 4-6. A composite of 7+ means you would stake your
reputation on the partner taking the meeting.

RULES:
- Score only on available information. Missing data = null, never a guess.
- Never invent investors, amounts, customers or founder backgrounds.
- Name the moat, the wedge and the main risk specifically.
- Compare against the best companies in the sector, not the average.

Return ONLY valid JSON matching the schema. No markdown, no preamble."""


def build_schema(rubric: dict) -> str:
    dims = ",\n".join(f'    "{k}": int or null' for k in rubric)
    return """{
  "company_name": "string",
  "scores": {
""" + dims + """
  },
  "moat_type": "regulatory or approval" | "data" | "workflow" | "network" | "none" | "unknown",
  "funding_detail": "known rounds, leads and follow-on status, or empty",
  "gtm_strategy": "how it reaches buyers, including any procurement route",
  "exit_comparables": "named acquirers or comparable exits, or empty",
  "one_liner": "what they do and why it matters, one sentence",
  "bull_case": "2 sentences max, specific upside",
  "bear_case": "2 sentences max, the actual risk",
  "action": "track" | "watch" | "skip",
  "reasoning": "3 sentences: the moat, the wedge, why this action"
}"""


def evaluate_candidate(
    candidate: RawCandidate,
    config: dict,
) -> Evaluation:
    """Evaluate a single candidate against the thesis."""
    client = get_client()
    thesis = config["thesis"]

    rubric = thesis.get("evaluation_rubric", {})
    system = EVALUATOR_SYSTEM.format(
        thesis_text=get_thesis_text(config),
        rubric="\n".join(f"- {k}: {v}" for k, v in rubric.items()),
    )

    prompt = f"""Evaluate this company:

Name: {candidate.name}
URL: {candidate.url or 'N/A'}
Description: {candidate.description}
Source: {candidate.source}
Additional context: {candidate.raw_context or 'None'}

Apply each analytical lens in the thesis, then score every dimension.

Return your evaluation as JSON matching this schema:
{build_schema(rubric)}"""

    try:
        result = client.complete_json(
            task_type="evaluate",
            system=system,
            prompt=prompt,
        )

        scores = {k: v for k, v in (result.get("scores") or {}).items()
                  if k in rubric and (v is None or (isinstance(v, int) and 1 <= v <= 10))}
        eval_obj = Evaluation(
            company_name=result.get("company_name", candidate.name),
            scores=scores,
            moat_type=result.get("moat_type", ""),
            funding_detail=result.get("funding_detail", ""),
            gtm_strategy=result.get("gtm_strategy", ""),
            exit_comparables=result.get("exit_comparables", ""),
            one_liner=result.get("one_liner", ""),
            bull_case=result.get("bull_case", ""),
            bear_case=result.get("bear_case", ""),
            action=Action(result.get("action", "skip")),
            reasoning=result.get("reasoning", ""),
        )
        # Use thesis-specific weights if available
        thesis_weights = thesis.get("evaluation_weights") or {k: 1.0 for k in rubric}
        eval_obj.compute_composite(custom_weights=thesis_weights)
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
        try:
            ev = evaluate_candidate(candidate, config)
        except Exception as e:  # budget reached or API trouble: keep what's done
            print(f"  [STOP] evaluation stopped: {e}")
            break
        evaluations.append(ev)
        print(f"  [{ev.action.value.upper():5s}] {ev.composite_score:4.1f} — {candidate.name}: {ev.one_liner[:80]}")

    evaluations.sort(key=lambda e: e.composite_score, reverse=True)
    return evaluations


def triage(candidates: list[RawCandidate], config: dict, keep: int = 15, batch: int = 60) -> list[RawCandidate]:
    """
    One cheap pass over every candidate before the full evaluation. The model
    sees name, source and a line of description, 60 at a time, and returns the
    ones that plausibly fit the thesis and are real operating companies. Only
    the best `keep` go on to the (much more expensive) per-company evaluation.
    """
    if len(candidates) <= keep:
        return candidates
    client = get_client()
    system = ("You triage deal-sourcing leads against an investment thesis. Most leads are noise: "
              "open-source repos, VCs, articles, big incumbents, or companies outside the thesis. "
              "Keep only real, private, early-to-growth-stage operating companies that plausibly fit.\n\n"
              + get_thesis_text(config))
    scored: dict[int, int] = {}
    for start in range(0, len(candidates), batch):
        chunk = candidates[start:start + batch]
        lines = "\n".join(f"{start + i}. {c.name} [{c.source}] {(c.description or '')[:160]}"
                           for i, c in enumerate(chunk))
        prompt = (f"Leads:\n{lines}\n\nReturn JSON: {{\"keep\": [{{\"i\": <number>, \"fit\": <1-10>}}]}} "
                  f"listing only leads with fit 6 or more. No commentary.")
        try:
            out = client.complete_json("evaluate", system, prompt, max_tokens=1500)
            for row in out.get("keep", []):
                i, fit = int(row.get("i", -1)), int(row.get("fit", 0))
                if start <= i < start + len(chunk) and fit >= 6:
                    scored[i] = fit
        except Exception as e:
            print(f"  [WARN] triage batch failed: {e}")
            if "budget" in str(e).lower():
                break
    best = sorted(scored, key=lambda i: -scored[i])[:keep]
    print(f"  Triage: {len(candidates)} leads → {len(scored)} plausible → evaluating the top {len(best)}")
    return [candidates[i] for i in best]
