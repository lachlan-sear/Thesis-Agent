#!/usr/bin/env python3
"""
thesis-agent — a deal-intelligence engine any fund can point at its own thesis.

Usage:
    python main.py weekly                 # The scheduled run: refresh, scout, radar, ops, events, publish
    python main.py run --refresh          # Check every tracked company for rounds, exits, shutdowns
    python main.py run --scout            # Source new companies against the thesis
    python main.py run --radar [--weekly] # Market signals (and weekly synthesis)
    python main.py run --ops              # Tracker staleness and cross-references
    python main.py run --events           # Upcoming outbound triggers
    python main.py run --all --dry-run    # Everything, no API calls
    python main.py publish                # Rebuild data/observatory.json for the Observatory
    python main.py check                  # Validate thesis.yaml and the tracker
    python main.py thesis                 # Print the thesis as the agents see it
    python main.py health                 # Tracker freshness summary
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # .env support is optional; Actions passes secrets as env vars
    pass

from shared.config_loader import get_thesis_text, load_config, sector_map


def _banner(config):
    print(f"\n{'#' * 60}\n  thesis-agent — {config['thesis'].get('name', '')}"
          f"\n  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n{'#' * 60}")


def cmd_run(args):
    config = load_config()
    picks = {k: args.all or getattr(args, k) for k in ("refresh", "scout", "radar", "ops", "events")}
    if not any(picks.values()):
        print("Specify at least one agent: --all, --refresh, --scout, --radar, --ops or --events")
        return
    _banner(config)
    if picks["refresh"]:
        from agents.refresh.refresh import run_refresh
        run_refresh(config=config, dry_run=args.dry_run, limit=args.limit)
    if picks["scout"]:
        from agents.scout.scout import run_scout
        run_scout(config=config, max_search_queries=args.max_queries,
                  output_dir="outputs/weekly", dry_run=args.dry_run)
    if picks["radar"]:
        from agents.radar.radar import run_radar
        run_radar(config=config, weekly=args.weekly, output_dir="outputs/weekly", dry_run=args.dry_run)
    if picks["ops"]:
        from agents.ops.ops import run_ops
        run_ops(config=config, output_dir="outputs/weekly", dry_run=args.dry_run)
    if picks["events"]:
        from agents.events.events import run_events
        run_events(config=config, output_dir="outputs/weekly", dry_run=args.dry_run)


def cmd_weekly(args):
    """The scheduled pipeline. Each stage is isolated so one failure doesn't lose the rest."""
    config = load_config()
    _banner(config)
    from agents.refresh.refresh import run_refresh
    stages = [("refresh", lambda: run_refresh(config=config, dry_run=args.dry_run))]
    if not args.refresh_only:
        from agents.scout.scout import run_scout
        from agents.radar.radar import run_radar
        from agents.ops.ops import run_ops
        from agents.events.events import run_events
        stages += [
            ("scout", lambda: run_scout(config=config, max_search_queries=args.max_queries,
                                        output_dir="outputs/weekly", dry_run=args.dry_run)),
            ("radar", lambda: run_radar(config=config, weekly=True, output_dir="outputs/weekly", dry_run=args.dry_run)),
            ("ops", lambda: run_ops(config=config, output_dir="outputs/weekly", dry_run=args.dry_run)),
            ("events", lambda: run_events(config=config, output_dir="outputs/weekly", dry_run=args.dry_run)),
        ]
    failed = []
    for name, fn in stages:
        try:
            fn()
        except Exception as e:
            failed.append(name)
            print(f"\n  [ERROR] {name} failed: {e}\n")
    if not args.dry_run:
        from shared.publish import build
        out = build(config)
        print(f"  Published edition {out['edition']['number'] if out['edition'] else '-'} → data/observatory.json")
    if "refresh" in failed:
        sys.exit(1)  # the tracker is the product; a failed refresh should show red in Actions


def cmd_publish(args):
    from shared.publish import build
    out = build()
    print(f"  data/observatory.json: {len(out['companies'])} companies, edition {out['edition'] and out['edition']['number']}")


def cmd_check(args):
    """Validate the thesis and tracker; exits non-zero on any problem (used in CI)."""
    from shared import tracker
    config = load_config()
    problems = []
    t = config.get("thesis", {})
    sectors = sector_map(config)
    if not sectors:
        problems.append("thesis.sectors is empty")
    weights = t.get("evaluation_weights") or {}
    if weights and abs(sum(weights.values()) - 1.0) > 0.01:
        problems.append(f"evaluation_weights sum to {sum(weights.values()):.2f}, not 1.0")
    if weights and set(weights) - set(t.get("evaluation_rubric", {})):
        problems.append(f"weights without a rubric entry: {sorted(set(weights) - set(t.get('evaluation_rubric', {})))}")
    problems += tracker.validate(tracker.load(), set(sectors))
    if problems:
        print("  Problems:\n  - " + "\n  - ".join(problems))
        sys.exit(1)
    print(f"  OK: {len(sectors)} sectors, {len(tracker.load())} companies, rubric of {len(t.get('evaluation_rubric', {}))}")


def cmd_thesis(args):
    print(f"\n{get_thesis_text(load_config())}\n")


def cmd_health(args):
    from shared import tracker
    rows = tracker.load()
    pending = [c for c in rows if c.get("verifiedBy") == "pending"]
    stale = [c for c in rows if (tracker.days_since(c.get("lastVerified")) or 999) > 30
             and c.get("status") not in ("exited", "shut_down")]
    print(f"\n  Tracker: {len(rows)} companies | {len(pending)} awaiting first check | {len(stale)} not checked in 30 days")
    for c in stale[:15]:
        print(f"    {c['name']:<24} last checked {c.get('lastVerified') or 'never'}")
    print()


def main():
    parser = argparse.ArgumentParser(description="thesis-agent", formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__)
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run individual agents")
    for flag in ("all", "refresh", "scout", "radar", "ops", "events", "weekly", "dry_run"):
        run.add_argument(f"--{flag.replace('_', '-')}", action="store_true")
    run.add_argument("--max-queries", type=int, default=24)
    run.add_argument("--limit", type=int, default=None, help="Max companies for --refresh")
    run.set_defaults(func=cmd_run)

    weekly = sub.add_parser("weekly", help="The scheduled weekly pipeline")
    weekly.add_argument("--dry-run", action="store_true")
    weekly.add_argument("--refresh-only", action="store_true")
    weekly.add_argument("--max-queries", type=int, default=24)
    weekly.set_defaults(func=cmd_weekly)

    for name, fn in (("publish", cmd_publish), ("check", cmd_check), ("thesis", cmd_thesis), ("health", cmd_health)):
        sub.add_parser(name).set_defaults(func=fn)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
