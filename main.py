#!/usr/bin/env python3
"""
thesis-radar — Autonomous deal intelligence for venture capital.

Four agents. One thesis. Daily briefs.

Usage:
    python main.py run --all              # Run all agents
    python main.py run --scout            # Run scout only
    python main.py run --radar            # Run radar only
    python main.py run --radar --weekly   # Run radar with weekly synthesis
    python main.py run --ops              # Run ops only
    python main.py run --events            # Run events only
    python main.py run --all --dry-run    # Dry run (no API calls)
    python main.py health                 # Show tracker health
    python main.py thesis                 # Display current thesis config
    python main.py history                # Show run history
"""

import sys
import argparse
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from shared.config_loader import load_config, get_thesis_text
from shared.db import init_db, get_all_seen, get_recent_signals


def cmd_run(args):
    """Run one or more agents."""
    config = load_config()

    run_scout = args.all or args.scout
    run_radar = args.all or args.radar
    run_ops = args.all or args.ops
    run_events = args.all or args.events

    if not (run_scout or run_radar or run_ops or run_events):
        print("Specify at least one agent: --all, --scout, --radar, --ops, or --events")
        return

    print(f"\n{'#' * 60}")
    print(f"  thesis-radar — {config['thesis'].get('fund', 'Deal Intelligence')}")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'#' * 60}")

    if run_scout:
        from agents.scout.scout import run_scout as execute_scout
        execute_scout(
            config=config,
            max_search_queries=args.max_queries,
            output_dir="outputs/daily",
            dry_run=args.dry_run,
        )

    if run_radar:
        from agents.radar.radar import run_radar as execute_radar
        execute_radar(
            config=config,
            weekly=args.weekly,
            output_dir="outputs/weekly" if args.weekly else "outputs/daily",
            dry_run=args.dry_run,
        )

    if run_ops:
        from agents.ops.ops import run_ops as execute_ops
        execute_ops(
            config=config,
            output_dir="outputs/weekly",
            dry_run=args.dry_run,
        )

    if run_events:
        from agents.events.events import run_events as execute_events
        execute_events(
            config=config,
            output_dir="outputs/weekly",
            dry_run=args.dry_run,
        )

    print(f"\n{'#' * 60}")
    print(f"  All runs complete. Check outputs/ for briefs.")
    print(f"{'#' * 60}\n")


def cmd_health(args):
    """Display tracker health summary."""
    init_db()
    tracked = get_all_seen(action_filter="track")
    watched = get_all_seen(action_filter="watch")
    skipped = get_all_seen(action_filter="skip")
    signals = get_recent_signals(days=7)

    print(f"\n  Tracker Health")
    print(f"  {'=' * 40}")
    print(f"  Tracked:  {len(tracked)}")
    print(f"  Watching: {len(watched)}")
    print(f"  Skipped:  {len(skipped)}")
    print(f"  Signals (7d): {len(signals)}")

    if tracked:
        print(f"\n  Top tracked companies:")
        for t in sorted(tracked, key=lambda x: x.get("composite_score") or 0, reverse=True)[:10]:
            score = t.get("composite_score", "?")
            print(f"    {score:>5} — {t['name']}")

    print()


def cmd_thesis(args):
    """Display the current thesis configuration."""
    config = load_config()
    print(f"\n{get_thesis_text(config)}\n")


def cmd_history(args):
    """Show recent run history."""
    init_db()
    from shared.db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM run_history ORDER BY started_at DESC LIMIT 20"
    ).fetchall()
    conn.close()

    if not rows:
        print("\n  No run history yet. Run an agent first.\n")
        return

    print(f"\n  Run History (last 20)")
    print(f"  {'=' * 60}")
    for r in rows:
        print(f"  {r['started_at'][:16]} | {r['agent']:6s} | raw:{r['raw_count']:3d} passed:{r['passed_count']:3d} | {r['status']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="thesis-radar — Autonomous deal intelligence for VC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run agents")
    run_parser.add_argument("--all", action="store_true", help="Run all agents")
    run_parser.add_argument("--scout", action="store_true", help="Run scout agent")
    run_parser.add_argument("--radar", action="store_true", help="Run radar agent")
    run_parser.add_argument("--ops", action="store_true", help="Run ops agent")
    run_parser.add_argument("--events", action="store_true", help="Run the events agent (outbound triggers)")
    run_parser.add_argument("--weekly", action="store_true", help="Include weekly synthesis (radar)")
    run_parser.add_argument("--dry-run", action="store_true", help="Skip API calls")
    run_parser.add_argument("--max-queries", type=int, default=10, help="Max search queries for scout")
    run_parser.set_defaults(func=cmd_run)

    # Health command
    health_parser = subparsers.add_parser("health", help="Show tracker health")
    health_parser.set_defaults(func=cmd_health)

    # Thesis command
    thesis_parser = subparsers.add_parser("thesis", help="Display thesis config")
    thesis_parser.set_defaults(func=cmd_thesis)

    # History command
    history_parser = subparsers.add_parser("history", help="Show run history")
    history_parser.set_defaults(func=cmd_history)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
