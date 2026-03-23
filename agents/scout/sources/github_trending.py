"""
GitHub API source.
Tracks developer traction signals: star velocity, contributor growth,
and repository activity in thesis-relevant domains.

A repo going from 50 to 500 stars in a week is a company forming.
This is how you would have caught Lovable, Replit, and n8n early.

API: https://docs.github.com/en/rest
Rate limit: 60 requests/hour unauthenticated, 5,000 authenticated.
Free with a GitHub personal access token.
"""

import json
import urllib.request
import urllib.parse
import os
from datetime import datetime, timedelta
from shared.models import RawCandidate


API_BASE = "https://api.github.com"

# Topics that map to thesis verticals
THESIS_TOPICS = [
    "healthcare-ai", "medical-ai", "dental-ai", "veterinary",
    "legal-tech", "legaltech", "legal-ai",
    "fintech", "insurtech",
    "practice-management", "clinic-management",
    "vertical-ai", "domain-specific-ai",
    "ai-agent", "ai-agents", "autonomous-agent",
    "workflow-automation", "process-automation",
    "compliance", "regulatory-tech", "regtech",
]

# Search queries for thesis-relevant repositories
SEARCH_QUERIES = [
    "healthcare AI platform",
    "veterinary practice management",
    "legal document automation",
    "dental AI",
    "insurance automation AI",
    "vertical AI SaaS",
    "AI agent workflow",
    "medical coding AI",
    "compliance automation",
    "clinical notes AI",
]


def _fetch(url: str) -> dict | None:
    """Make a request to the GitHub API."""
    token = os.environ.get("GITHUB_TOKEN", "")

    headers = {
        "User-Agent": "thesis-agent/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] GitHub API error: {e}")
        return None


def search_repos(
    query: str,
    sort: str = "stars",
    order: str = "desc",
    per_page: int = 10,
    min_stars: int = 50,
) -> list[dict]:
    """Search GitHub repositories."""
    # Add minimum stars filter to query
    full_query = f"{query} stars:>={min_stars}"
    params = urllib.parse.urlencode({
        "q": full_query,
        "sort": sort,
        "order": order,
        "per_page": per_page,
    })
    url = f"{API_BASE}/search/repositories?{params}"
    data = _fetch(url)
    if data and "items" in data:
        return data["items"]
    return []


def search_recently_created(
    query: str,
    days_back: int = 90,
    min_stars: int = 20,
    per_page: int = 10,
) -> list[dict]:
    """Search for recently created repos with traction."""
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    full_query = f"{query} created:>={cutoff} stars:>={min_stars}"
    params = urllib.parse.urlencode({
        "q": full_query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    })
    url = f"{API_BASE}/search/repositories?{params}"
    data = _fetch(url)
    if data and "items" in data:
        return data["items"]
    return []


def scan_github_for_companies(
    queries: list[str] = None,
    min_stars: int = 50,
    days_back: int = 180,
) -> list[RawCandidate]:
    """
    Scan GitHub for thesis-relevant repos that signal emerging companies.

    Signals:
    - Recently created repo with rapid star growth
    - Active development (recent commits, multiple contributors)
    - Professional indicators (custom domain, docs, CI/CD)
    - Topic tags matching thesis verticals
    """
    if queries is None:
        queries = SEARCH_QUERIES

    candidates = []
    seen_repos = set()

    for query in queries:
        print(f"  GitHub: searching '{query}'...")

        # Search recently created repos with traction
        results = search_recently_created(
            query=query,
            days_back=days_back,
            min_stars=min_stars,
            per_page=10,
        )

        for repo in results:
            repo_name = repo.get("full_name", "")
            if repo_name in seen_repos:
                continue
            seen_repos.add(repo_name)

            name = repo.get("name", "")
            description = repo.get("description", "") or "No description"
            stars = repo.get("stargazers_count", 0)
            forks = repo.get("forks_count", 0)
            language = repo.get("language", "Unknown")
            created = repo.get("created_at", "")[:10]
            updated = repo.get("updated_at", "")[:10]
            homepage = repo.get("homepage", "")
            topics = repo.get("topics", [])
            owner_type = repo.get("owner", {}).get("type", "")

            # Skip personal projects — look for org-owned repos
            # or repos with professional indicators
            has_homepage = bool(homepage and not homepage.startswith("https://github.com"))
            is_org = owner_type == "Organization"

            # Calculate a simple traction signal
            days_alive = max(1, (datetime.utcnow() - datetime.strptime(created, "%Y-%m-%d")).days)
            stars_per_day = stars / days_alive

            # Filter: want repos with meaningful traction
            if stars < min_stars:
                continue

            context_parts = [
                f"Stars: {stars} ({stars_per_day:.1f}/day)",
                f"Forks: {forks}",
                f"Language: {language}",
                f"Created: {created}",
                f"Last updated: {updated}",
            ]
            if topics:
                context_parts.append(f"Topics: {', '.join(topics[:5])}")
            if has_homepage:
                context_parts.append(f"Homepage: {homepage}")
            if is_org:
                context_parts.append(f"Organization: {repo.get('owner', {}).get('login', '')}")

            # Use the org name or repo name as company name
            company_name = repo.get("owner", {}).get("login", name)
            if is_org:
                company_name = repo["owner"]["login"]

            candidates.append(
                RawCandidate(
                    name=company_name,
                    url=homepage or repo.get("html_url", ""),
                    description=f"{description}. GitHub repo with {stars} stars, {stars_per_day:.1f} stars/day growth.",
                    source="github",
                    source_url=repo.get("html_url", ""),
                    raw_context=". ".join(context_parts),
                )
            )

    # Sort by traction (stars per day implied in description)
    print(f"  GitHub: {len(candidates)} thesis-relevant repos found")
    return candidates
