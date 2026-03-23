"""
Scout Agent — Deal Sourcing Pipeline.

Pipeline: Sources → Dedup → Evaluate → Enrich (top hits) → Brief

Sources:
  - Claude web search (thesis-targeted queries across 7 signal categories)
  - Hacker News (Show HN + top stories)
  - Companies House API (UK incorporations by SIC code — free)
  - GitHub API (developer traction signals — free)
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

# Optional sources — gracefully skip if not configured
try:
    from agents.scout.sources.companies_house import search_recently_incorporated
    HAS_COMPANIES_HOUSE = True
except ImportError:
    HAS_COMPANIES_HOUSE = False

try:
    from agents.scout.sources.github_trending import scan_github_for_companies
    HAS_GITHUB = True
except ImportError:
    HAS_GITHUB = False


def run_scout(
    config: dict | None = None,
    max_search_queries: int = 10,
    enrich_threshold: float = 7.0,
    output_dir: str = "outputs/daily",
    dry_run: bool = False,
) -> ScoutBrief:
    """
    Run the full scout pipeline.

    1. Gather candidates from all sources (parallel-ready)
    2. Deduplicate against seen companies
    3. Evaluate against thesis (Claude-powered, VC-grade rubric)
    4. Enrich high-scoring companies (deep research pass)
    5. Generate brief
    """
    if config is None:
        config = load_config()

    init_db()

    print("\n" + "=" * 60)
    print("  SCOUT AGENT — Deal Sourcing")
    print("=" * 60)

    # --- Step 1: Gather candidates ---
    print("\n[1/5] Gathering candidates from sources...")

    all_candidates: list[RawCandidate] = []
    source_counts = {}

    # Source 1: Claude web search (primary engine)
    if not dry_run:
        queries = get_search_queries(config)[:max_search_queries]
        print(f"\n  [Web Search] Running {len(queries)} thesis-targeted queries...")
        web_candidates = run_discovery(queries, max_per_query=5)
        all_candidates.extend(web_candidates)
        source_counts["web_search"] = len(web_candidates)
        print(f"  → {len(web_candidates)} candidates")

    # Source 2: Hacker News
    print(f"\n  [Hacker News] Scanning Show HN + top stories...")
    hn_show = scan_show_hn(max_items=30)
    hn_top = scan_top_stories(max_items=30)
    all_candidates.extend(hn_show)
    all_candidates.extend(hn_top)
    source_counts["hacker_news"] = len(hn_show) + len(hn_top)
    print(f"  → {len(hn_show) + len(hn_top)} candidates")

    # Source 3: Companies House (UK incorporations)
    if HAS_COMPANIES_HOUSE and config.get("sources", {}).get("companies_house", {}).get("enabled", False):
        print(f"\n  [Companies House] Scanning UK incorporations...")
        try:
            ch_candidates = search_recently_incorporated(days_back=90)
            all_candidates.extend(ch_candidates)
            source_counts["companies_house"] = len(ch_candidates)
            print(f"  → {len(ch_candidates)} candidates")
        except Exception as e:
            print(f"  → Skipped (error: {e})")
            source_counts["companies_house"] = 0
    else:
        print(f"\n  [Companies House] Skipped (not configured)")

    # Source 4: GitHub (developer traction)
    if HAS_GITHUB and config.get("sources", {}).get("github_trending", {}).get("enabled", False):
        print(f"\n  [GitHub] Scanning for thesis-relevant repos...")
        try:
            gh_candidates = scan_github_for_companies(
                min_stars=config.get("sources", {}).get("github_trending", {}).get("min_stars_velocity", 50)
            )
            all_candidates.extend(gh_candidates)
            source_counts["github"] = len(gh_candidates)
            print(f"  → {len(gh_candidates)} candidates")
        except Exception as e:
            print(f"  → Skipped (error: {e})")
            source_counts["github"] = 0
    else:
        print(f"\n  [GitHub] Skipped (not configured)")

    raw_count = len(all_candidates)
    print(f"\n  Total raw candidates: {raw_count}")
    for source, count in source_counts.items():
        print(f"    {source}: {count}")

    # --- Step 2: Deduplicate ---
    print("\n[2/5] Deduplicating against seen companies...")
    new_candidates = []
    for c in all_candidates:
        if not is_seen(c.name):
            new_candidates.append(c)

    # Also dedup within the current batch
    seen_in_batch = set()
    deduped = []
    for c in new_candidates:
        key = c.name.lower().strip()
        if key not in seen_in_batch:
            seen_in_batch.add(key)
            deduped.append(c)

    print(f"  {raw_count} raw → {len(deduped)} after dedup")

    if not deduped:
        print("\n  No new candidates to evaluate.")
        return ScoutBrief(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            raw_candidates=raw_count,
            passed_dedup=0,
            high_scoring=0,
        )

    # --- Step 3: Evaluate ---
    print(f"\n[3/5] Evaluating {len(deduped)} candidates against thesis...")

    if dry_run:
        print("  [DRY RUN] Skipping evaluation")
        evaluations = []
    else:
        evaluations = evaluate_batch(deduped, config)

    # Record all evaluations
    for ev in evaluations:
        mark_seen(
            ev.company_name,
            source="scout",
            composite_score=ev.composite_score,
            action=ev.action.value,
        )
        save_evaluation(ev.company_name, ev.model_dump())

    # --- Step 4: Enrich high-scoring companies ---
    high_scoring = [e for e in evaluations if e.composite_score >= enrich_threshold]
    print(f"\n[4/5] Enriching {len(high_scoring)} companies scoring {enrich_threshold}+...")

    enriched_track = []
    enriched_watch = []

    if not dry_run:
        for ev in evaluations:
            if ev.action == Action.TRACK and ev.composite_score >= enrich_threshold:
                print(f"  Enriching: {ev.company_name}...")
                orig = next((c for c in deduped if c.name.lower() == ev.company_name.lower()), None)
                url = orig.url if orig else None
                enriched = enrich_company(ev.company_name, url, ev)
                enriched_track.append(enriched)
            elif ev.action == Action.WATCH:
                orig = next((c for c in deduped if c.name.lower() == ev.company_name.lower()), None)
                url = orig.url if orig else None
                enriched = enrich_company(ev.company_name, url, ev)
                enriched_watch.append(enriched)

    # --- Step 5: Generate brief ---
    print(f"\n[5/5] Generating scout brief...")

    skipped = [
        {"name": ev.company_name, "reason": ev.reasoning[:100]}
        for ev in evaluations
        if ev.action == Action.SKIP
    ]

    brief = ScoutBrief(
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        raw_candidates=raw_count,
        passed_dedup=len(deduped),
        high_scoring=len(high_scoring),
        recommended_track=enriched_track,
        watch_list=enriched_watch,
        skipped=skipped,
    )

    # Write brief to file
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    brief_file = output_path / f"scout_{brief.date}.md"
    brief_file.write_text(format_scout_brief(brief, config, source_counts))
    print(f"\n  Brief written to: {brief_file}")

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
        lines.append("**Sources:**")
        for source, count in source_counts.items():
            lines.append(f"- {source.replace('_', ' ').title()}: {count} candidates")
        lines.append("")

    if brief.recommended_track:
        lines.append("---\n")
        lines.append("## Recommended: Track\n")
        lines.append("*These companies scored 7+ against the thesis and warrant a first meeting.*\n")

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
                f"| Dimension | Score | |",
                f"|-----------|:-----:|---|",
                f"| Thesis Fit | **{ev.thesis_fit or '?'}**/10 | |",
                f"| Customer Durability | **{ev.customer_durability or '?'}**/10 | |",
                f"| Regulation Moat | **{ev.regulation_moat or '?'}**/10 | |",
                f"| Unit Economics | **{ev.unit_economics or '?'}**/10 | |",
                f"| Growth Inflection | **{ev.growth_inflection or '?'}**/10 | |",
                f"| Founder Quality | **{ev.founder_quality or '?'}**/10 | |",
                f"| Autopilot Potential | **{ev.autopilot_potential or '?'}**/10 | *Selling the work or the tool?* |",
                f"| **Composite** | **{ev.composite_score}**/10 | |",
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
                f"**Reasoning:** {ev.reasoning}",
                "",
                "---\n",
            ])

    if brief.watch_list:
        lines.append("## Watch List\n")
        lines.append("*Thesis-adjacent. Not yet meeting-ready but worth monitoring.*\n")
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
        lines.append(f"## Skipped ({len(brief.skipped)} companies)\n")
        for s in brief.skipped[:15]:
            lines.append(f"- **{s['name']}**: {s['reason']}")
        if len(brief.skipped) > 15:
            lines.append(f"\n*...and {len(brief.skipped) - 15} more*")

    lines.extend([
        "",
        "---",
        f"*Generated by thesis-agent on {brief.date}.*",
        f"*Evaluation: Claude API with model routing (Sonnet for scoring, Opus for synthesis).*",
        f"*Sources: Web search, Hacker News, Companies House, GitHub.*",
    ])

    return "\n".join(lines)
