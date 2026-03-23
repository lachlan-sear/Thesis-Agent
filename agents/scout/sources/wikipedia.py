"""
Wikipedia Pageviews source.
Tracks mindshare and public awareness signals for companies and
industry terms. More reliable than Google Trends (no rate limiting,
no session-based blocking).

When a company's Wikipedia page starts getting significantly more
traffic, it signals growing public awareness — often preceding
press coverage and funding announcements.

API: https://wikimedia.org/api/rest_v1/
Completely free. No auth required. No rate limit concerns.
Daily pageview data available since July 2015.
"""

import json
import urllib.request
from datetime import datetime, timedelta


WIKIMEDIA_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"


def get_pageviews(
    article_title: str,
    project: str = "en.wikipedia",
    days_back: int = 90,
    granularity: str = "daily",
) -> list[dict]:
    """
    Get daily pageview data for a Wikipedia article.

    Returns list of {"date": "YYYY-MM-DD", "views": int}
    """
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)

    # Wikipedia API date format: YYYYMMDD
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    # Article titles use underscores in the API
    safe_title = article_title.replace(" ", "_")

    url = (
        f"{WIKIMEDIA_API}/{project}/all-access/all-agents/"
        f"{safe_title}/{granularity}/{start_str}/{end_str}"
    )

    req = urllib.request.Request(url, headers={
        "User-Agent": "thesis-agent/1.0 (deal sourcing research tool; contact: github.com/thesis-agent)",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("items", [])
            return [
                {
                    "date": item.get("timestamp", "")[:8],
                    "views": item.get("views", 0),
                }
                for item in items
            ]
    except Exception as e:
        return []


def compute_trend(pageviews: list[dict], recent_days: int = 14) -> dict:
    """
    Compute trend metrics from pageview data.

    Returns:
    - avg_daily: average daily views over full period
    - avg_recent: average daily views over last N days
    - trend_ratio: recent / historical (>1.5 = growing, <0.5 = declining)
    - total_views: total over period
    - peak_day: highest single day
    """
    if not pageviews:
        return {
            "avg_daily": 0,
            "avg_recent": 0,
            "trend_ratio": 0,
            "total_views": 0,
            "peak_day": 0,
        }

    views = [pv["views"] for pv in pageviews]
    total = sum(views)
    avg = total / len(views) if views else 0

    recent = views[-recent_days:] if len(views) >= recent_days else views
    avg_recent = sum(recent) / len(recent) if recent else 0

    older = views[:-recent_days] if len(views) > recent_days else views
    avg_older = sum(older) / len(older) if older else 1

    return {
        "avg_daily": round(avg, 1),
        "avg_recent": round(avg_recent, 1),
        "trend_ratio": round(avg_recent / avg_older, 2) if avg_older > 0 else 0,
        "total_views": total,
        "peak_day": max(views) if views else 0,
    }


def check_company_mindshare(
    company_name: str,
    wikipedia_title: str = None,
    days_back: int = 90,
) -> dict:
    """
    Check a company's Wikipedia mindshare signal.
    Used by the Radar agent for tracked company monitoring.

    If the company has a Wikipedia article, this returns trend data.
    A trend_ratio > 1.5 means growing awareness (positive signal).
    A trend_ratio < 0.5 means declining awareness (potential stale signal).

    Returns: {"has_article": bool, "trend": dict, "signal": str}
    """
    title = wikipedia_title or company_name

    pageviews = get_pageviews(title, days_back=days_back)

    if not pageviews or all(pv["views"] == 0 for pv in pageviews):
        # Try with common suffixes
        for suffix in ["_(company)", "_(software)", "_(startup)"]:
            pageviews = get_pageviews(title + suffix, days_back=days_back)
            if pageviews and any(pv["views"] > 0 for pv in pageviews):
                break

    if not pageviews or all(pv["views"] == 0 for pv in pageviews):
        return {
            "has_article": False,
            "trend": {},
            "signal": "no_article",
        }

    trend = compute_trend(pageviews)

    if trend["trend_ratio"] >= 2.0:
        signal = "surging"
    elif trend["trend_ratio"] >= 1.5:
        signal = "growing"
    elif trend["trend_ratio"] >= 0.8:
        signal = "stable"
    elif trend["trend_ratio"] >= 0.5:
        signal = "declining"
    else:
        signal = "fading"

    return {
        "has_article": True,
        "trend": trend,
        "signal": signal,
    }


def scan_vertical_mindshare(
    terms: list[str] = None,
    days_back: int = 90,
) -> list[dict]:
    """
    Track mindshare trends for thesis-relevant industry terms.
    Used by the Radar agent for market trend monitoring.

    Returns trends for each term, useful for spotting which
    verticals are gaining or losing attention.
    """
    if terms is None:
        terms = [
            "Veterinary_informatics",
            "Health_information_technology",
            "Legal_technology",
            "Dental_informatics",
            "Insurance_technology",
            "Artificial_intelligence_in_healthcare",
            "Practice_management_software",
            "Regulatory_technology",
        ]

    results = []
    for term in terms:
        print(f"  Wikipedia: checking '{term}'...")
        pageviews = get_pageviews(term, days_back=days_back)
        if pageviews:
            trend = compute_trend(pageviews)
            results.append({
                "term": term.replace("_", " "),
                "trend": trend,
            })

    return results
