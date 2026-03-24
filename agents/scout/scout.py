"""
Scout Agent — Deal Sourcing Pipeline.

Pipeline: Sources → Dedup → Evaluate → Enrich (top hits) → Brief

12 Sources covering the full company lifecycle:
  1.  Claude web search — thesis-targeted queries across 7 signal categories
  2.  Hacker News — Show HN + top stories
  3.  Companies House — UK incorporations by SIC code
  4.  GitHub — developer traction signals
  5.  Adzuna — hiring velocity (#1 breakout predictor)
  6.  RSS feeds — Sifted, TechCrunch, EU-Startups, newsletters
  7.  Product Hunt — catches companies on launch day
  8.  Reddit — practitioner frustration and adoption signals
  9.  USPTO Patents — IP defensibility signals
  10. Wikipedia — mindshare trending
  11. Podcasts — 20VC, Riding Unicorns, founder appearance signals
  12. Twitter/X — funding announcements and investor activity
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

# Optional sources — each gracefully skips if not available
_SRC = {}
_source_imports = {
    "companies_house": ("agents.scout.sources.companies_house", "search_recently_incorporated"),
    "github": ("agents.scout.sources.github_trending", "scan_github_for_companies"),
    "adzuna": ("agents.scout.sources.adzuna_hiring", "scan_vertical_hiring"),
    "rss": ("agents.scout.sources.rss", "scan_rss_feeds"),
    "producthunt": ("agents.scout.sources.producthunt", "scan_product_hunt"),
    "reddit": ("agents.scout.sources.reddit", "scan_reddit_signals"),
    "patents": ("agents.scout.sources.patents", "scan_patent_filings"),
    "podcasts": ("agents.scout.sources.podcasts", "scan_podcasts"),
    "twitter": ("agents.scout.sources.twitter", "scan_twitter_signals"),
}

for key, (module_path, func_name) in _source_imports.items():
    try:
        mod = __import__(module_path, fromlist=[func_name])
        _SRC[key] = getattr(mod, func_name)
    except (ImportError, AttributeError):
        _SRC[key] = None


def _run_source(name: str, func, source_counts: dict, all_candidates: list, **kwargs):
    """Run a source with error handling."""
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
    available = sum(1 for v in _SRC.values() if v is not None) + 2  # +2 for web search and HN

    print("\n" + "=" * 60)
    print("  SCOUT AGENT — Deal Sourcing")
    print(f"  Sources available: {available}/12")
    print("=" * 60)

    all_candidates: list[RawCandidate] = []
    source_counts = {}

    # --- Gather from all sources ---
    print("\n[1/5] Gathering candidates...")

    # 1. Web search (primary — always on unless dry run)
    if not dry_run:
        queries = get_search_queries(config)[:max_search_queries]
        print(f"\n  [Web Search] {len(queries)} thesis-targeted queries...")
        web = run_discovery(queries, max_per_query=5)
        all_candidates.extend(web)
        source_counts["web_search"] = len(web)
        print(f"  → {len(web)} candidates")

    # 2. Hacker News (always on)
    print(f"\n  [Hacker News] Show HN + top stories...")
    hn_show = scan_show_hn(max_items=30)
    hn_top = scan_top_stories(max_items=30)
    all_candidates.extend(hn_show + hn_top)
    source_counts["hacker_news"] = len(hn_show) + len(hn_top)
    print(f"  → {source_counts['hacker_news']} candidates")

    # 3. Companies House
    if _SRC["companies_house"] and sources_cfg.get("companies_house", {}).get("enabled"):
        _run_source("Companies House", _SRC["companies_house"], source_counts, all_candidates, days_back=90)
    else:
        print(f"\n  [Companies House] Skipped")

    # 4. GitHub
    if _SRC["github"] and sources_cfg.get("github_trending", {}).get("enabled"):
        _run_source("GitHub", _SRC["github"], source_counts, all_candidates,
                     min_stars=sources_cfg.get("github_trending", {}).get("min_stars_velocity", 50))
    else:
        print(f"\n  [GitHub] Skipped")

    # 5. Adzuna hiring
    if _SRC["adzuna"] and not dry_run:
        _run_source("Adzuna Hiring", _SRC["adzuna"], source_counts, all_candidates)
    else:
        print(f"\n  [Adzuna] Skipped")

    # 6. RSS feeds
    if _SRC["rss"] and sources_cfg.get("rss_feeds", {}).get("enabled"):
        feeds = sources_cfg.get("rss_feeds", {}).get("feeds", [])
        _run_source("RSS Feeds", _SRC["rss"], source_counts, all_candidates,
                     feeds=feeds if feeds else None)
    else:
        print(f"\n  [RSS] Skipped")

    # 7. Product Hunt
    if _SRC["producthunt"] and not dry_run:
        _run_source("Product Hunt", _SRC["producthunt"], source_counts, all_candidates)
    else:
        print(f"\n  [Product Hunt] Skipped")

    # 8. Reddit
    if _SRC["reddit"] and not dry_run:
        _run_source("Reddit", _SRC["reddit"], source_counts, all_candidates)
    else:
        print(f"\n  [Reddit] Skipped")

    # 9. Patents
    if _SRC["patents"] and not dry_run:
        _run_source("Patents", _SRC["patents"], source_counts, all_candidates)
    else:
        print(f"\n  [Patents] Skipped")

    # 10. Podcasts (20VC, Riding Unicorns, etc.)
    if _SRC["podcasts"] and not dry_run:
        _run_source("Podcasts", _SRC["podcasts"], source_counts, all_candidates)
    else:
        print(f"\n  [Podcasts] Skipped")

    # 11. Twitter/X
    if _SRC["twitter"] and not dry_run:
        _run_source("Twitter/X", _SRC["twitter"], source_counts, all_candidates)
    else:
        print(f"\n  [Twitter/X] Skipped")

    raw_count = len(all_candidates)
    print(f"\n  ┌─────────────────────────────────")
    print(f"  │ Total raw candidates: {raw_count}")
    for src, count in source_counts.items():
        print(f"  │   {src}: {count}")
    print(f"  └─────────────────────────────────")

    # --- Dedup ---
    print("\n[2/5] Deduplicating...")
    new = [c for c in all_candidates if not is_seen(c.name)]
    seen_batch = set()
    deduped = []
    for c in new:
        key = c.name.lower().strip()
        if key not in seen_batch:
            seen_batch.add(key)
            deduped.append(c)
    print(f"  {raw_count} raw → {len(deduped)} new")

    if not deduped:
        return ScoutBrief(date=datetime.utcnow().strftime("%Y-%m-%d"),
                          raw_candidates=raw_count, passed_dedup=0, high_scoring=0)

    # --- Evaluate ---
    print(f"\n[3/5] Evaluating {len(deduped)} candidates...")
    evaluations = [] if dry_run else evaluate_batch(deduped, config)
    if dry_run:
        print("  [DRY RUN] Skipped")

    for ev in evaluations:
        mark_seen(ev.company_name, source="scout", composite_score=ev.composite_score, action=ev.action.value)
        save_evaluation(ev.company_name, ev.model_dump())

    # --- Enrich ---
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

    # --- Brief ---
    print(f"\n[5/5] Generating brief...")
    skipped = [{"name": ev.company_name, "reason": ev.reasoning[:100]}
               for ev in evaluations if ev.action == Action.SKIP]

    brief = ScoutBrief(
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        raw_candidates=raw_count, passed_dedup=len(deduped),
        high_scoring=len(high_scoring),
        recommended_track=enriched_track, watch_list=enriched_watch,
        skipped=skipped,
    )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    brief_file = output_path / f"scout_{brief.date}.md"
    brief_file.write_text(format_brief(brief, config, source_counts), encoding='utf-8')
    print(f"\n  Brief → {brief_file}")
    log_run("scout", raw_count=raw_count, passed_count=len(deduped), output_path=str(brief_file))

    print(f"\n{'=' * 60}")
    print(f"  SCOUT COMPLETE")
    print(f"  Raw: {raw_count} | New: {len(deduped)} | Track: {len(enriched_track)} | Watch: {len(enriched_watch)}")
    print(f"{'=' * 60}\n")
    return brief


def format_brief(brief: ScoutBrief, config: dict, source_counts: dict = None) -> str:
    """Format as VC-grade markdown."""
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
        for src, count in source_counts.items():
            lines.append(f"- {src.replace('_', ' ').title()}: {count}")
        lines.append("")

    if brief.recommended_track:
        lines.extend(["---\n", "## Recommended: Track\n",
                       "*Scored 7+ against thesis. Warrant a first meeting.*\n"])
        for company in brief.recommended_track:
            ev = company.evaluation
            lines.extend([
                f"### {company.name}", f"**{ev.one_liner}**", "",
                f"| | |", f"|---|---|",
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
                "", "#### Thesis Scorecard", "",
                f"| Dimension | Score | Notes |",
                f"|-----------|-------|-------|",
                f"| Thesis Fit | **{ev.thesis_fit or '?'}**/10 | |",
                f"| Customer Durability | **{ev.customer_durability or '?'}**/10 | |",
                f"| Regulation Moat | **{ev.regulation_moat or '?'}**/10 | |",
                f"| Unit Economics | **{ev.unit_economics or '?'}**/10 | |",
                f"| Growth Inflection | **{ev.growth_inflection or '?'}**/10 | |",
                f"| Founder Quality | **{ev.founder_quality or '?'}**/10 | |",
                f"| Autopilot Potential | **{ev.autopilot_potential or '?'}**/10 | *Selling the work or the tool?* |",
                f"| Funding & Cap Table | **{ev.funding_stage_score or '?'}**/10 | {ev.funding_detail or ''} |",
                f"| TAM / Market Size | **{ev.tam_score or '?'}**/10 | |",
                f"| Revenue Model | **{ev.revenue_model_score or '?'}**/10 | {ev.revenue_model_type or ''} |",
                f"| Go-to-Market | **{ev.gtm_score or '?'}**/10 | {ev.gtm_strategy or ''} |",
                f"| Geographic Scalability | **{ev.geo_scalability or '?'}**/10 | |",
                f"| Exit Potential | **{ev.exit_potential or '?'}**/10 | {ev.exit_comparables or ''} |",
                f"| **Composite** | **{ev.composite_score}**/10 | |",
                "",
                f"**Bull case:** {ev.bull_case}", "",
                f"**Bear case:** {ev.bear_case}", "",
                f"**Competitive landscape:** {company.competitive_landscape or 'N/A'}", "",
                f"**Regulatory context:** {company.regulatory_context or 'N/A'}", "",
                f"**Product maturity:** {company.product_maturity or 'N/A'}", "",
                f"**TAM estimate:** {company.tam_estimate or 'N/A'}",
                "",
                f"**Revenue model:** {company.revenue_model or 'N/A'}",
                "",
                f"**Distribution:** {company.gtm_strategy or 'N/A'}",
                "",
                f"**Distribution advantage:** {company.distribution_advantage or 'N/A'}",
                "",
                f"**Investor quality:** {company.investor_quality or 'N/A'}",
                "",
                f"**Exit comparables:** {company.exit_comparables or 'N/A'}",
                "",
                "---\n",
            ])

    if brief.watch_list:
        lines.append("## Watch List\n")
        for company in brief.watch_list:
            ev = company.evaluation
            lines.extend([
                f"**{company.name}** ({ev.composite_score}/10) — {ev.one_liner}",
                f"- Bull: {ev.bull_case}", f"- Bear: {ev.bear_case}", "",
            ])

    if brief.skipped:
        lines.extend(["---\n", f"## Skipped ({len(brief.skipped)})\n"])
        for s in brief.skipped[:15]:
            lines.append(f"- **{s['name']}**: {s['reason']}")
        if len(brief.skipped) > 15:
            lines.append(f"\n*...and {len(brief.skipped) - 15} more*")

    lines.extend([
        "", "---",
        f"*Generated by [thesis-agent](https://github.com/lachlan-sear/thesis-agent) on {brief.date}.*",
        "*12 sources: Web search, Hacker News, Companies House, GitHub, Adzuna, RSS, "
        "Product Hunt, Reddit, Patents, Wikipedia, Podcasts, Twitter/X.*",
    ])
    return "\n".join(lines)
