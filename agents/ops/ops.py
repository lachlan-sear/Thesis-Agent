"""
Ops Agent — Tracker & Dossier Management.

Audits tracked companies for staleness, suggests promotions and kills,
and cross-references with market signals and contact networks.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from shared.claude_client import get_client
from shared.config_loader import load_config, get_thesis_text
from shared.models import (
    OpsReview, OpsRecommendation, TrackerEntry, TrackerStatus, Urgency
)
from shared.db import init_db, get_recent_signals, get_all_seen, log_run


TRACKER_STATE_PATH = Path(__file__).parent.parent.parent / "config" / "tracker_state.json"


def load_tracker_state() -> list[TrackerEntry]:
    """Load the current tracker state from JSON."""
    if not TRACKER_STATE_PATH.exists():
        return []

    with open(TRACKER_STATE_PATH) as f:
        data = json.load(f)

    entries = []
    for item in data:
        try:
            entry = TrackerEntry(
                name=item["name"],
                url=item.get("url"),
                vertical=item.get("vertical", "Unknown"),
                stage=item.get("stage", "unknown"),
                status=item.get("status", "active"),
                composite_score=item.get("composite_score"),
                last_updated=datetime.fromisoformat(item.get("last_updated", "2025-01-01")),
                added_at=datetime.fromisoformat(item.get("added_at", "2025-01-01")),
                notes=item.get("notes"),
                benchmark=item.get("benchmark", False),
            )
            # Calculate staleness
            delta = datetime.utcnow() - entry.last_updated
            entry.stale_days = delta.days
            entries.append(entry)
        except Exception:
            continue

    return entries


def audit_staleness(entries: list[TrackerEntry], stale_threshold: int = 30) -> list[OpsRecommendation]:
    """Flag companies not updated in the last N days."""
    recs = []
    for entry in entries:
        if entry.stale_days > stale_threshold and entry.status != TrackerStatus.KILLED:
            recs.append(OpsRecommendation(
                company=entry.name,
                action="refresh",
                reasoning=f"Last updated {entry.stale_days} days ago. Needs freshness check.",
                urgency=Urgency.ALERT if entry.stale_days > 60 else Urgency.NORMAL,
            ))
    return recs


def check_for_news(entries: list[TrackerEntry], config: dict) -> list[OpsRecommendation]:
    """Search for recent news on tracked companies."""
    client = get_client()
    recs = []

    # Only check active, non-stale companies (or stale ones for kill signals)
    to_check = [e for e in entries if e.status != TrackerStatus.KILLED][:20]  # Cap at 20 for cost

    for entry in to_check:
        print(f"  Checking: {entry.name}...")
        try:
            raw = client.search_and_summarise(
                query=f"{entry.name} startup funding round investors 2026",
                task_type="audit",
                system="""You are checking for recent news about a startup company.
Look specifically for:
1. New funding rounds or extensions
2. New investors joining the cap table
3. Revenue milestones or growth metrics
4. Product launches or pivots
5. Team changes (new C-suite, departures)
6. Regulatory developments affecting their vertical
7. Competitive moves (competitor funding, launches, acquisitions)
8. Shutdown or pivot signals

If you find a new funding round, note the amount, lead investor, and whether
previous investors followed on. This is a critical signal.

Return ONLY valid JSON: {"has_news": true/false, "news_type": "funding"|"acquisition"|"shutdown"|"product"|"hiring"|"none",
"summary": "brief description or empty", "action": "update"|"kill"|"promote"|"none"}""",
            )

            # Parse response
            cleaned = raw.strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(cleaned[start:end])
            else:
                continue

            if result.get("has_news") and result.get("action") != "none":
                action = result.get("action", "update")
                urgency = Urgency.ALERT if action in ("kill", "promote") else Urgency.NORMAL

                recs.append(OpsRecommendation(
                    company=entry.name,
                    action=action,
                    reasoning=result.get("summary", "News detected"),
                    evidence=f"Source: web search, type: {result.get('news_type', 'unknown')}",
                    urgency=urgency,
                ))

        except Exception as e:
            print(f"  [WARN] News check failed for {entry.name}: {e}")

    return recs


def cross_reference_signals(
    entries: list[TrackerEntry],
    signals: list[dict],
) -> list[dict]:
    """Cross-reference recent radar signals with tracked companies."""
    crossrefs = []
    entry_names = {e.name.lower() for e in entries}

    for signal in signals:
        company = (signal.get("company") or "").lower()
        if company and company in entry_names:
            crossrefs.append({
                "company": signal.get("company"),
                "signal_type": signal.get("type"),
                "summary": signal.get("summary"),
                "action": "Review tracker entry — radar detected activity",
            })

    return crossrefs


def run_ops(
    config: dict | None = None,
    output_dir: str = "outputs/weekly",
    dry_run: bool = False,
) -> OpsReview:
    """Run the ops agent."""
    if config is None:
        config = load_config()

    init_db()

    print("\n" + "=" * 60)
    print("  OPS AGENT — Tracker Management")
    print("=" * 60)

    # Load tracker state
    print("\n[1/4] Loading tracker state...")
    entries = load_tracker_state()

    if not entries:
        # If no tracker_state.json, use seen companies from DB
        seen = get_all_seen(action_filter="track")
        print(f"  No tracker_state.json found. Using {len(seen)} tracked companies from DB.")
        entries = [
            TrackerEntry(
                name=s["name"],
                url=s.get("url"),
                vertical="Unknown",
                composite_score=s.get("composite_score"),
                last_updated=datetime.fromisoformat(s.get("last_seen", "2025-01-01")),
                added_at=datetime.fromisoformat(s.get("first_seen", "2025-01-01")),
            )
            for s in seen
        ]

    print(f"  {len(entries)} companies in tracker")

    # Staleness audit
    print("\n[2/4] Auditing staleness...")
    stale_recs = audit_staleness(entries)
    print(f"  {len(stale_recs)} flagged stale")

    # News check
    news_recs = []
    if not dry_run and entries:
        print(f"\n[3/4] Checking for news on tracked companies...")
        news_recs = check_for_news(entries, config)
        print(f"  {len(news_recs)} companies have news")
    else:
        print("\n[3/4] Skipping news check (dry run or empty tracker)")

    # Cross-reference with radar signals
    print("\n[4/4] Cross-referencing with radar signals...")
    recent_signals = get_recent_signals(days=7)
    crossrefs = cross_reference_signals(entries, recent_signals)
    print(f"  {len(crossrefs)} cross-references found")

    # Separate recommendations
    all_recs = stale_recs + news_recs
    promotions = [r for r in all_recs if r.action == "promote"]
    kills = [r for r in all_recs if r.action == "kill"]
    updates = [r for r in all_recs if r.action in ("update", "refresh")]

    review = OpsReview(
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        total_tracked=len(entries),
        flagged_stale=len(stale_recs),
        funding_updates=len([r for r in news_recs if "funding" in (r.evidence or "").lower()]),
        shutdowns_detected=len(kills),
        promotions=promotions,
        kills=kills,
        updates=updates,
        dossier_crossrefs=crossrefs,
    )

    # Write output
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    brief_file = output_path / f"ops_{review.date}.md"
    brief_file.write_text(format_ops_review(review, config))
    print(f"\n  Review written to: {brief_file}")

    log_run("ops", raw_count=len(entries), passed_count=len(all_recs), output_path=str(brief_file))

    print(f"\n{'=' * 60}")
    print(f"  OPS COMPLETE — {len(entries)} tracked | {len(promotions)} promote | {len(kills)} kill | {len(updates)} update")
    print(f"{'=' * 60}\n")

    return review


def format_ops_review(review: OpsReview, config: dict) -> str:
    """Format ops review as markdown."""
    fund = config["thesis"].get("fund", "")
    lines = [
        f"# Ops Review — {review.date}",
        f"**Fund:** {fund}",
        "",
        "## Tracker Health",
        f"- **{review.total_tracked}** companies tracked",
        f"- **{review.flagged_stale}** flagged stale (>30 days since update)",
        f"- **{review.funding_updates}** funding updates detected",
        f"- **{review.shutdowns_detected}** shutdowns/kills detected",
        "",
    ]

    if review.promotions:
        lines.append("---\n\n## Promote to Benchmark\n")
        for r in review.promotions:
            lines.extend([
                f"### {r.company}",
                f"**Reasoning:** {r.reasoning}",
                f"**Evidence:** {r.evidence or 'N/A'}",
                "",
            ])

    if review.kills:
        lines.append("---\n\n## Suggested Kills\n")
        for r in review.kills:
            lines.extend([
                f"### {r.company}",
                f"**Reasoning:** {r.reasoning}",
                f"**Evidence:** {r.evidence or 'N/A'}",
                "",
            ])

    if review.updates:
        lines.append("---\n\n## Updates Required\n")
        for r in review.updates:
            prefix = "🔴" if r.urgency == Urgency.ALERT else "🔵"
            lines.append(f"{prefix} **{r.company}**: {r.reasoning}")
        lines.append("")

    if review.dossier_crossrefs:
        lines.append("---\n\n## Radar Cross-References\n")
        for cr in review.dossier_crossrefs:
            lines.append(f"- **{cr['company']}** [{cr['signal_type']}]: {cr['summary']}")
        lines.append("")

    return "\n".join(lines)
