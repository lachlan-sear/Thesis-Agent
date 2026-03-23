"""
Web Search source.
Uses Claude's web search tool to discover companies matching thesis queries.
This is the primary discovery engine for the scout agent.
"""

import json
from shared.claude_client import get_client
from shared.models import RawCandidate


DISCOVERY_SYSTEM = """You are a deal sourcing analyst. Search for startup companies
matching the given query. For each company found, extract:
- Company name
- URL (if available)
- Brief description (1-2 sentences)
- Why it appeared in results (context)

Return ONLY a valid JSON array of objects. No markdown, no preamble.
If no relevant startups found, return an empty array: []

Schema for each object:
{"name": "string", "url": "string or null", "description": "string", "context": "string"}

RULES:
- Only include actual startups/companies, not articles or blog posts
- Only include companies that seem relevant to the search query
- Deduplicate within your results
- Maximum 10 companies per search"""


def search_for_companies(
    query: str,
    max_results: int = 10,
) -> list[RawCandidate]:
    """Search the web for companies matching a thesis query."""
    client = get_client()

    try:
        raw = client.search_and_summarise(
            query=query,
            task_type="evaluate",
            system=DISCOVERY_SYSTEM,
            prompt_template=(
                "Search for: {query}\n\n"
                f"Find up to {max_results} startup companies relevant to this query. "
                "Return a JSON array of company objects."
            ),
        )

        # Try to parse JSON from the response
        # The response may have text mixed with JSON, so find the array
        cleaned = raw.strip()

        # Try direct parse first
        try:
            companies = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to extract JSON array from response
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1
            if start >= 0 and end > start:
                companies = json.loads(cleaned[start:end])
            else:
                return []

        candidates = []
        for c in companies:
            if isinstance(c, dict) and c.get("name"):
                candidates.append(
                    RawCandidate(
                        name=c["name"],
                        url=c.get("url"),
                        description=c.get("description", "No description"),
                        source="web_search",
                        source_url=None,
                        raw_context=c.get("context", query),
                    )
                )

        return candidates[:max_results]

    except Exception as e:
        print(f"  [WARN] Web search failed for '{query}': {e}")
        return []


def run_discovery(queries: list[str], max_per_query: int = 5) -> list[RawCandidate]:
    """Run multiple search queries and aggregate results."""
    all_candidates = []
    seen_names = set()

    for i, query in enumerate(queries):
        print(f"  Searching ({i+1}/{len(queries)}): {query[:60]}...")
        results = search_for_companies(query, max_per_query)

        for candidate in results:
            name_lower = candidate.name.lower().strip()
            if name_lower not in seen_names:
                seen_names.add(name_lower)
                all_candidates.append(candidate)

    return all_candidates
