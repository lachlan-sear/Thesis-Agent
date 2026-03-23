"""
Patent Intelligence source.
Tracks patent filings as a defensibility signal for regulated verticals.

A dental AI company filing patents on diagnostic workflows has a
fundamentally different moat profile than one that doesn't. Patent
activity in thesis-relevant domains signals both innovation and
intent to build defensible IP.

APIs:
  - USPTO PatentsView: https://patentsview.org/apis (free, no auth)
  - EPO Open Patent Services: https://www.epo.org/en/searching-for-patents/data/web-services (free tier)

Rate limits: USPTO is generous. EPO allows up to 4GB/month free.
"""

import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from shared.models import RawCandidate


USPTO_API = "https://api.patentsview.org/patents/query"

# CPC classification codes relevant to thesis verticals
# These are the patent categories where thesis-relevant innovation happens
THESIS_CPC_CODES = {
    "G16H": "Healthcare informatics (EHR, clinical decision support, telemedicine)",
    "A61B": "Medical diagnostics, surgery, identification",
    "G06N": "Machine learning, neural networks, AI systems",
    "G06Q": "Business methods, fintech, insurance",
    "G06F40": "Natural language processing (legal, medical text)",
    "A61C": "Dentistry (dental diagnostics, treatment planning)",
    "A01K": "Animal husbandry, veterinary instruments",
}

# Search terms for patent queries
THESIS_PATENT_QUERIES = [
    "veterinary artificial intelligence",
    "dental diagnosis machine learning",
    "medical coding automation",
    "legal document artificial intelligence",
    "insurance claims automation",
    "clinical notes natural language processing",
    "practice management software",
    "healthcare workflow automation",
    "regulatory compliance artificial intelligence",
]


def search_patents_by_keyword(
    query: str,
    per_page: int = 25,
    days_back: int = 365,
) -> list[dict]:
    """
    Search USPTO patents by keyword using the PatentsView API.
    Returns recent patent applications in thesis-relevant domains.
    """
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # PatentsView uses a JSON query format
    request_body = json.dumps({
        "q": {
            "_and": [
                {"_text_any": {"patent_abstract": query}},
                {"_gte": {"patent_date": cutoff}},
            ]
        },
        "f": [
            "patent_number", "patent_title", "patent_abstract",
            "patent_date", "patent_type",
            "assignee_organization", "assignee_country",
            "inventor_first_name", "inventor_last_name",
        ],
        "o": {"page": 1, "per_page": per_page},
        "s": [{"patent_date": "desc"}],
    }).encode("utf-8")

    req = urllib.request.Request(
        USPTO_API,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "thesis-agent/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("patents", [])
    except Exception as e:
        print(f"  [WARN] USPTO API error for '{query}': {e}")
        return []


def scan_patent_filings(
    queries: list[str] = None,
    days_back: int = 180,
) -> list[RawCandidate]:
    """
    Scan patent filings for thesis-relevant innovation.

    This catches companies building defensible IP in regulated verticals.
    Patent filings signal both technical depth and intent to create moats.
    """
    if queries is None:
        queries = THESIS_PATENT_QUERIES

    candidates = []
    seen_assignees = set()

    for query in queries:
        print(f"  Patents: searching '{query}'...")
        patents = search_patents_by_keyword(query, per_page=10, days_back=days_back)

        for patent in patents:
            if not patent:
                continue

            # Extract assignee (company) info
            assignees = patent.get("assignees", [{}])
            if not assignees:
                continue

            assignee = assignees[0] if isinstance(assignees, list) else assignees
            org_name = ""
            if isinstance(assignee, dict):
                org_name = assignee.get("assignee_organization", "").strip()
            elif isinstance(assignee, str):
                org_name = assignee

            if not org_name:
                continue

            # Skip known large incumbents — we want startups
            large_corps = [
                "google", "microsoft", "apple", "amazon", "meta",
                "ibm", "oracle", "siemens", "philips", "ge ",
                "johnson & johnson", "medtronic", "idexx",
            ]
            if any(corp in org_name.lower() for corp in large_corps):
                continue

            # Deduplicate by assignee
            if org_name.lower() in seen_assignees:
                continue
            seen_assignees.add(org_name.lower())

            title = patent.get("patent_title", "")
            abstract = patent.get("patent_abstract", "")[:300]
            patent_date = patent.get("patent_date", "")
            patent_number = patent.get("patent_number", "")
            country = ""
            if assignees and isinstance(assignees[0], dict):
                country = assignees[0].get("assignee_country", "")

            # Extract inventors
            inventors = patent.get("inventors", [])
            inventor_names = []
            if isinstance(inventors, list):
                for inv in inventors[:3]:
                    if isinstance(inv, dict):
                        first = inv.get("inventor_first_name", "")
                        last = inv.get("inventor_last_name", "")
                        if first or last:
                            inventor_names.append(f"{first} {last}".strip())

            candidates.append(
                RawCandidate(
                    name=org_name,
                    url=f"https://patents.google.com/patent/US{patent_number}" if patent_number else None,
                    description=(
                        f"Patent filing detected: '{title}'. "
                        f"Filed {patent_date}. Signals IP defensibility in {query}."
                    ),
                    source="patents_uspto",
                    source_url=f"https://patentsview.org/patent/{patent_number}" if patent_number else None,
                    raw_context=(
                        f"Patent: {title}. Abstract: {abstract}. "
                        f"Inventors: {', '.join(inventor_names)}. "
                        f"Country: {country}. Query: {query}."
                    ),
                )
            )

    print(f"  Patents: {len(candidates)} thesis-relevant assignees found")
    return candidates


def check_company_patents(
    company_name: str,
    days_back: int = 730,
) -> dict:
    """
    Check a specific company's patent activity.
    Used by the Ops agent to assess IP defensibility.

    Returns: {"total_patents": int, "recent_patents": int, "titles": list}
    """
    request_body = json.dumps({
        "q": {"_text_any": {"assignee_organization": company_name}},
        "f": ["patent_number", "patent_title", "patent_date"],
        "o": {"page": 1, "per_page": 50},
        "s": [{"patent_date": "desc"}],
    }).encode("utf-8")

    req = urllib.request.Request(
        USPTO_API,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "thesis-agent/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            patents = data.get("patents", [])

            cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            recent = [p for p in patents if p.get("patent_date", "") >= cutoff]

            return {
                "total_patents": len(patents),
                "recent_patents": len(recent),
                "titles": [p.get("patent_title", "") for p in patents[:5]],
            }
    except Exception:
        return {"total_patents": 0, "recent_patents": 0, "titles": []}
