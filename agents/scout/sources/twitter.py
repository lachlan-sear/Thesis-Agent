"""
Twitter/X signal source.
Monitors startup and VC Twitter for funding announcements,
founder signals, and investor activity.

The Twitter API is effectively dead for free use ($42K/year for
full access). This source uses Claude web search to query
site:twitter.com and site:x.com for specific signal patterns.

Not real-time monitoring, but catches signals within 24-48 hours —
fast enough for deal sourcing where the goal is to be early,
not to be first.
"""

from shared.claude_client import get_client
from shared.models import RawCandidate
import json


# Signal-specific search patterns
# These target the actual tweets VCs and founders post when deals happen
TWITTER_QUERIES = [
    # Funding announcements (founders and VCs tweet these)
    'site:x.com "excited to announce" "raised" startup 2026',
    'site:x.com "thrilled to share" "series" funding 2026',
    'site:x.com "just closed" "round" startup 2026',

    # Investor activity signals
    'site:x.com "excited to lead" "seed" OR "series a" 2026',
    'site:x.com "proud to back" startup founder 2026',
    'site:x.com "newest investment" portfolio startup 2026',

    # Thesis-vertical specific
    'site:x.com healthcare AI startup funding 2026',
    'site:x.com legal tech startup raised 2026',
    'site:x.com fintech startup seed Europe UK 2026',
    'site:x.com veterinary dental AI startup 2026',

    # European ecosystem signals
    'site:x.com European startup series A 2026',
    'site:x.com "London-based" startup raised 2026',
    'site:x.com "Berlin-based" OR "Paris-based" startup funding 2026',
]


PARSER_SYSTEM = """You are a deal sourcing analyst scanning Twitter/X search results
for startup funding signals. Extract any companies mentioned alongside
funding announcements, launches, or investor backing.

Return ONLY a valid JSON array. Each object:
{"name": "company name", "signal": "what happened (1 sentence)", "url": "tweet URL or null"}

If no relevant companies found, return: []
Rules:
- Only include actual startups/companies, not VCs or journalists
- Only include companies where there's a clear signal (funding, launch, backing)
- Do not hallucinate — if unsure, skip it"""


def scan_twitter_signals(
    queries: list[str] = None,
    max_queries: int = 8,
) -> list[RawCandidate]:
    """
    Scan Twitter/X for startup funding and launch signals.

    Uses Claude web search as a proxy for the dead Twitter API.
    Each query targets a specific signal pattern (funding announcement,
    investor backing, thesis-vertical activity).
    """
    if queries is None:
        queries = TWITTER_QUERIES

    client = get_client()
    candidates = []
    seen_names = set()

    for query in queries[:max_queries]:
        print(f"  X/Twitter: searching...")

        try:
            raw = client.search_and_summarise(
                query=query,
                task_type="evaluate",
                system=PARSER_SYSTEM,
            )

            # Try to parse companies from the response
            cleaned = raw.strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1

            if start >= 0 and end > start:
                companies = json.loads(cleaned[start:end])
            else:
                continue

            for c in companies:
                if not isinstance(c, dict) or not c.get("name"):
                    continue

                name = c["name"].strip()
                if name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())

                candidates.append(
                    RawCandidate(
                        name=name,
                        url=c.get("url"),
                        description=f"Twitter signal: {c.get('signal', 'Funding/launch detected')}",
                        source="twitter",
                        source_url=c.get("url"),
                        raw_context=f"Query: {query}. Signal: {c.get('signal', '')}",
                    )
                )

        except Exception as e:
            print(f"  [WARN] Twitter scan failed: {e}")
            continue

    print(f"  X/Twitter: {len(candidates)} signals found")
    return candidates
