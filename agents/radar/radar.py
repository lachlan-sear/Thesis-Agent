"""
Radar Agent — Market Intelligence.

Monitors funding rounds, exits, regulatory changes, and competitive moves
across thesis-relevant verticals. Generates daily signals and weekly synthesis.
"""

import json
from datetime import datetime
from pathlib import Path

from shared.claude_client import get_client
from shared.config_loader import load_config, get_thesis_text
from shared.models import Signal, SignalType, Urgency, RadarDigest
from shared.db import init_db, save_signal, get_recent_signals, log_run


# --- Funding Monitor ---

def scan_funding(config: dict) -> list[Signal]:
    """Search for recent funding rounds in thesis-relevant verticals."""
    client = get_client()
    thesis = config["thesis"]
    verticals = thesis.get("target_verticals", {}).get("primary", [])

    signals = []

    for vertical in verticals:
        query = f"{vertical} startup funding round 2026"
        print(f"  Scanning funding: {vertical}...")

        try:
            raw = client.search_and_summarise(
                query=query,
                task_type="evaluate",
                system="""You are a venture capital market analyst. Search for recent startup
funding rounds in the given sector. For each round found, extract structured data.
Return ONLY a JSON array. Each object: {"company": "name", "round": "Series A",
"amount": "$10M", "lead_investor": "name or Unknown", "vertical": "sector",
"summary": "one sentence", "urgency": "normal" or "alert"}
If no rounds found, return: []""",
                prompt_template=f"Find recent (last 30 days) startup funding rounds in: {{query}}",
            )

            # Parse JSON from response
            try:
                cleaned = raw.strip()
                start = cleaned.find("[")
                end = cleaned.rfind("]") + 1
                if start >= 0 and end > start:
                    rounds = json.loads(cleaned[start:end])
                else:
                    rounds = []
            except json.JSONDecodeError:
                rounds = []

            for r in rounds:
                if isinstance(r, dict) and r.get("company"):
                    sig = Signal(
                        type=SignalType.FUNDING,
                        source="web_search",
                        company=r.get("company"),
                        vertical=r.get("vertical", vertical),
                        summary=f"{r.get('company')} raised {r.get('amount', '?')} ({r.get('round', '?')}). Lead: {r.get('lead_investor', 'Unknown')}. {r.get('summary', '')}",
                        urgency=Urgency(r.get("urgency", "normal")),
                    )
                    signals.append(sig)
                    save_signal(sig.model_dump())

        except Exception as e:
            print(f"  [WARN] Funding scan failed for {vertical}: {e}")

    return signals


# --- Exits Monitor ---

def scan_exits(config: dict) -> list[Signal]:
    """Search for recent exits (acquisitions, IPOs, shutdowns)."""
    client = get_client()

    queries = [
        "startup acquisition 2026 tech consumer",
        "startup shutdown 2026",
        "tech IPO filing 2026",
        "AI company acquired 2026",
    ]

    signals = []

    for query in queries:
        print(f"  Scanning exits: {query[:40]}...")

        try:
            raw = client.search_and_summarise(
                query=query,
                task_type="evaluate",
                system="""You are a venture capital market analyst tracking exits.
Return ONLY a JSON array of exit events. Each object:
{"company": "name", "type": "acquisition" | "ipo" | "shutdown",
"details": "brief description", "vertical": "sector",
"acquirer": "name or null", "amount": "value or Unknown"}
If none found, return: []""",
            )

            cleaned = raw.strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1
            if start >= 0 and end > start:
                exits = json.loads(cleaned[start:end])
            else:
                exits = []

            for ex in exits:
                if isinstance(ex, dict) and ex.get("company"):
                    exit_type = ex.get("type", "exit")
                    sig_type = {
                        "acquisition": SignalType.EXIT,
                        "ipo": SignalType.EXIT,
                        "shutdown": SignalType.SHUTDOWN,
                    }.get(exit_type, SignalType.EXIT)

                    sig = Signal(
                        type=sig_type,
                        source="web_search",
                        company=ex.get("company"),
                        vertical=ex.get("vertical", "tech"),
                        summary=f"{ex.get('company')}: {exit_type}. {ex.get('details', '')}",
                        urgency=Urgency.ALERT if exit_type == "shutdown" else Urgency.NORMAL,
                    )
                    signals.append(sig)
                    save_signal(sig.model_dump())

        except Exception as e:
            print(f"  [WARN] Exit scan failed: {e}")

    return signals


# --- Trend Monitor ---

def scan_trends(config: dict) -> list[Signal]:
    """Search for emerging trends and regulatory changes."""
    client = get_client()
    thesis = config["thesis"]

    trend_queries = [
        "AI regulation update Europe UK 2026",
        "EU AI Act enforcement 2026",
        "digital health regulation FDA 2026",
        "fintech regulation FCA 2026",
        "consumer AI startup trends 2026",
        "vertical AI market trends 2026",
    ]

    signals = []

    for query in trend_queries[:4]:  # Limit to keep costs manageable
        print(f"  Scanning trends: {query[:40]}...")

        try:
            raw = client.search_and_summarise(
                query=query,
                task_type="evaluate",
                system="""You are a venture capital market analyst tracking trends and regulatory changes.
Return ONLY a JSON array of signals. Each object:
{"type": "regulatory" | "competitive" | "model-update",
"summary": "2-3 sentence description", "vertical": "affected sector",
"thesis_implication": "what this means for our investment thesis"}
If nothing noteworthy, return: []""",
            )

            cleaned = raw.strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1
            if start >= 0 and end > start:
                trends = json.loads(cleaned[start:end])
            else:
                trends = []

            for t in trends:
                if isinstance(t, dict) and t.get("summary"):
                    sig_type = {
                        "regulatory": SignalType.REGULATORY,
                        "competitive": SignalType.COMPETITIVE,
                        "model-update": SignalType.MODEL_UPDATE,
                    }.get(t.get("type", ""), SignalType.COMPETITIVE)

                    sig = Signal(
                        type=sig_type,
                        source="web_search",
                        vertical=t.get("vertical", "general"),
                        summary=t.get("summary", ""),
                        thesis_implication=t.get("thesis_implication"),
                    )
                    signals.append(sig)
                    save_signal(sig.model_dump())

        except Exception as e:
            print(f"  [WARN] Trend scan failed: {e}")

    return signals


# --- Weekly Synthesis ---

def generate_synthesis(signals: list[Signal], config: dict) -> str:
    """Use Opus to synthesise a week's signals into thesis implications."""
    client = get_client()

    signals_text = "\n".join([
        f"- [{s.type.value}] {s.summary}" + (f" → Thesis: {s.thesis_implication}" if s.thesis_implication else "")
        for s in signals
    ])

    prompt = f"""Here are the market signals detected this week:

{signals_text}

THESIS CONTEXT:
{get_thesis_text(config)}

Write a 3-5 sentence synthesis of what these signals mean for the fund's investment thesis.
Focus on: opportunities opening, risks emerging, verticals heating up or cooling down,
and any signals that should change how we prioritise deal sourcing."""

    return client.complete(
        task_type="synthesise",
        system="You are a senior VC analyst writing a weekly market synthesis. Be concise and actionable.",
        prompt=prompt,
    )


# --- Main Runner ---

def run_radar(
    config: dict | None = None,
    weekly: bool = False,
    output_dir: str = "outputs/daily",
    dry_run: bool = False,
) -> RadarDigest:
    """Run the radar agent."""
    if config is None:
        config = load_config()

    init_db()

    print("\n" + "=" * 60)
    print("  RADAR AGENT — Market Intelligence")
    print("=" * 60)

    all_signals: list[Signal] = []

    if not dry_run:
        # Daily monitors
        print("\n[1/3] Scanning funding rounds...")
        funding_signals = scan_funding(config)
        all_signals.extend(funding_signals)
        print(f"  Found {len(funding_signals)} funding signals")

        print("\n[2/3] Scanning exits...")
        exit_signals = scan_exits(config)
        all_signals.extend(exit_signals)
        print(f"  Found {len(exit_signals)} exit signals")

        print("\n[3/3] Scanning trends & regulatory...")
        trend_signals = scan_trends(config)
        all_signals.extend(trend_signals)
        print(f"  Found {len(trend_signals)} trend signals")
    else:
        print("\n  [DRY RUN] Skipping signal collection")

    # Weekly synthesis
    synthesis = ""
    if weekly and all_signals and not dry_run:
        print("\n[Synthesis] Generating weekly market synthesis...")
        # Include signals from the past 7 days
        recent = get_recent_signals(days=7)
        recent_signals = all_signals  # Use current + DB
        synthesis = generate_synthesis(all_signals, config)
        print(f"  Synthesis generated ({len(synthesis)} chars)")

    digest = RadarDigest(
        week_of=datetime.utcnow().strftime("%Y-%m-%d"),
        signals=all_signals,
        thesis_implications=synthesis,
    )

    # Write output
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    prefix = "radar_weekly" if weekly else "radar"
    brief_file = output_path / f"{prefix}_{digest.week_of}.md"
    brief_file.write_text(format_radar_digest(digest, config))
    print(f"\n  Digest written to: {brief_file}")

    log_run("radar", raw_count=len(all_signals), output_path=str(brief_file))

    print(f"\n{'=' * 60}")
    print(f"  RADAR COMPLETE — {len(all_signals)} signals detected")
    print(f"{'=' * 60}\n")

    return digest


def format_radar_digest(digest: RadarDigest, config: dict) -> str:
    """Format radar output as markdown."""
    fund = config["thesis"].get("fund", "")
    lines = [
        f"# Radar Digest — {digest.week_of}",
        f"**Fund:** {fund}",
        "",
        "## Signal Summary",
        f"- **{len(digest.signals)}** total signals detected",
        f"- **{len([s for s in digest.signals if s.type == SignalType.FUNDING])}** funding rounds",
        f"- **{len([s for s in digest.signals if s.type == SignalType.EXIT])}** exits",
        f"- **{len([s for s in digest.signals if s.type == SignalType.REGULATORY])}** regulatory signals",
        f"- **{len([s for s in digest.signals if s.urgency == Urgency.ALERT])}** alerts",
        "",
    ]

    # Group by type
    for sig_type, label in [
        (SignalType.FUNDING, "Funding Rounds"),
        (SignalType.EXIT, "Exits & Shutdowns"),
        (SignalType.REGULATORY, "Regulatory & Policy"),
        (SignalType.COMPETITIVE, "Competitive Moves"),
        (SignalType.MODEL_UPDATE, "AI Model Updates"),
    ]:
        typed = [s for s in digest.signals if s.type == sig_type]
        if typed:
            lines.append(f"---\n\n### {label}\n")
            for s in typed:
                prefix = "🔴" if s.urgency == Urgency.ALERT else "🔵"
                lines.append(f"{prefix} **{s.company or s.vertical}**: {s.summary}")
                if s.thesis_implication:
                    lines.append(f"   → *Thesis implication: {s.thesis_implication}*")
                lines.append("")

    if digest.thesis_implications:
        lines.extend([
            "---\n",
            "## Weekly Thesis Synthesis\n",
            digest.thesis_implications,
            "",
        ])

    return "\n".join(lines)
