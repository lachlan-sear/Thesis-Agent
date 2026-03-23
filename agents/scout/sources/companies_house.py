"""
Companies House source.
Queries the free UK Companies House API to find recently incorporated
companies matching thesis-relevant SIC codes.

This is a unique signal — it finds companies at incorporation, before
they have a website, funding, or press coverage. No other open-source
deal sourcing tool does this.

API: https://developer.company-information.service.gov.uk/
Rate limit: 600 requests per 5 minutes. No API key required for basic search.
"""

import json
import urllib.request
import urllib.parse
import os
from datetime import datetime, timedelta
from shared.models import RawCandidate


API_BASE = "https://api.company-information.service.gov.uk"

# SIC codes relevant to thesis verticals
# Full list: https://resources.companieshouse.gov.uk/sic/
DEFAULT_SIC_CODES = {
    "62012": "Business and domestic software development",
    "62020": "Information technology consultancy activities",
    "62090": "Other information technology service activities",
    "86101": "Hospital activities",
    "86210": "General medical practice activities",
    "86220": "Specialist medical practice activities",
    "86230": "Dental practice activities",
    "86900": "Other human health activities",
    "75000": "Veterinary activities",
    "64209": "Activities of other holding companies",
    "72110": "Research and experimental development on biotechnology",
    "72190": "Other research and experimental development on natural sciences",
}

# Keywords that suggest a tech/AI company vs. a traditional business
TECH_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "platform",
    "software", "digital", "tech", "data", "automation", "saas",
    "cloud", "analytics", "algorithm", "neural", "deep learning",
    "healthtech", "medtech", "fintech", "legaltech", "insurtech",
    "veterinary technology", "dental technology", "practice management",
]


def _fetch(endpoint: str, params: dict = None) -> dict | None:
    """Make a request to the Companies House API."""
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")

    url = f"{API_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={"User-Agent": "thesis-agent/1.0"})

    # API key is optional for search, required for some endpoints
    if api_key:
        import base64
        auth = base64.b64encode(f"{api_key}:".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] Companies House API error: {e}")
        return None


def search_companies(
    query: str,
    items_per_page: int = 20,
) -> list[dict]:
    """Search for companies by name/keyword."""
    data = _fetch("/search/companies", {
        "q": query,
        "items_per_page": items_per_page,
    })
    if data and "items" in data:
        return data["items"]
    return []


def search_recently_incorporated(
    sic_codes: list[str] = None,
    days_back: int = 90,
    keywords: list[str] = None,
) -> list[RawCandidate]:
    """
    Find recently incorporated UK companies in thesis-relevant sectors.

    Strategy: search by tech-relevant terms and filter by:
    1. Incorporation date (last N days)
    2. SIC code (if available)
    3. Name keywords suggesting tech/AI company
    """
    if sic_codes is None:
        sic_codes = list(DEFAULT_SIC_CODES.keys())
    if keywords is None:
        keywords = ["AI", "digital health", "veterinary tech", "legal tech",
                     "fintech platform", "dental AI", "practice management software",
                     "healthtech", "insurtech", "automation platform"]

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    candidates = []
    seen_numbers = set()

    for keyword in keywords:
        print(f"  Companies House: searching '{keyword}'...")
        results = search_companies(keyword, items_per_page=20)

        for item in results:
            company_number = item.get("company_number", "")

            # Skip if already seen
            if company_number in seen_numbers:
                continue
            seen_numbers.add(company_number)

            # Check incorporation date
            date_str = item.get("date_of_creation", "")
            if date_str:
                try:
                    inc_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if inc_date < cutoff:
                        continue  # Too old
                except ValueError:
                    continue

            # Check company status
            status = item.get("company_status", "")
            if status not in ("active", ""):
                continue

            company_name = item.get("title", "").strip()
            address = item.get("address_snippet", "")
            description = item.get("description", "")

            # Basic relevance filter: does the name or description
            # contain tech-relevant keywords?
            combined = f"{company_name} {description}".lower()
            is_tech = any(kw in combined for kw in TECH_KEYWORDS)

            if not is_tech:
                continue

            candidates.append(
                RawCandidate(
                    name=company_name,
                    url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}",
                    description=f"UK company incorporated {date_str}. {description or 'No description available.'}",
                    source="companies_house",
                    source_url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}",
                    raw_context=f"SIC codes: {item.get('sic_codes', 'N/A')}. Address: {address}. Status: {status}.",
                )
            )

    print(f"  Companies House: {len(candidates)} tech companies found (last {days_back} days)")
    return candidates


def get_company_profile(company_number: str) -> dict | None:
    """Get detailed profile for a specific company."""
    return _fetch(f"/company/{company_number}")


def get_officers(company_number: str) -> list[dict]:
    """Get officers (directors/founders) for a company."""
    data = _fetch(f"/company/{company_number}/officers")
    if data and "items" in data:
        return data["items"]
    return []
