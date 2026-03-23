"""
Product Hunt source.
Catches companies on launch day — before they have press coverage,
funding announcements, or significant web presence.

Product Hunt is where founders ship. A product launching in healthcare,
legal, dental, or fintech with 100+ upvotes on day one is a signal
worth evaluating.

API: GraphQL via https://api.producthunt.com/v2/api/graphql
Auth: OAuth2 — get a developer token at https://www.producthunt.com/v2/oauth/applications
Rate limit: Generous for personal use.
"""

import json
import urllib.request
import os
from datetime import datetime, timedelta
from shared.models import RawCandidate


API_URL = "https://api.producthunt.com/v2/api/graphql"

# Categories and keywords that map to thesis verticals
THESIS_CATEGORIES = [
    "health", "health-fitness", "healthcare",
    "fintech", "finance", "banking",
    "legal", "law",
    "education", "edtech",
    "food-drink", "food",
    "productivity", "saas",
    "developer-tools",
    "artificial-intelligence",
]

THESIS_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning",
    "healthcare", "health", "medical", "clinical", "patient",
    "dental", "veterinary", "vet",
    "legal", "law", "compliance", "regulatory",
    "fintech", "insurance", "accounting", "tax",
    "practice management", "automation", "workflow",
    "consumer", "marketplace", "platform",
]


def _graphql_request(query: str, variables: dict = None) -> dict | None:
    """Make a GraphQL request to Product Hunt API."""
    token = os.environ.get("PRODUCTHUNT_TOKEN", "")

    if not token:
        return None

    payload = json.dumps({
        "query": query,
        "variables": variables or {},
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "thesis-agent/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] Product Hunt API error: {e}")
        return None


def get_recent_posts(
    days_back: int = 7,
    first: int = 50,
) -> list[dict]:
    """Fetch recent Product Hunt posts."""
    query = """
    query($first: Int, $postedAfter: DateTime) {
      posts(first: $first, postedAfter: $postedAfter, order: VOTES) {
        edges {
          node {
            id
            name
            tagline
            description
            url
            votesCount
            website
            createdAt
            topics {
              edges {
                node {
                  name
                  slug
                }
              }
            }
            makers {
              name
              headline
            }
          }
        }
      }
    }
    """

    posted_after = (datetime.utcnow() - timedelta(days=days_back)).isoformat() + "Z"

    data = _graphql_request(query, {
        "first": first,
        "postedAfter": posted_after,
    })

    if not data or "data" not in data:
        return []

    posts = []
    for edge in data.get("data", {}).get("posts", {}).get("edges", []):
        node = edge.get("node", {})
        if node:
            # Extract topics
            topics = [
                t["node"]["slug"]
                for t in node.get("topics", {}).get("edges", [])
                if t.get("node")
            ]
            node["topic_slugs"] = topics

            # Extract maker info
            makers = node.get("makers", [])
            node["maker_names"] = [m.get("name", "") for m in makers]
            node["maker_headlines"] = [m.get("headline", "") for m in makers]

            posts.append(node)

    return posts


def scan_product_hunt(
    days_back: int = 7,
    min_votes: int = 50,
) -> list[RawCandidate]:
    """
    Scan Product Hunt for thesis-relevant launches.

    Filters by:
    1. Recency (last N days)
    2. Traction (minimum upvotes)
    3. Topic/keyword relevance to thesis
    """
    # Check for API token
    if not os.environ.get("PRODUCTHUNT_TOKEN"):
        print("  Product Hunt: skipped (no API token — get one at producthunt.com/v2/oauth/applications)")
        return []

    print(f"  Product Hunt: fetching posts from last {days_back} days...")
    posts = get_recent_posts(days_back=days_back, first=50)

    if not posts:
        print("  Product Hunt: no posts returned")
        return []

    candidates = []

    for post in posts:
        votes = post.get("votesCount", 0)
        if votes < min_votes:
            continue

        name = post.get("name", "").strip()
        tagline = post.get("tagline", "")
        description = post.get("description", "")
        website = post.get("website", "")
        topics = post.get("topic_slugs", [])
        makers = post.get("maker_names", [])
        maker_headlines = post.get("maker_headlines", [])

        # Check thesis relevance
        combined = f"{name} {tagline} {description} {' '.join(topics)}".lower()
        is_relevant = any(kw in combined for kw in THESIS_KEYWORDS)

        # Also check topic slugs directly
        topic_match = any(t in THESIS_CATEGORIES for t in topics)

        if not is_relevant and not topic_match:
            continue

        # Build context
        context_parts = [
            f"Votes: {votes}",
            f"Topics: {', '.join(topics[:5])}" if topics else "",
            f"Makers: {', '.join(makers[:3])}" if makers else "",
        ]
        if maker_headlines:
            context_parts.append(f"Maker backgrounds: {'; '.join(h for h in maker_headlines[:2] if h)}")

        candidates.append(
            RawCandidate(
                name=name,
                url=website or post.get("url", ""),
                description=f"{tagline}. Launched on Product Hunt with {votes} upvotes.",
                source="product_hunt",
                source_url=post.get("url", ""),
                raw_context=". ".join(p for p in context_parts if p),
            )
        )

    print(f"  Product Hunt: {len(posts)} posts checked, {len(candidates)} thesis-relevant")
    return candidates
