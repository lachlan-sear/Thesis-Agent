"""
Hacker News source.
Scans Show HN posts and top stories for thesis-relevant companies.
Uses the public Firebase API — no auth needed.
"""

import json
import urllib.request
from shared.models import RawCandidate


HN_API = "https://hacker-news.firebaseio.com/v0"
SHOW_HN_URL = f"{HN_API}/showstories.json"
TOP_URL = f"{HN_API}/topstories.json"


def fetch_json(url: str) -> any:
    """Simple URL fetch for HN API."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "thesis-radar/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] HN fetch failed: {e}")
        return None


def get_item(item_id: int) -> dict | None:
    """Fetch a single HN item by ID."""
    data = fetch_json(f"{HN_API}/item/{item_id}.json")
    return data if isinstance(data, dict) else None


def scan_show_hn(
    max_items: int = 30,
    keywords: list[str] | None = None,
) -> list[RawCandidate]:
    """
    Scan recent Show HN posts for thesis-relevant companies.
    Keywords are used for basic filtering before Claude evaluates.
    """
    if keywords is None:
        keywords = [
            "health", "medical", "dental", "vet", "legal", "law",
            "fintech", "finance", "payment", "insurance", "tax",
            "food", "beverage", "edtech", "education", "tutor",
            "AI", "agent", "automat", "consumer", "marketplace",
            "compliance", "regulat", "digital", "platform",
        ]

    story_ids = fetch_json(SHOW_HN_URL)
    if not story_ids:
        return []

    candidates = []
    checked = 0

    for story_id in story_ids[:max_items]:
        item = get_item(story_id)
        if not item:
            continue

        title = item.get("title", "")
        url = item.get("url", "")
        text = item.get("text", "")

        combined = f"{title} {text}".lower()
        checked += 1

        # Basic keyword filter — Claude will do the real evaluation
        if keywords and not any(kw.lower() in combined for kw in keywords):
            continue

        # Clean the title: remove "Show HN: " prefix
        clean_title = title.replace("Show HN: ", "").replace("Show HN:", "").strip()

        candidates.append(
            RawCandidate(
                name=clean_title.split("–")[0].split("-")[0].split(":")[0].strip(),
                url=url or None,
                description=clean_title,
                source="hacker_news",
                source_url=f"https://news.ycombinator.com/item?id={story_id}",
                raw_context=text[:500] if text else None,
            )
        )

    print(f"  HN: checked {checked} Show HN posts, {len(candidates)} passed keyword filter")
    return candidates


def scan_top_stories(
    max_items: int = 30,
    keywords: list[str] | None = None,
) -> list[RawCandidate]:
    """Scan top stories for funding announcements and launches."""
    if keywords is None:
        keywords = ["startup", "launch", "funding", "raises", "series", "seed", "YC"]

    story_ids = fetch_json(TOP_URL)
    if not story_ids:
        return []

    candidates = []

    for story_id in story_ids[:max_items]:
        item = get_item(story_id)
        if not item:
            continue

        title = item.get("title", "")
        url = item.get("url", "")

        combined = title.lower()
        if not any(kw.lower() in combined for kw in keywords):
            continue

        candidates.append(
            RawCandidate(
                name=title.split("–")[0].split(" raises ")[0].split(" launch")[0].strip(),
                url=url or None,
                description=title,
                source="hacker_news_top",
                source_url=f"https://news.ycombinator.com/item?id={story_id}",
            )
        )

    print(f"  HN top: {len(candidates)} funding/launch stories found")
    return candidates
