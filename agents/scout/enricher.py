"""
Scout Enricher.
For companies scoring 7+, runs a deep research pass using Claude web search.
Returns fully enriched company profiles.

Researches like a top-tier analyst:
- Founder pedigree and domain credibility
- Funding history with investor quality assessment
- Competitive dynamics and positioning
- Regulatory barriers and compliance status
- Product maturity signals (real users vs vaporware)
- Go-to-market and distribution advantages
"""

import json
from shared.claude_client import get_client
from shared.models import Evaluation, EnrichedCompany, Stage


ENRICHER_SYSTEM = """You are a venture capital analyst conducting pre-meeting due diligence.
Your job is to give the partner everything they need to decide whether to take a meeting.

Think like an analyst at Sequoia or Benchmark preparing a company brief:
- Founder backgrounds matter more than product features at this stage.
- Investor quality signals conviction: who led the round, and have they
  returned to follow on?
- Competitive positioning: are they the first mover, the fast follower,
  or entering a crowded space?
- Regulatory context: is regulation a moat (they've cleared a bar others
  haven't) or a risk (they might get blocked)?
- Distribution: how are they acquiring customers — sales, partnerships,
  viral, or paid acquisition?

CRITICAL RULES:
- Only report facts you can verify. NEVER hallucinate investors or funding amounts.
- If information is unavailable, say "Not found" — don't guess.
- Be specific about what you found and what you couldn't find.
- Distinguish between "confirmed" and "unverified" information.
- A partner reading this brief should trust every fact in it.

Return ONLY valid JSON. No markdown fences, no preamble."""


ENRICHER_SCHEMA = """{
  "name": "string",
  "url": "string or null",
  "description": "string — 2-3 sentence description based on research",
  "vertical": "string — primary vertical category",
  "stage": "pre-seed" | "seed" | "series-a" | "series-b" | "series-c" | "growth" | "unknown",
  "geography": "string — HQ location and key markets",
  "founded": "string — year or 'Not found'",
  "funding_total": "string — e.g. '$5M' or 'Not found'",
  "last_round": "string — e.g. 'Seed, $2M, Jan 2026, led by X' or 'Not found'",
  "investors": ["list of known investor names — verified only"],
  "investor_quality_note": "string — are these tier 1 funds? angels? accelerators?",
  "founders": ["list of founder names"],
  "founder_backgrounds": "string — for each founder: prior role, domain relevance, years in industry",
  "founder_market_fit": "string — 1-2 sentences: why these founders for this problem?",
  "competitive_landscape": "string — 3-4 sentences: who else is here, how is this company positioned, what's their edge",
  "regulatory_context": "string — what compliance barriers exist, has the company cleared any, is regulation a moat or risk",
  "product_maturity": "string — live product with paying customers / beta / waitlist / pre-product. Include evidence.",
  "distribution_strategy": "string — how do they acquire customers? partnerships, sales, PLG, marketplace?",
  "key_metrics": "string — any public metrics: revenue, users, growth rate, retention. 'Not found' if unavailable.",
  "red_flags": "string — anything concerning: no product, pivot history, founder departures, lawsuit, etc. 'None found' if clean.",
  "tam_estimate": "string — market size estimate with source",
  "revenue_model": "string — how they make money, pricing details if known",
  "gtm_strategy": "string — customer acquisition strategy and distribution",
  "distribution_advantage": "string — any exclusive partnerships or channels",
  "exit_comparables": "string — potential acquirers, comparable exits, multiples",
  "investor_quality": "string — lead investors, tier, follow-on behaviour"
}"""


def enrich_company(
    name: str,
    url: str | None,
    evaluation: Evaluation,
) -> EnrichedCompany:
    """Run deep research on a high-scoring company."""
    client = get_client()

    prompt = f"""Conduct pre-meeting due diligence on this company:

Name: {name}
URL: {url or 'Unknown'}
Initial Assessment: {evaluation.one_liner}
Composite Score: {evaluation.composite_score}

Research the following — search thoroughly, use multiple queries if needed:

1. FOUNDERS: Who are they? Where did they work before? Do they have credibility
   in this specific domain? How long have they been in the industry?

2. FUNDING: What rounds have they raised? How much? Who led? Did previous
   investors follow on? What's the investor quality signal?

3. COMPETITIVE LANDSCAPE: Who else is building in this space? How is this
   company differentiated? Are they first mover, fast follower, or late entrant?
   Name specific competitors.

4. REGULATORY CONTEXT: What compliance requirements exist in their vertical?
   Have they obtained any certifications, licenses, or regulatory approvals?
   Is regulation protecting them or blocking them?

5. PRODUCT: Is there a live product? Paying customers? Public metrics? Or is
   this still pre-product? Look for evidence — app store listings, customer
   testimonials, press coverage of usage, job postings indicating scale.

6. DISTRIBUTION: How are they going to market? Direct sales, partnerships,
   product-led growth? Any notable distribution advantages?

7. RED FLAGS: Any concerns? Founder departures, pivots, lawsuits, negative
   press, quiet periods suggesting stall?

8. TAM & MARKET SIZE: What is the total addressable market for this company's
   vertical? Find market research estimates. Is this a $500M niche or a $50B+
   opportunity? What is the serviceable obtainable market in year 1-3?

9. REVENUE MODEL: How does this company make money? Subscription per seat?
   Per-clinic SaaS? Usage-based? Transactional? Marketplace take rate?
   Are there multiple revenue streams? What are typical price points?

10. GO-TO-MARKET & DISTRIBUTION: How do they acquire customers? Product-led
    growth? Direct sales team? Channel partnerships? Viral referral?
    What is the typical sales cycle length? What is the CAC relative
    to LTV? Any distribution moats (exclusive partnerships, integrations)?

11. GEOGRAPHIC PRESENCE & SCALABILITY: Where do they operate today?
    What markets are they expanding into? Does regulation help or
    hinder cross-border expansion? Is the product inherently local
    or globally portable?

12. EXIT LANDSCAPE: Who are potential acquirers in this space? Have there
    been comparable exits? At what multiples? Is IPO realistic given
    the TAM? Name specific companies that could acquire this.

13. INVESTOR QUALITY: Who has invested? Are lead investors tier 1?
    Have insiders followed on in subsequent rounds? What does the
    investor's portfolio tell you about their conviction in this space?

Return your findings as JSON matching this schema:
{ENRICHER_SCHEMA}"""

    try:
        # Use web search for enrichment
        raw_research = client.search_and_summarise(
            query=f"{name} startup funding investors revenue customers 2025 2026",
            task_type="enrich",
            system=ENRICHER_SYSTEM,
            prompt_template=prompt,
        )

        # Now parse the research into structured JSON
        parse_prompt = f"""Extract structured data from this research into JSON.
If the research doesn't contain certain fields, use "Not found" or empty lists.
Never invent information that isn't in the research.

Research text:
{raw_research}

Return ONLY valid JSON matching this schema:
{ENRICHER_SCHEMA}"""

        result = client.complete_json(
            task_type="enrich",
            system="Extract structured JSON from the provided research. Return ONLY valid JSON. Never hallucinate facts.",
            prompt=parse_prompt,
        )

        stage_map = {
            "pre-seed": Stage.PRE_SEED,
            "seed": Stage.SEED,
            "series-a": Stage.SERIES_A,
            "series-b": Stage.SERIES_B,
            "series-c": Stage.SERIES_C,
            "growth": Stage.GROWTH,
        }

        return EnrichedCompany(
            name=result.get("name", name),
            url=result.get("url", url),
            description=result.get("description", evaluation.one_liner),
            vertical=result.get("vertical", "Unknown"),
            stage=stage_map.get(result.get("stage", ""), Stage.UNKNOWN),
            geography=result.get("geography"),
            founded=result.get("founded"),
            funding_total=result.get("funding_total"),
            last_round=result.get("last_round"),
            investors=result.get("investors", []),
            founders=result.get("founders", []),
            founder_backgrounds=result.get("founder_backgrounds"),
            competitive_landscape=result.get("competitive_landscape"),
            regulatory_context=result.get("regulatory_context"),
            product_maturity=result.get("product_maturity"),
            tam_estimate=result.get("tam_estimate"),
            revenue_model=result.get("revenue_model"),
            gtm_strategy=result.get("gtm_strategy"),
            distribution_advantage=result.get("distribution_advantage"),
            exit_comparables=result.get("exit_comparables"),
            investor_quality=result.get("investor_quality"),
            evaluation=evaluation,
            source="enriched",
        )

    except Exception as e:
        print(f"  [WARN] Enrichment failed for {name}: {e}")
        return EnrichedCompany(
            name=name,
            url=url,
            description=evaluation.one_liner,
            vertical="Unknown",
            evaluation=evaluation,
            source="enrichment_failed",
        )
