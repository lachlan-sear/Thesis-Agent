"""
Scout Agent — Deal Sourcing Pipeline.

Pipeline: Sources → Dedup → Evaluate → Enrich (top hits) → Brief

10 Sources:
  1. Claude web search — thesis-targeted queries across 7 signal categories
  2. Hacker News — Show HN + top stories (free, no auth)
  3. Companies House — UK incorporations by SIC code (free)
  4. GitHub — developer traction signals (free)
  5. Adzuna — hiring velocity, the #1 breakout predictor (free tier)
  6. RSS feeds — Sifted, TechCrunch, EU-Startups (free, no auth)
  7. Product Hunt — catches companies on launch day (free with token)
  8. Reddit — practitioner frustration and adoption signals (free)
  9. USPTO Patents — IP defensibility signals (free, no auth)
  10. Wikipedia — mindshare trending (free, no auth) [used by Radar]
"""

import json
from datetime import datetime
from pathlib import Path

from shared.config_loader import load_config, get_search_queries
from shared.models import RawCandidate, Action, ScoutBrief
from shared.db import init_db, is_seen, mark_seen, save_evaluation, log_run
from agents.scout.sources.web_search import run_discovery
from agents.scout.sources.hn import scan_show_hn, scan_top_stories
from agents.scout.evaluator import evaluate_batch
from agents.scout.enricher import enrich_company

# All optional sources — gracefully skip if not available or not configured
_OPTIONAL_SOURCES = {}

try:
    from agents.scout.sources.companies_house import search_recently_incorporated
    _OPTIONAL_SOURCES["companies_house"] = True
except ImportError:
    _OPTIONAL_SOURCES["companies_house"] = False

try:
    from agents.scout.sources.github_trending import scan_github_for_companies
    _OPTIONAL_SOURCES["github"] = True
except ImportError:
    _OPTIONAL_SOURCES["github"] = False

try:
    from agents.scout.sources.adzuna_hiring import scan_vertical_hiring
    _OPTIONAL_SOURCES["adzuna"] = True
except ImportError:
    _OPTIONAL_SOURCES["adzuna"] = False

try:
    from agents.scout.sources.rss import scan_rss_feeds
    _OPTIONAL_SOURCES["rss"] = True
except ImportError:
    _OPTIONAL_SOURCES["rss"] = False

try:
    from agents.scout.sources.producthunt import scan_product_hunt
    _OPTIONAL_SOURCES["producthunt"] = True
except ImportError:
    _OPTIONAL_SOURCES["producthunt"] = False

try:
    from agents.scout.sources.reddit import scan_reddit_signals
    _OPTIONAL_SOURCES["reddit"] = True
except ImportError:
    _OPTIONAL_SOURCES["reddit"] = False

try:
    from agents.scout.sources.patents import scan_patent_filings
    _OPTIONAL_SOURCES["patents"] = True
except ImportError:
    _OPTIONAL_SOURCES["patents"] = False


def _run_source(name: str, func, config: dict, source_counts: dict, all_candidates: list, **kwargs):
    """Helper to run a source with error handling and reporting."""
    print(f"\n  [{name}] Scanning...")
    try:
        results = func(**kwargs)
        all_candidates.extend(results)
        source_counts[name.lower().replace(" ", "_")] = len(results)
        print(f"  → {len(results)} candidates")
    except Exception as e:
        print(f"  → Failed ({e})")
        source_counts[name.lower().replace(" ", "_")] = 0


def run_scout(
    config: dict | None = None,
    max_search_queries: int = 10,
    enrich_threshold: float = 7.0,
    output_dir: str = "outputs/daily",
    dry_run: bool = False,
) -> ScoutBrief:
    """Run the full scout pipeline."""
    if config is None:
        config = load_config()

    init_db()
    sources_cfg = config.get("sources", {})

    print("\n" + "=" * 60)
    print("  SCOUT AGENT — Deal Sourcing")
    print(f"  Sources available: {sum(1 for v in _OPTIONAL_SOURCES.values() if v) + 2}/10")
    print("=" * 60)

    # --- Step 1: Gather candidates from all sources ---
    print("\n[1/5] Gathering candidates...")

    all_candidates: list[RawCandidate] = []
    source_counts = {}

    # 1. Claude web search (primary — always on unless dry run)
    if not dry_run:
        queries = get_search_queries(config)[:max_search_queries]
        print(f"\n  [Web Search] Running {len(queries)} thesis-targeted queries...")
        web = run_discovery(queries, max_per_query=5)
        all_candidates.extend(web)
        source_counts["web_search"] = len(web)
        print(f"  → {len(web)} candidates")

    # 2. Hacker News (always on — free, no auth)
    print(f"\n  [Hacker News] Scanning...")
    hn_show = scan_show_hn(max_items=30)
    hn_top = scan_top_stories(max_items=30)
    all_candidates.extend(hn_show + hn_top)
    source_counts["hacker_news"] = len(hn_show) + len(hn_top)
    print(f"  → {len(hn_show) + len(hn_top)} candidates")

    # 3. Companies House (free UK incorporation data)
    if _OPTIONAL_SOURCES.get("companies_house") and sources_cfg.get("companies_house", {}).get("enabled"):
        _run_source("Companies House", search_recently_incorporated, config, source_counts, all_candidates, days_back=90)
    else:
        print(f"\n  [Companies House] Skipped")

    # 4. GitHub (free developer traction)
    if _OPTIONAL_SOURCES.get("github") and sources_cfg.get("github_trending", {}).get("enabled"):
        min_stars = sources_cfg.get("github_trending", {}).get("min_stars_velocity", 50)
        _run_source("GitHub", scan_github_for_companies, config, source_counts, all_candidates, min_stars=min_stars)
    else:
        print(f"\n  [GitHub] Skipped")

    # 5. Adzuna (free hiring velocity)
    if _OPTIONAL_SOURCES.get("adzuna") and not dry_run:
        _run_source("Adzuna Hiring", scan_vertical_hiring, config, source_counts, all_candidates)
    else:
        print(f"\n  [Adzuna] Skipped")

    # 6. RSS feeds (free, no auth)
    if _OPTIONAL_SOURCES.get("rss") and sources_cfg.get("rss_feeds", {}).get("enabled"):
        feeds = sources_cfg.get("rss_feeds", {}).get("feeds", [])
        _run_source("RSS Feeds", scan_rss_feeds, config, source_counts, all_candidates, feeds=feeds if feeds else None)
    else:
        print(f"\n  [RSS] Skipped")

    # 7. Product Hunt (free with token)
    if _OPTIONAL_SOURCES.get("producthunt") and not dry_run:
        _run_source("Product Hunt", scan_product_hunt, config, source_counts, all_candidates)
    else:
        print(f"\n  [Product Hunt] Skipped")

    # 8. Reddit (free, rate-limited)
    if _OPTIONAL_SOURCES.get("reddit") and not dry_run:
        _run_source("Reddit", scan_reddit_signals, config, source_counts, all_candidates)
    else:
        print(f"\n  [Reddit] Skipped")

    # 9. USPTO Patents (free, no auth)
    if _OPTIONAL_SOURCES.get("patents") and not dry_run:
        _run_source("Patents", scan_patent_filings, config, source_counts, all_candidates)
    else:
        print(f"\n  [Patents] Skipped")

    raw_count = len(all_candidates)
    print(f"\n  ┌─────────────────────────────────")
    print(f"  │ Total raw candidates: {raw_count}")
    for source, count in source_counts.items():
        print(f"  │   {source}: {count}")
    print(f"  └─────────────────────────────────")

    # --- Step 2: Deduplicate ---
    print("\n[2/5] Deduplicating...")
    new_candidates = [c for c in all_candidates if not is_seen(c.name)]

    seen_in_batch = set()
    deduped = []
    for c in new_candidates:
        key = c.name.lower().strip()
        if key not in seen_in_batch:
            seen_in_batch.add(key)
            deduped.append(c)

    print(f"  {raw_count} raw → {len(deduped)} new")

    if not deduped:
        print("\n  No new candidates to evaluate.")
        return ScoutBrief(date=datetime.utcnow().strftime("%Y-%m-%d"), raw_candidates=raw_count, passed_dedup=0, high_scoring=0)

    # --- Step 3: Evaluate ---
    print(f"\n[3/5] Evaluating {len(deduped)} candidates against thesis...")
    if dry_run:
        print("  [DRY RUN] Skipping evaluation")
        evaluations = []
    else:
        evaluations = evaluate_batch(deduped, config)

    for ev in evaluations:
        mark_seen(ev.company_name, source="scout", composite_score=ev.composite_score, action=ev.action.value)
        save_evaluation(ev.company_name, ev.model_dump())

    # --- Step 4: Enrich high-scoring companies ---
    high_scoring = [e for e in evaluations if e.composite_score >= enrich_threshold]
    print(f"\n[4/5] Enriching {len(high_scoring)} companies scoring {enrich_threshold}+...")

    enriched_track, enriched_watch = [], []

    if not dry_run:
        for ev in evaluations:
            orig = next((c for c in deduped if c.name.lower() == ev.company_name.lower()), None)
            url = orig.url if orig else None
            if ev.action == Action.TRACK and ev.composite_score >= enrich_threshold:
                print(f"  Enriching: {ev.company_name}...")
                enriched_track.append(enrich_company(ev.company_name, url, ev))
            elif ev.action == Action.WATCH:
                enriched_watch.append(enrich_company(ev.company_name, url, ev))

    # --- Step 5: Generate brief ---
    print(f"\n[5/5] Generating brief...")

    skipped = [{"name": ev.company_name, "reason": ev.reasoning[:100]} for ev in evaluations if ev.action == Action.SKIP]

    brief = ScoutBrief(
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        raw_candidates=raw_count,
        passed_dedup=len(deduped),
        high_scoring=len(high_scoring),
        recommended_track=enriched_track,
        watch_list=enriched_watch,
        skipped=skipped,
    )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    brief_file = output_path / f"scout_{brief.date}.md"
    brief_file.write_text(format_scout_brief(brief, config, source_counts))
    print(f"\n  Brief → {brief_file}")

    log_run("scout", raw_count=raw_count, passed_count=len(deduped), output_path=str(brief_file))

    print(f"\n{'=' * 60}")
    print(f"  SCOUT COMPLETE")
    print(f"  Raw: {raw_count} | New: {len(deduped)} | Track: {len(enriched_track)} | Watch: {len(enriched_watch)}")
    print(f"{'=' * 60}\n")

    return brief


def format_scout_brief(brief: ScoutBrief, config: dict, source_counts: dict = None) -> str:
    """Format the scout brief as a VC-grade markdown report."""
    thesis_name = config["thesis"].get("name", "")
    lines = [
        f"# Scout Brief — {brief.date}",
        f"**Thesis:** {thesis_name}",
        "",
        "## Pipeline Summary",
        "",
        f"| Stage | Count |",
        f"|-------|-------|",
        f"| Raw candidates scanned | {brief.raw_candidates} |",
        f"| Passed deduplication | {brief.passed_dedup} |",
        f"| Scored 7+ (enriched) | {brief.high_scoring} |",
        f"| **Recommended: Track** | **{len(brief.recommended_track)}** |",
        f"| Watch list | {len(brief.watch_list)} |",
        "",
    ]

    if source_counts:
        lines.append("**Sources scanned:**")
        for source, count in source_counts.items():
            lines.append(f"- {source.replace('_', ' ').title()}: {count}")
        lines.append("")

    if brief.recommended_track:
        lines.append("---\n")
        lines.append("## Recommended: Track\n")
        lines.append("*Scored 7+ against thesis. Warrant a first meeting.*\n")

        for company in brief.recommended_track:
            ev = company.evaluation
            lines.extend([
                f"### {company.name}",
                f"**{ev.one_liner}**",
                "",
                f"| | |",
                f"|---|---|",
                f"| **Vertical** | {company.vertical} |",
                f"| **Stage** | {company.stage.value} |",
                f"| **Geography** | {company.geography or 'N/A'} |",
                f"| **Founded** | {company.founded or 'N/A'} |",
                f"| **Funding** | {company.funding_total or 'N/A'} |",
                f"| **Last Round** | {company.last_round or 'N/A'} |",
                f"| **Investors** | {', '.join(company.investors) if company.investors else 'N/A'} |",
                "",
                f"**Founders:** {', '.join(company.founders) if company.founders else 'N/A'}",
                f"**Founder-Market Fit:** {company.founder_backgrounds or 'N/A'}",
                "",
                f"#### Thesis Scorecard",
                "",
                f"| Dimension | Score |",
                f"|-----------|:-----:|",
                f"| Thesis Fit | **{ev.thesis_fit or '?'}**/10 |",
                f"| Customer Durability | **{ev.customer_durability or '?'}**/10 |",
                f"| Regulation Moat | **{ev.regulation_moat or '?'}**/10 |",
                f"| Unit Economics | **{ev.unit_economics or '?'}**/10 |",
                f"| Growth Inflection | **{ev.growth_inflection or '?'}**/10 |",
                f"| Founder Quality | **{ev.founder_quality or '?'}**/10 |",
                f"| Autopilot Potential | **{ev.autopilot_potential or '?'}**/10 |",
                f"| **Composite** | **{ev.composite_score}**/10 |",
                "",
                f"**Bull case:** {ev.bull_case}",
                "",
                f"**Bear case:** {ev.bear_case}",
                "",
                f"**Competitive landscape:** {company.competitive_landscape or 'N/A'}",
                "",
                f"**Regulatory context:** {company.regulatory_context or 'N/A'}",
                "",
                f"**Product maturity:** {company.product_maturity or 'N/A'}",
                "",
                "---\n",
            ])

    if brief.watch_list:
        lines.append("## Watch List\n")
        for company in brief.watch_list:
            ev = company.evaluation
            lines.extend([
                f"**{company.name}** ({ev.composite_score}/10) — {ev.one_liner}",
                f"- Bull: {ev.bull_case}",
                f"- Bear: {ev.bear_case}",
                "",
            ])

    if brief.skipped:
        lines.append("---\n")
        lines.append(f"## Skipped ({len(brief.skipped)})\n")
        for s in brief.skipped[:15]:
            lines.append(f"- **{s['name']}**: {s['reason']}")
        if len(brief.skipped) > 15:
            lines.append(f"\n*...and {len(brief.skipped) - 15} more*")

    lines.extend([
        "", "---",
        f"*Generated by [thesis-agent](https://github.com/lachlan-sear/thesis-agent) on {brief.date}.*",
        f"*Claude API (Sonnet → scoring, Opus → synthesis). "
        f"10 sources: Web search, HN, Companies House, GitHub, Adzuna, RSS, Product Hunt, Reddit, Patents, Wikipedia.*",
    ])

    return "\n".join(lines)
