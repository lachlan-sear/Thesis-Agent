"""
Scout Enricher.
For companies scoring 7+, runs a deep research pass using Claude web search.
Returns fully enriched company profiles.
"""

import json
from shared.claude_client import get_client
from shared.models import Evaluation, EnrichedCompany, Stage


ENRICHER_SYSTEM = """You are a venture capital research analyst conducting due diligence.
Given a company name and initial evaluation, research deeply and return structured findings.

CRITICAL RULES:
- Only report facts you can verify. Never hallucinate investors or funding amounts.
- If information is unavailable, say "Not found" — don't guess.
- Be specific about sources: "according to their website", "per Crunchbase", etc.
- Focus on: founders, funding, competitive landscape, regulatory context, product maturity.

Return ONLY valid JSON. No markdown fences, no preamble."""


ENRICHER_SCHEMA = """{
  "name": "string",
  "url": "string or null",
  "description": "string — 2-3 sentence description based on research",
  "vertical": "string — primary vertical category",
  "stage": "pre-seed" | "seed" | "series-a" | "series-b" | "series-c" | "growth" | "unknown",
  "geography": "string — HQ location",
  "founded": "string — year or 'Not found'",
  "funding_total": "string — e.g. '$5M' or 'Not found'",
  "last_round": "string — e.g. 'Seed, $2M, Jan 2026' or 'Not found'",
  "investors": ["list of known investor names"],
  "founders": ["list of founder names"],
  "founder_backgrounds": "string — brief on each founder's relevant background",
  "competitive_landscape": "string — 2-3 sentences on key competitors",
  "regulatory_context": "string — what regulatory barriers/advantages exist",
  "product_maturity": "string — live product, beta, waitlist, vaporware"
}"""


def enrich_company(
    name: str,
    url: str | None,
    evaluation: Evaluation,
) -> EnrichedCompany:
    """Run deep research on a high-scoring company."""
    client = get_client()

    prompt = f"""Research this company thoroughly:

Name: {name}
URL: {url or 'Unknown'}
Initial Assessment: {evaluation.one_liner}
Composite Score: {evaluation.composite_score}

Search for:
1. Founder backgrounds — who are they, what did they do before?
2. Funding history — rounds, amounts, investors
3. Competitive landscape — who else is in this space?
4. Regulatory context — what compliance barriers exist in their vertical?
5. Product maturity — is there a live product? Customers? Revenue signals?
6. Recent news — any announcements in the last 3 months?

Return your findings as JSON matching this schema:
{ENRICHER_SCHEMA}"""

    try:
        # Use web search for enrichment
        raw_research = client.search_and_summarise(
            query=f"{name} startup company funding founders",
            task_type="enrich",
            system=ENRICHER_SYSTEM,
            prompt_template=prompt,
        )

        # Now parse the research into structured JSON
        parse_prompt = f"""Extract structured data from this research into JSON.
If the research doesn't contain certain fields, use "Not found" or empty lists.

Research text:
{raw_research}

Return ONLY valid JSON matching this schema:
{ENRICHER_SCHEMA}"""

        result = client.complete_json(
            task_type="enrich",
            system="Extract structured JSON from the provided research. Return ONLY valid JSON.",
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
            evaluation=evaluation,
            source="enriched",
        )

    except Exception as e:
        # Return basic enrichment on failure
        return EnrichedCompany(
            name=name,
            url=url,
            description=evaluation.one_liner,
            vertical="Unknown",
            evaluation=evaluation,
            source="enrichment_failed",
        )
