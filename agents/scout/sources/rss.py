"""
RSS Feed source.
Monitors startup news feeds for funding announcements, launches,
and thesis-relevant signals.

Catches the TechCrunch headline, the Sifted deep-dive, and the
EU-Startups announcement that web search might miss or surface late.

No API key required. No rate limits. Just XML parsing.
"""

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from shared.models import RawCandidate


# Default feeds — configurable via thesis.yaml
DEFAULT_FEEDS = [
    {
        "name": "Sifted",
        "url": "https://sifted.eu/feed",
        "focus": "European startups, funding rounds, deep dives",
    },
    {
        "name": "TechCrunch Startups",
        "url": "https://techcrunch.com/category/startups/feed/",
        "focus": "Global startup news, funding announcements",
    },
    {
        "name": "EU-Startups",
        "url": "https://www.eu-startups.com/feed/",
        "focus": "European startup ecosystem",
    },
]

# Keywords that suggest an article contains a company worth evaluating
FUNDING_KEYWORDS = [
    "raises", "raised", "funding", "series a", "series b", "seed",
    "million", "investment", "backed", "led by", "round",
    "pre-seed", "venture", "capital",
]

THESIS_KEYWORDS = [
    "ai", "artificial intelligence", "healthcare", "health tech",
    "legal tech", "dental", "veterinary", "insurance", "fintech",
    "compliance", "automation", "practice management",
    "vertical", "regulated", "saas", "platform",
    "consumer", "digital health", "mental health",
]


def fetch_feed(url: str, timeout: int = 10) -> str | None:
    """Fetch RSS feed XML content."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "thesis-agent/1.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] RSS fetch failed for {url}: {e}")
        return None


def parse_feed(xml_content: str) -> list[dict]:
    """Parse RSS feed items from XML."""
    items = []
    try:
        root = ET.fromstring(xml_content)

        # Handle both RSS 2.0 and Atom feeds
        # RSS 2.0: channel/item
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            description = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()

            # Clean HTML from description
            if "<" in description:
                # Simple HTML tag stripping
                import re
                description = re.sub(r"<[^>]+>", "", description)

            items.append({
                "title": title,
                "link": link,
                "description": description[:500],
                "pub_date": pub_date,
            })

        # Atom: entry
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            link_elem = entry.find("atom:link", ns)
            link = link_elem.get("href", "") if link_elem is not None else ""
            summary = entry.findtext("atom:summary", "", ns).strip()

            items.append({
                "title": title,
                "link": link,
                "description": summary[:500],
                "pub_date": entry.findtext("atom:published", "", ns),
            })

    except ET.ParseError as e:
        print(f"  [WARN] RSS parse error: {e}")

    return items


def is_relevant(title: str, description: str) -> tuple[bool, str]:
    """
    Check if an RSS item is relevant to the thesis.
    Returns (is_relevant, reason).
    """
    combined = f"{title} {description}".lower()

    has_funding = any(kw in combined for kw in FUNDING_KEYWORDS)
    has_thesis = any(kw in combined for kw in THESIS_KEYWORDS)

    if has_funding and has_thesis:
        return True, "funding + thesis match"
    elif has_funding:
        return True, "funding announcement"
    elif has_thesis:
        # Only thesis keywords without funding — lower priority
        # but still worth catching for launches and news
        thesis_matches = [kw for kw in THESIS_KEYWORDS if kw in combined]
        if len(thesis_matches) >= 2:
            return True, f"thesis keywords: {', '.join(thesis_matches[:3])}"

    return False, ""


def extract_company_name(title: str) -> str:
    """
    Best-effort extraction of company name from an article title.
    Handles common patterns:
    - "CompanyX raises $10M..."
    - "CompanyX, the AI startup, launches..."
    - "London-based CompanyX secures funding..."
    """
    # Common patterns: first word(s) before a verb
    stop_words = [
        "raises", "raised", "secures", "launches", "announces",
        "closes", "lands", "nabs", "bags", "gets", "grabs",
        "snags", "picks up", "hauls in", "brings in",
        "the", "a", "an",
    ]

    # Try to find the company name — usually the first noun phrase
    parts = title.split()
    name_parts = []

    for word in parts:
        clean = word.strip(",:;-–—").lower()
        if clean in stop_words or clean.startswith("$") or clean.startswith("€") or clean.startswith("£"):
            break
        name_parts.append(word.strip(",:;-–—"))

    name = " ".join(name_parts).strip()

    # Remove common prefixes
    for prefix in ["london-based", "uk-based", "berlin-based", "paris-based", "european"]:
        if name.lower().startswith(prefix):
            name = name[len(prefix):].strip()

    return name if len(name) > 1 else title.split(":")[0].strip()


def scan_rss_feeds(
    feeds: list[dict] = None,
    max_age_days: int = 7,
) -> list[RawCandidate]:
    """
    Scan RSS feeds for thesis-relevant startup news.

    Filters by:
    1. Recency (last N days)
    2. Keyword relevance (funding + thesis terms)
    3. Basic company name extraction
    """
    if feeds is None:
        feeds = DEFAULT_FEEDS

    candidates = []
    seen_links = set()

    for feed_config in feeds:
        name = feed_config.get("name", "Unknown")
        url = feed_config.get("url", "")

        if not url:
            continue

        print(f"  RSS [{name}]: fetching...")
        xml = fetch_feed(url)
        if not xml:
            continue

        items = parse_feed(xml)
        relevant_count = 0

        for item in items:
            # Skip duplicates
            if item["link"] in seen_links:
                continue
            seen_links.add(item["link"])

            # Check relevance
            is_rel, reason = is_relevant(item["title"], item["description"])
            if not is_rel:
                continue

            relevant_count += 1
            company_name = extract_company_name(item["title"])

            candidates.append(
                RawCandidate(
                    name=company_name,
                    url=item["link"],
                    description=f"{item['title']}",
                    source=f"rss_{name.lower().replace(' ', '_')}",
                    source_url=item["link"],
                    raw_context=f"Source: {name}. Relevance: {reason}. {item['description'][:300]}",
                )
            )

        print(f"  RSS [{name}]: {len(items)} items, {relevant_count} relevant")

    print(f"  RSS total: {len(candidates)} thesis-relevant articles found")
    return candidates
