"""
Podcast Intelligence source.
Scans VC and startup podcast feeds for founder appearances —
one of the strongest "about to raise" signals in venture.

When Harry Stebbings interviews a founder on 20VC, money follows
within weeks. When a founder appears on Riding Unicorns, they're
positioning for European growth-stage capital. These are high-signal,
low-noise sources that no automated sourcing tool captures.

All podcasts have RSS feeds. Episode titles and descriptions
contain company names, funding context, and vertical keywords.

No API key required. No rate limits. Just RSS parsing.
"""

import json
import urllib.request
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta
from shared.models import RawCandidate


# VC and startup podcasts ranked by signal strength
# These are the shows where founders appear when raising or just after closing
PODCAST_FEEDS = [
    {
        "name": "20VC (The Twenty Minute VC)",
        "url": "https://feeds.megaphone.fm/twentyminutevc",
        "signal_strength": "very_high",
        "description": "Harry Stebbings. The highest-signal VC podcast globally. A founder appearing here is almost always raising or just raised.",
    },
    {
        "name": "Riding Unicorns",
        "url": "https://feeds.acast.com/public/shows/riding-unicorns",
        "signal_strength": "high",
        "description": "James Pringle. European early-stage focus. Strong signal for UK and European startups pre-Series A/B.",
    },
    {
        "name": "The Generalist Podcast",
        "url": "https://feeds.simplecast.com/l2i9YnTd",
        "signal_strength": "high",
        "description": "Mario Gabriele. Deep-dive company analyses and founder interviews.",
    },
    {
        "name": "This Week in Startups",
        "url": "https://feeds.megaphone.fm/thisweekinstartups",
        "signal_strength": "medium",
        "description": "Jason Calacanis. Broad startup coverage, frequent founder pitches.",
    },
    {
        "name": "Lenny's Podcast",
        "url": "https://feeds.simplecast.com/lAHUbQkP",
        "signal_strength": "medium",
        "description": "Lenny Rachitsky. Product and growth focus. Strong for consumer/marketplace companies.",
    },
    {
        "name": "How I Built This",
        "url": "https://feeds.simplecast.com/dHoohVNH",
        "signal_strength": "medium",
        "description": "Guy Raz / NPR. Founder stories, typically later-stage but strong brand signal.",
    },
    {
        "name": "Invest Like the Best",
        "url": "https://feeds.megaphone.fm/investlikethebest",
        "signal_strength": "medium",
        "description": "Patrick O'Shaughnessy. Investor and founder conversations. Strong for fintech and deep tech.",
    },
]

# Keywords that suggest a thesis-relevant episode
THESIS_KEYWORDS = [
    "ai", "artificial intelligence", "healthcare", "health tech",
    "legal tech", "dental", "veterinary", "insurance", "fintech",
    "compliance", "automation", "practice management", "vertical",
    "regulated", "consumer", "digital health", "mental health",
    "saas", "marketplace", "platform", "series a", "series b",
    "seed", "raised", "funding", "million",
]


def fetch_podcast_feed(url: str, timeout: int = 15) -> str | None:
    """Fetch podcast RSS feed."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "thesis-agent/1.0",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] Podcast feed fetch failed: {e}")
        return None


def parse_podcast_episodes(xml_content: str, max_episodes: int = 20) -> list[dict]:
    """Parse episodes from a podcast RSS feed."""
    episodes = []
    try:
        root = ET.fromstring(xml_content)

        # iTunes namespace for podcast-specific fields
        itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"

        for item in root.findall(".//item")[:max_episodes]:
            title = item.findtext("title", "").strip()
            description = item.findtext("description", "").strip()
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "").strip()

            # Try iTunes-specific fields
            itunes_summary = item.findtext(f"{{{itunes_ns}}}summary", "").strip()
            itunes_subtitle = item.findtext(f"{{{itunes_ns}}}subtitle", "").strip()

            # Use best available description
            desc = itunes_summary or itunes_subtitle or description
            # Strip HTML
            if "<" in desc:
                desc = re.sub(r"<[^>]+>", "", desc)

            episodes.append({
                "title": title,
                "description": desc[:500],
                "link": link,
                "pub_date": pub_date,
            })

    except ET.ParseError as e:
        print(f"  [WARN] Podcast XML parse error: {e}")

    return episodes


def extract_guest_and_company(title: str, description: str) -> tuple[str, str]:
    """
    Extract guest name and company from podcast episode title.

    Common patterns:
    - "John Smith, CEO of CompanyX: How They Built..."
    - "CompanyX Founder on Raising $20M"
    - "How CompanyX is Disrupting Healthcare with John Smith"
    - "#456: John Smith — Building CompanyX"
    """
    # Remove episode numbers
    clean = re.sub(r"^[#\d]+[\s:.\-—]+", "", title).strip()

    # Try pattern: "Name, Role at/of Company"
    match = re.search(r"(.+?),\s+(?:CEO|CTO|founder|co-founder|cofounder)\s+(?:of|at)\s+(.+?)(?:\s*[:\-—|]|$)", clean, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # Try pattern: "Name — Company" or "Name - Company"
    match = re.search(r"(.+?)\s*[—\-]\s*(.+?)(?:\s*[:\-—|]|$)", clean)
    if match:
        guest = match.group(1).strip()
        company = match.group(2).strip()
        if len(guest) < 40 and len(company) < 40:
            return guest, company

    # Fallback: use the full title as context
    return "", clean


def scan_podcasts(
    feeds: list[dict] = None,
    max_episodes_per_feed: int = 15,
    days_back: int = 30,
) -> list[RawCandidate]:
    """
    Scan VC podcast feeds for thesis-relevant founder appearances.

    A founder appearing on 20VC or Riding Unicorns is a high-confidence
    signal that the company is raising or has recently raised.
    """
    if feeds is None:
        feeds = PODCAST_FEEDS

    candidates = []
    seen_titles = set()

    for feed_config in feeds:
        name = feed_config["name"]
        url = feed_config["url"]
        signal_strength = feed_config.get("signal_strength", "medium")

        print(f"  Podcast [{name}]: fetching...")
        xml = fetch_podcast_feed(url)
        if not xml:
            continue

        episodes = parse_podcast_episodes(xml, max_episodes=max_episodes_per_feed)
        relevant = 0

        for ep in episodes:
            title = ep["title"]
            if title in seen_titles:
                continue
            seen_titles.add(title)

            description = ep["description"]
            combined = f"{title} {description}".lower()

            # Check thesis relevance
            matching_keywords = [kw for kw in THESIS_KEYWORDS if kw in combined]
            if len(matching_keywords) < 1:
                continue

            relevant += 1
            guest, company = extract_guest_and_company(title, description)

            # Use company name if extracted, otherwise use episode context
            candidate_name = company if company and len(company) < 50 else f"[Podcast] {title[:60]}"

            candidates.append(
                RawCandidate(
                    name=candidate_name,
                    url=ep["link"] or None,
                    description=(
                        f"Podcast appearance on {name}: {title}. "
                        f"Signal strength: {signal_strength}. "
                        f"Keywords: {', '.join(matching_keywords[:3])}."
                    ),
                    source=f"podcast_{name.lower().replace(' ', '_')[:20]}",
                    source_url=ep["link"],
                    raw_context=(
                        f"Podcast: {name}. Episode: {title}. "
                        f"Guest: {guest or 'Unknown'}. "
                        f"Signal strength: {signal_strength}. "
                        f"{description[:300]}"
                    ),
                )
            )

        print(f"  Podcast [{name}]: {len(episodes)} episodes, {relevant} thesis-relevant")

    print(f"  Podcasts total: {len(candidates)} signals found")
    return candidates
