"""
Scout Agent — Deal Sourcing Pipeline.

Pipeline: Sources → Dedup → Evaluate → Enrich (top hits) → Brief
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


def run_scout(
    config: dict | None = None,
    max_search_queries: int = 10,
    enrich_threshold: float = 7.0,
    output_dir: str = "outputs/daily",
    dry_run: bool = False,
) -> ScoutBrief:
    """
    Run the full scout pipeline.

    1. Gather candidates from all sources
    2. Deduplicate against seen companies
    3. Evaluate against thesis
    4. Enrich high-scoring companies
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

    # Web search (primary engine)
    if not dry_run:
        queries = get_search_queries(config)[:max_search_queries]
        print(f"  Running {len(queries)} web search queries...")
        web_candidates = run_discovery(queries, max_per_query=5)
        all_candidates.extend(web_candidates)
        print(f"  Web search: {len(web_candidates)} candidates")

    # Hacker News
    print("  Scanning Hacker News...")
    hn_show = scan_show_hn(max_items=30)
    hn_top = scan_top_stories(max_items=30)
    all_candidates.extend(hn_show)
    all_candidates.extend(hn_top)
    print(f"  HN total: {len(hn_show) + len(hn_top)} candidates")

    raw_count = len(all_candidates)
    print(f"\n  Total raw candidates: {raw_count}")

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
                # Find the original candidate for URL
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
    brief_file.write_text(format_scout_brief(brief, config))
    print(f"\n  Brief written to: {brief_file}")

    log_run("scout", raw_count=raw_count, passed_count=len(deduped), output_path=str(brief_file))

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  SCOUT COMPLETE")
    print(f"  Raw: {raw_count} | New: {len(deduped)} | Track: {len(enriched_track)} | Watch: {len(enriched_watch)}")
    print(f"{'=' * 60}\n")

    return brief


def format_scout_brief(brief: ScoutBrief, config: dict) -> str:
    """Format the scout brief as markdown."""
    fund = config["thesis"].get("fund", "")
    lines = [
        f"# Scout Brief — {brief.date}",
        f"**Fund:** {fund}",
        "",
        "## Summary",
        f"- **{brief.raw_candidates}** raw candidates scanned",
        f"- **{brief.passed_dedup}** passed deduplication",
        f"- **{brief.high_scoring}** scored 7+ and were enriched",
        f"- **{len(brief.recommended_track)}** recommended for tracking",
        f"- **{len(brief.watch_list)}** added to watch list",
        "",
    ]

    if brief.recommended_track:
        lines.append("---\n")
        lines.append("## Recommended: Track\n")
        for company in brief.recommended_track:
            ev = company.evaluation
            lines.extend([
                f"### {company.name} ({ev.composite_score} composite)",
                f"**What they do:** {company.description}",
                f"**Vertical:** {company.vertical} | **Stage:** {company.stage.value} | **Geography:** {company.geography or 'N/A'}",
                f"**Founded:** {company.founded or 'N/A'} | **Funding:** {company.funding_total or 'N/A'} | **Last Round:** {company.last_round or 'N/A'}",
                f"**Founders:** {', '.join(company.founders) if company.founders else 'N/A'}",
                f"**Founder Backgrounds:** {company.founder_backgrounds or 'N/A'}",
                "",
                f"| Dimension | Score |",
                f"|-----------|-------|",
                f"| Customer Durability | {ev.customer_durability or 'N/A'}/10 |",
                f"| Unit Economics | {ev.unit_economics or 'N/A'}/10 |",
                f"| Regulation Moat | {ev.regulation_moat or 'N/A'}/10 |",
                f"| Growth Inflection | {ev.growth_inflection or 'N/A'}/10 |",
                f"| Founder Quality | {ev.founder_quality or 'N/A'}/10 |",
                f"| Thesis Fit | {ev.thesis_fit or 'N/A'}/10 |",
                f"| Autopilot Potential | {ev.autopilot_potential or 'N/A'}/10 |",
                "",
                f"**Bull case:** {ev.bull_case}",
                f"**Bear case:** {ev.bear_case}",
                f"**Competitive landscape:** {company.competitive_landscape or 'N/A'}",
                f"**Regulatory context:** {company.regulatory_context or 'N/A'}",
                "",
                f"**Investors:** {', '.join(company.investors) if company.investors else 'N/A'}",
                "",
            ])

    if brief.watch_list:
        lines.append("---\n")
        lines.append("## Watch List\n")
        for company in brief.watch_list:
            ev = company.evaluation
            lines.extend([
                f"### {company.name} ({ev.composite_score} composite)",
                f"**What:** {ev.one_liner}",
                f"**Bull:** {ev.bull_case}",
                f"**Bear:** {ev.bear_case}",
                "",
            ])

    if brief.skipped:
        lines.append("---\n")
        lines.append(f"## Skipped ({len(brief.skipped)} companies)\n")
        for s in brief.skipped[:20]:
            lines.append(f"- **{s['name']}**: {s['reason']}")
        if len(brief.skipped) > 20:
            lines.append(f"\n*...and {len(brief.skipped) - 20} more*")

    return "\n".join(lines)
