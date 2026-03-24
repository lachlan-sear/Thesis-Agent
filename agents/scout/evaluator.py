"""
Scout Evaluator.
Takes raw candidates and scores them against the thesis using Claude.
Returns structured evaluations with composite scores and recommendations.

Uses VC-grade evaluation frameworks:
- Sequoia autopilot vs copilot lens
- Moat taxonomy (regulatory, data, workflow, network)
- Founder-market fit assessment
- 10x better or 10x cheaper test
- Outsourcing wedge analysis
"""

import json
from shared.claude_client import get_client
from shared.config_loader import get_thesis_text
from shared.models import RawCandidate, Evaluation, Action


EVALUATOR_SYSTEM = """You are a senior investment analyst at a top-tier venture capital fund.
You evaluate companies with the rigour of Sequoia, Benchmark, and Founders Fund.
Your job: decide whether a company deserves a first meeting with a partner.

THESIS:
{thesis_text}

EVALUATION FRAMEWORK:

1. MOAT TAXONOMY — What kind of defensibility does this company have?
   - Regulatory moat: licensing, certification, compliance barriers competitors must clear
   - Data moat: proprietary dataset that improves with usage, competitors can't replicate
   - Workflow moat: deeply embedded in daily operations, painful to rip out
   - Network moat: value increases with each additional user or node
   - None: thin wrapper, commodity offering, easily replicated

2. AUTOPILOT TEST (Sequoia "Services: The New Software"):
   - Is this company selling the WORK (autopilot) or the TOOL (copilot)?
   - Autopilot = captures labour/service budget. Tool = captures software budget.
   - Autopilots have 6x larger TAM and benefit from model improvements.
   - Score 8+ only if clearly selling outcomes, not features.

3. 10x TEST:
   - Is this 10x better than the status quo? Or 10x cheaper? Or both?
   - Incremental improvement = skip. Step-change = track.

4. FOUNDER-MARKET FIT:
   - Did the founders work in this industry? Do they have domain credibility?
   - Ex-operators in regulated industries >> generic tech founders
   - If founding team info is unavailable, score as null, never guess.

5. OUTSOURCING WEDGE (Sequoia playbook):
   - Is the task already outsourced? (If yes: existing budget, buyer accepts external delivery)
   - Is it intelligence-heavy? (Rule-based, codifiable, verifiable output)
   - Outsourced + intelligence-heavy = ideal entry point for an autopilot.

6. CUSTOMER DURABILITY:
   - Will the customer still be using this in 5-10 years?
   - Regulated workflows create natural lock-in.
   - Monthly consumer apps without switching costs = low durability.

ADDITIONAL DIMENSIONS — score these for every company:

8. FUNDING STAGE & CAP TABLE (funding_stage_score):
   - Who has invested? Are they tier 1 (Sequoia, a16z, Accel, Balderton, Index)?
   - Have insiders followed on? (strongest signal of conviction)
   - Is the cap table clean or cluttered with party rounds?
   - Pre-seed with no investors = null, not 1. Seed with top angels = 6-7. Series A led by tier 1 = 8-9.
   - If no funding information is available, score null.

9. TAM / MARKET SIZE (tam_score):
   - Is this a venture-scale market? $1B+ TAM minimum for a VC-backable company.
   - Consider both current market and expansion potential.
   - Niche vertical in a tiny market = 3-4 even if execution is great.
   - Vertical AI in a $50B+ regulated market = 8-9.
   - Score based on the realistic serviceable obtainable market, not fantasy TAM.

10. REVENUE MODEL (revenue_model_score):
   - Subscription/SaaS with annual contracts = strong (7-8).
   - Usage-based with growing consumption = strong (7-8).
   - Transactional with repeat purchasing = good (6-7).
   - One-time purchases or unclear monetisation = weak (3-4).
   - Revenue model tied to outcomes rather than seats = bonus.

11. GO-TO-MARKET / DISTRIBUTION (gtm_score):
   - Product-led growth with viral mechanics = excellent (8-9).
   - Partnerships providing guaranteed distribution = strong (7-8).
   - Direct sales to SMBs with short cycles = good (6-7).
   - Enterprise sales with 12+ month cycles to early-stage company = risk (4-5).
   - No clear distribution strategy = weak (2-3).

12. GEOGRAPHIC SCALABILITY (geo_scalability):
   - Software with no regulatory barriers to expansion = 8-9.
   - Vertical AI where regulation varies by country but core product transfers = 6-7.
   - Heavily UK-specific with limited portability = 3-4.
   - Consider: does being in a regulated vertical help or hinder cross-border growth?

13. EXIT POTENTIAL (exit_potential):
   - Clear strategic acquirers exist and are active = 8-9 (e.g. IDEXX for vet tech, Epic for health IT).
   - Market has seen comparable exits at strong multiples = 7-8.
   - IPO-scale potential given TAM and growth = 8-9.
   - No obvious acquirers and market too small for IPO = 3-4.
   - If too early to assess, score null.

SCORING CALIBRATION:
- 1-3: Weak. No thesis fit, thin wrapper, or fundamentally flawed.
- 4-5: Interesting space, but execution or positioning concerns. Not worth a meeting yet.
- 6: Decent. Thesis-adjacent. Would track but not prioritise.
- 7: Strong. Would recommend the partner look at this. Clear thesis fit.
- 8-9: Exceptional. Top-decile opportunity. Urgent meeting recommended.
- 10: Generational. Almost never given.

Most companies should score 4-6. Reserve 7+ for genuine thesis fit.
A composite of 7+ means you'd stake your reputation on the partner taking a meeting.

CRITICAL RULES:
- Score only on available information. Insufficient data = null, not a guess.
- NEVER hallucinate investors, funding amounts, or team backgrounds.
- If it smells like a wrapper on ChatGPT/Claude with no domain depth, say so.
- Compare against the best companies in the vertical, not the average.
- Be specific in your reasoning — name the moat type, the wedge, the risk.

Return ONLY valid JSON matching the schema below. No markdown, no preamble."""


EVALUATOR_SCHEMA = """{
  "company_name": "string",
  "customer_durability": int or null,    // 1-10: will this customer relationship last 5-10 years?
  "unit_economics": int or null,         // 1-10: strong or clearly improving unit economics?
  "regulation_moat": int or null,        // 1-10: does regulatory complexity create defensibility?
  "growth_inflection": int or null,      // 1-10: at or approaching breakout growth?
  "founder_quality": int or null,        // 1-10: domain expertise, operator background?
  "thesis_fit": int or null,             // 1-10: overall alignment with investment thesis?
  "autopilot_potential": int or null,    // 1-10: selling the work or the tool?
  "funding_stage_score": int or null,    // 1-10: quality of cap table, investor tier, follow-on signals
  "tam_score": int or null,              // 1-10: total addressable market size — $500M or $50B?
  "revenue_model_score": int or null,    // 1-10: quality and durability of revenue model
  "gtm_score": int or null,              // 1-10: go-to-market efficiency — short sales cycles, low CAC?
  "geo_scalability": int or null,        // 1-10: can this expand beyond home market?
  "exit_potential": int or null,         // 1-10: clear acquirers, IPO path, or comparable exits?
  "funding_detail": "string — known funding rounds, lead investors, follow-on status",
  "revenue_model_type": "subscription" | "transactional" | "marketplace" | "usage-based" | "hybrid" | "unknown",
  "gtm_strategy": "string — PLG, direct sales, partnerships, viral, paid acquisition, or combination",
  "exit_comparables": "string — named acquirers, comparable exits, relevant multiples",
  "moat_type": "regulatory" | "data" | "workflow" | "network" | "none" | "unknown",
  "ten_x_test": "better" | "cheaper" | "both" | "neither" | "unknown",
  "outsourcing_wedge": true | false | null,  // is the task already outsourced?
  "one_liner": "string — what they do and why it matters, one sentence",
  "bull_case": "string — 2 sentences max, be specific about the upside",
  "bear_case": "string — 2 sentences max, name the actual risk",
  "action": "track" | "watch" | "skip",
  "reasoning": "string — 3 sentences: what moat, what wedge, why this action"
}"""


def evaluate_candidate(
    candidate: RawCandidate,
    config: dict,
) -> Evaluation:
    """Evaluate a single candidate against the thesis."""
    client = get_client()
    thesis = config["thesis"]

    system = EVALUATOR_SYSTEM.format(
        thesis_text=get_thesis_text(config),
    )

    prompt = f"""Evaluate this company:

Name: {candidate.name}
URL: {candidate.url or 'N/A'}
Description: {candidate.description}
Source: {candidate.source}
Additional context: {candidate.raw_context or 'None'}

Apply the full evaluation framework: moat taxonomy, autopilot test, 10x test,
founder-market fit, outsourcing wedge, and customer durability.

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
            funding_stage_score=result.get("funding_stage_score"),
            tam_score=result.get("tam_score"),
            revenue_model_score=result.get("revenue_model_score"),
            gtm_score=result.get("gtm_score"),
            geo_scalability=result.get("geo_scalability"),
            exit_potential=result.get("exit_potential"),
            funding_detail=result.get("funding_detail", ""),
            revenue_model_type=result.get("revenue_model_type", ""),
            gtm_strategy=result.get("gtm_strategy", ""),
            exit_comparables=result.get("exit_comparables", ""),
            one_liner=result.get("one_liner", ""),
            bull_case=result.get("bull_case", ""),
            bear_case=result.get("bear_case", ""),
            action=Action(result.get("action", "skip")),
            reasoning=result.get("reasoning", ""),
        )
        # Use thesis-specific weights if available
        thesis_weights = config.get("thesis", {}).get("evaluation_weights", None)
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
        ev = evaluate_candidate(candidate, config)
        evaluations.append(ev)
        print(f"  [{ev.action.value.upper():5s}] {ev.composite_score:4.1f} — {candidate.name}: {ev.one_liner[:80]}")

    evaluations.sort(key=lambda e: e.composite_score, reverse=True)
    return evaluations
