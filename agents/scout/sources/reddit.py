"""
Reddit source.
Monitors industry subreddits for practitioner signals:
- Frustration with incumbent software (demand signal)
- Adoption of new tools (product-market fit signal)
- Workflow pain points (opportunity signal)

"I switched to [new tool] and it saved me 2 hours a day" — that's a
product-market fit signal no database captures.

API: https://www.reddit.com/dev/api/
Rate limit: 100 requests/minute with OAuth, 10/min without.
Free with a Reddit app registration.
"""

import json
import urllib.request
import os
from datetime import datetime, timedelta
from shared.models import RawCandidate


API_BASE = "https://www.reddit.com"

# Subreddits where practitioners discuss tools and workflows
# These are the demand signal channels for thesis verticals
THESIS_SUBREDDITS = {
    "veterinary": ["veterinary", "VetTech", "veterinaryprofession"],
    "dental": ["dentistry", "DentalProfessionals"],
    "healthcare": ["healthIT", "medicine", "nursing"],
    "legal": ["legaltech", "LawFirm", "lawyers"],
    "fintech": ["fintech", "insurtech"],
    "accounting": ["Accounting", "taxpros"],
    "general_startup": ["startups", "SaaS", "EntrepreneurRideAlong"],
}

# Keywords that signal a company worth evaluating
SIGNAL_KEYWORDS = {
    "adoption": [
        "switched to", "started using", "migrated to", "replaced",
        "moved to", "trying out", "just launched", "new tool",
        "recommend", "game changer", "saved me",
    ],
    "frustration": [
        "frustrated with", "hate", "worst software", "looking for alternative",
        "anyone else having issues", "switching from", "terrible",
        "outdated", "legacy", "broken", "unusable",
    ],
    "discovery": [
        "anyone heard of", "what do you think of", "has anyone tried",
        "new startup", "just discovered", "interesting tool",
        "AI for", "automation for",
    ],
}


def _fetch_reddit(endpoint: str, params: dict = None) -> dict | None:
    """Fetch from Reddit's public JSON API (no auth needed for read)."""
    url = f"{API_BASE}{endpoint}.json"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

    req = urllib.request.Request(url, headers={
        "User-Agent": "thesis-agent/1.0 (deal sourcing research tool)",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] Reddit API error: {e}")
        return None


def search_subreddit(
    subreddit: str,
    query: str,
    sort: str = "new",
    time_filter: str = "month",
    limit: int = 25,
) -> list[dict]:
    """Search within a specific subreddit."""
    data = _fetch_reddit(f"/r/{subreddit}/search", {
        "q": query,
        "sort": sort,
        "t": time_filter,
        "restrict_sr": "on",
        "limit": str(limit),
    })

    if not data or "data" not in data:
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post:
            posts.append({
                "title": post.get("title", ""),
                "selftext": post.get("selftext", "")[:500],
                "url": f"https://reddit.com{post.get('permalink', '')}",
                "score": post.get("score", 0),
                "num_comments": post.get("num_comments", 0),
                "created_utc": post.get("created_utc", 0),
                "subreddit": post.get("subreddit", subreddit),
            })

    return posts


def scan_reddit_signals(
    verticals: list[str] = None,
    search_terms: list[str] = None,
) -> list[RawCandidate]:
    """
    Scan thesis-relevant subreddits for adoption and frustration signals.

    Strategy:
    1. Search industry subreddits for software/tool discussions
    2. Filter by signal keywords (adoption, frustration, discovery)
    3. Extract potential company names from posts
    """
    if verticals is None:
        verticals = ["veterinary", "dental", "healthcare", "legal", "fintech"]
    if search_terms is None:
        search_terms = [
            "software", "AI tool", "new platform", "practice management",
            "automation", "switched to", "alternative to",
        ]

    candidates = []
    seen_posts = set()

    for vertical in verticals:
        subreddits = THESIS_SUBREDDITS.get(vertical, [])

        for subreddit in subreddits[:2]:  # Limit to 2 per vertical for rate limits
            for term in search_terms[:3]:  # Limit queries per subreddit
                print(f"  Reddit [r/{subreddit}]: searching '{term}'...")

                posts = search_subreddit(
                    subreddit=subreddit,
                    query=term,
                    sort="new",
                    time_filter="month",
                    limit=10,
                )

                for post in posts:
                    post_id = post["url"]
                    if post_id in seen_posts:
                        continue
                    seen_posts.add(post_id)

                    title = post["title"]
                    text = post["selftext"]
                    combined = f"{title} {text}".lower()

                    # Classify the signal type
                    signal_type = None
                    for sig_type, keywords in SIGNAL_KEYWORDS.items():
                        if any(kw in combined for kw in keywords):
                            signal_type = sig_type
                            break

                    if not signal_type:
                        continue

                    # Only include posts with some engagement
                    if post["score"] < 3 and post["num_comments"] < 2:
                        continue

                    candidates.append(
                        RawCandidate(
                            name=f"[Reddit Signal] {title[:60]}",
                            url=post["url"],
                            description=(
                                f"Practitioner signal ({signal_type}) in r/{subreddit}: {title}. "
                                f"Score: {post['score']}, Comments: {post['num_comments']}."
                            ),
                            source="reddit",
                            source_url=post["url"],
                            raw_context=(
                                f"Vertical: {vertical}. Signal type: {signal_type}. "
                                f"Subreddit: r/{subreddit}. "
                                f"{text[:300]}"
                            ),
                        )
                    )

    print(f"  Reddit: {len(candidates)} practitioner signals found")
    return candidates
