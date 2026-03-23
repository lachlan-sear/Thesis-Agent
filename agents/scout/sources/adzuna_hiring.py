"""
Adzuna Job Postings source.
Tracks hiring velocity — the single strongest leading indicator
that a startup is about to break out.

A company posting 5+ engineering roles after being quiet = just raised.
A company hiring sales + BD alongside engineering = Series A/B prep.
A company posting CFO/legal/finance = IPO or acquisition prep.

Why this matters: hiring velocity has 3-12 month lead time on funding
announcements. This catches companies before the TechCrunch headline.

API: https://developer.adzuna.com/
Rate limit: 250 requests/day on free tier.
Coverage: 16 countries including UK, DE, FR, NL, AU, US.
"""

import json
import urllib.request
import urllib.parse
import os
from datetime import datetime
from shared.models import RawCandidate


API_BASE = "https://api.adzuna.com/v1/api/jobs"

# Adzuna country codes for thesis-relevant markets
COUNTRIES = {
    "gb": "United Kingdom",
    "de": "Germany",
    "fr": "France",
    "nl": "Netherlands",
    "us": "United States",
}

# Job title patterns that signal a company worth tracking
# Engineering surge = building product
# Sales/BD surge = going to market
# Leadership hires = scaling/fundraising
SIGNAL_CATEGORIES = {
    "engineering": [
        "software engineer", "machine learning engineer",
        "backend engineer", "frontend engineer", "full stack",
        "data engineer", "ML engineer", "AI engineer",
        "engineering lead", "CTO", "VP engineering",
    ],
    "sales_gtm": [
        "account executive", "sales development",
        "business development", "partnerships",
        "head of sales", "VP sales", "customer success",
    ],
    "leadership": [
        "chief financial officer", "CFO", "general counsel",
        "head of people", "VP operations", "COO",
    ],
}


def _fetch(country: str, params: dict) -> dict | None:
    """Make a request to the Adzuna API."""
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")

    if not app_id or not app_key:
        return None

    params["app_id"] = app_id
    params["app_key"] = app_key

    url = f"{API_BASE}/{country}/search/1?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "thesis-agent/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] Adzuna API error: {e}")
        return None


def search_jobs(
    company: str,
    country: str = "gb",
    results_per_page: int = 5,
) -> dict | None:
    """Search for job postings by company name."""
    return _fetch(country, {
        "what": company,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    })


def scan_vertical_hiring(
    verticals: list[str] = None,
    countries: list[str] = None,
    min_results: int = 3,
) -> list[RawCandidate]:
    """
    Scan for hiring surges in thesis-relevant verticals.

    Strategy: search for job postings that combine a vertical keyword
    with tech/AI terms. A company posting multiple roles in our
    target verticals is a signal worth evaluating.
    """
    if verticals is None:
        verticals = [
            "veterinary software", "dental AI", "healthcare AI",
            "legal tech", "insurance automation", "compliance AI",
            "practice management", "clinical AI", "medical coding",
        ]
    if countries is None:
        countries = ["gb"]

    # Check if API credentials are configured
    if not os.environ.get("ADZUNA_APP_ID") or not os.environ.get("ADZUNA_APP_KEY"):
        print("  Adzuna: skipped (no API credentials — get free key at developer.adzuna.com)")
        return []

    candidates = []
    seen_companies = set()

    for country in countries:
        for vertical in verticals:
            print(f"  Adzuna [{country.upper()}]: searching '{vertical}'...")

            data = _fetch(country, {
                "what": vertical,
                "results_per_page": 20,
                "content-type": "application/json",
                "sort_by": "date",
            })

            if not data or "results" not in data:
                continue

            # Group results by company
            company_jobs: dict[str, list] = {}
            for job in data["results"]:
                company_name = job.get("company", {}).get("display_name", "").strip()
                if not company_name or company_name.lower() in seen_companies:
                    continue
                if company_name not in company_jobs:
                    company_jobs[company_name] = []
                company_jobs[company_name].append(job)

            # Companies with multiple postings = hiring surge signal
            for company_name, jobs in company_jobs.items():
                if len(jobs) < min_results:
                    continue

                seen_companies.add(company_name.lower())

                # Classify the hiring pattern
                titles = [j.get("title", "").lower() for j in jobs]
                has_engineering = any(
                    any(kw in t for kw in SIGNAL_CATEGORIES["engineering"])
                    for t in titles
                )
                has_sales = any(
                    any(kw in t for kw in SIGNAL_CATEGORIES["sales_gtm"])
                    for t in titles
                )
                has_leadership = any(
                    any(kw in t for kw in SIGNAL_CATEGORIES["leadership"])
                    for t in titles
                )

                # Build the signal description
                signal_parts = []
                if has_engineering:
                    signal_parts.append("engineering")
                if has_sales:
                    signal_parts.append("sales/GTM")
                if has_leadership:
                    signal_parts.append("leadership")
                signal = " + ".join(signal_parts) if signal_parts else "general"

                location = jobs[0].get("location", {}).get("display_name", COUNTRIES.get(country, country))
                sample_titles = ", ".join(set(j.get("title", "")[:50] for j in jobs[:3]))

                candidates.append(
                    RawCandidate(
                        name=company_name,
                        url=None,
                        description=(
                            f"Hiring surge detected: {len(jobs)} open roles in {vertical}. "
                            f"Signal: {signal} hiring. Location: {location}."
                        ),
                        source="adzuna_hiring",
                        source_url=jobs[0].get("redirect_url"),
                        raw_context=(
                            f"Roles: {sample_titles}. "
                            f"Country: {country.upper()}. "
                            f"Hiring pattern: {signal}. "
                            f"Open positions: {len(jobs)}."
                        ),
                    )
                )

    print(f"  Adzuna: {len(candidates)} companies with hiring surges found")
    return candidates


def check_company_hiring(
    company_name: str,
    countries: list[str] = None,
) -> dict:
    """
    Check a specific company's hiring activity.
    Used by the Ops agent to detect post-funding hiring surges.

    Returns: {"total_jobs": int, "by_category": dict, "signal": str}
    """
    if countries is None:
        countries = ["gb", "us"]

    if not os.environ.get("ADZUNA_APP_ID") or not os.environ.get("ADZUNA_APP_KEY"):
        return {"total_jobs": 0, "by_category": {}, "signal": "no_api_key"}

    total_jobs = 0
    all_titles = []

    for country in countries:
        data = search_jobs(company_name, country, results_per_page=50)
        if data and "results" in data:
            for job in data["results"]:
                # Verify the company name matches (Adzuna search is fuzzy)
                job_company = job.get("company", {}).get("display_name", "").lower()
                if company_name.lower() in job_company or job_company in company_name.lower():
                    total_jobs += 1
                    all_titles.append(job.get("title", "").lower())

    # Classify
    by_category = {}
    for cat, keywords in SIGNAL_CATEGORIES.items():
        count = sum(1 for t in all_titles if any(kw in t for kw in keywords))
        if count > 0:
            by_category[cat] = count

    # Determine signal
    if total_jobs == 0:
        signal = "no_hiring"
    elif total_jobs >= 10:
        signal = "major_surge"
    elif total_jobs >= 5:
        signal = "active_hiring"
    elif "leadership" in by_category:
        signal = "leadership_hire"
    else:
        signal = "moderate"

    return {
        "total_jobs": total_jobs,
        "by_category": by_category,
        "signal": signal,
    }
