"""
Events Agent — Outbound Trigger Intelligence.

Monitors industry conferences, regulatory hearings, product launches,
and earnings calls to surface time-sensitive outbound triggers.

The other agents answer "what exists?" and "what changed?"
This agent answers "what's happening this week that gives me a reason to call?"

Runs: Weekly (Monday morning, before the Scout brief)
Output: Events digest with actionable outbound triggers
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from shared.claude_client import get_client
from shared.config_loader import load_config, get_thesis_text
from shared.db import init_db, log_run


def scan_conferences(config: dict) -> list[dict]:
    """Search for upcoming conferences, summits, and demo days relevant to thesis verticals."""
    client = get_client()
    thesis = config["thesis"]
    verticals = thesis.get("target_verticals", {}).get("primary", [])
    signals = []

    # Build conference search queries from verticals
    conference_queries = []
    for vertical in verticals[:6]:  # Cap to control costs
        conference_queries.append(f"{vertical} conference summit 2026 Europe UK speakers")
        conference_queries.append(f"{vertical} startup demo day pitch event 2026")

    # Also search for major known events
    major_events = [
        "London Tech Week 2026 speakers agenda",
        "SaaStr EMEA 2026 speakers startups",
        "Web Summit 2026 startup speakers",
        "Slush 2026 speakers finalists",
        "TechCrunch Disrupt 2026 Europe startups",
        "Sifted Summit 2026 speakers",
    ]
    conference_queries.extend(major_events)

    # Add thesis-specific event queries from config
    event_queries = thesis.get("events_monitoring", {}).get("queries", [])
    conference_queries.extend(event_queries)

    print(f"  Scanning {len(conference_queries)} conference queries...")

    for query in conference_queries:
        try:
            raw = client.search_and_summarise(
                query=query,
                task_type="audit",  # Use Sonnet for cost efficiency
                system="""You are scanning for upcoming industry events relevant to a VC fund.
For each event you find, extract:
1. Event name and date
2. Location
3. Notable speakers or presenting startups
4. Why this matters for deal sourcing (which speakers are founders of early-stage companies?)

Focus on events happening in the NEXT 30 DAYS. Ignore past events.
Look for: startup founders speaking on panels, demo days, pitch competitions,
regulatory hearings with published agendas, product launch events.

Return a JSON array of events. Each object:
{"event": "name", "date": "YYYY-MM-DD or approximate", "location": "city",
 "speakers_or_startups": ["name1", "name2"],
 "outbound_trigger": "why this creates a reason to reach out",
 "vertical": "which thesis vertical this maps to",
 "urgency": "high" | "medium" | "low"}

If nothing relevant found, return: []""",
                prompt_template=query,
            )

            # Parse JSON from response
            cleaned = raw.strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1
            if start >= 0 and end > start:
                events = json.loads(cleaned[start:end])
                for event in events:
                    if isinstance(event, dict) and event.get("event"):
                        signals.append(event)
        except Exception as e:
            print(f"  [WARN] Conference scan failed for query: {e}")

    return signals


def scan_regulatory_hearings(config: dict) -> list[dict]:
    """Search for upcoming regulatory hearings, consultations, and rule changes."""
    client = get_client()
    thesis = config["thesis"]
    signals = []

    # Use regulatory monitoring queries from thesis config
    reg_queries = thesis.get("regulatory_monitoring", {}).get("queries", [])

    # Add generic regulatory hearing queries
    reg_queries.extend([
        "upcoming regulatory consultation UK FCA 2026",
        "EU regulation hearing digital markets 2026",
        "CMA investigation update UK 2026",
        "regulatory deadline compliance technology 2026",
    ])

    print(f"  Scanning {len(reg_queries)} regulatory queries...")

    for query in reg_queries:
        try:
            raw = client.search_and_summarise(
                query=query,
                task_type="audit",
                system="""You are scanning for upcoming regulatory events relevant to a VC fund.
Look for: regulatory hearings with published dates, consultation deadlines,
new rules coming into force, compliance deadlines that create urgency for startups.

For each event, extract:
1. What regulation or hearing
2. Date or deadline
3. Which companies or sectors are affected
4. The outbound trigger — how does this create a reason to call a founder?

Return a JSON array. Each object:
{"event": "regulation/hearing name", "date": "YYYY-MM-DD or approximate",
 "affected_sectors": ["sector1", "sector2"],
 "outbound_trigger": "why this creates urgency for outbound",
 "vertical": "thesis vertical",
 "urgency": "high" | "medium" | "low"}

If nothing relevant, return: []""",
                prompt_template=query,
            )

            cleaned = raw.strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1
            if start >= 0 and end > start:
                events = json.loads(cleaned[start:end])
                for event in events:
                    if isinstance(event, dict) and event.get("event"):
                        event["type"] = "regulatory"
                        signals.append(event)
        except Exception as e:
            print(f"  [WARN] Regulatory scan failed: {e}")

    return signals


def scan_product_launches(config: dict) -> list[dict]:
    """Search for upcoming product launches and announcements in thesis verticals."""
    client = get_client()
    thesis = config["thesis"]
    verticals = thesis.get("target_verticals", {}).get("primary", [])
    signals = []

    queries = []
    for vertical in verticals[:4]:
        queries.append(f"{vertical} startup product launch announcement 2026")
        queries.append(f"{vertical} startup beta launch waitlist 2026")

    print(f"  Scanning {len(queries)} product launch queries...")

    for query in queries:
        try:
            raw = client.search_and_summarise(
                query=query,
                task_type="audit",
                system="""You are scanning for upcoming or very recent product launches by startups.
Look for: beta launches, waitlist openings, Product Hunt launches planned,
major feature announcements, pivot announcements.

A product launch is a perfect outbound trigger — the founder is in "tell the world" mode
and more receptive to investor conversations.

Return a JSON array. Each object:
{"company": "name", "launch": "what they launched or are about to launch",
 "date": "YYYY-MM-DD or approximate",
 "outbound_trigger": "why this is the right moment to reach out",
 "vertical": "thesis vertical",
 "urgency": "high" | "medium" | "low"}

If nothing relevant, return: []""",
                prompt_template=query,
            )

            cleaned = raw.strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]") + 1
            if start >= 0 and end > start:
                events = json.loads(cleaned[start:end])
                for event in events:
                    if isinstance(event, dict):
                        event["type"] = "product_launch"
                        signals.append(event)
        except Exception as e:
            print(f"  [WARN] Product launch scan failed: {e}")

    return signals


def deduplicate_events(events: list[dict]) -> list[dict]:
    """Remove duplicate events based on name similarity."""
    seen = set()
    unique = []
    for event in events:
        key = (event.get("event", "") or event.get("company", "")).lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(event)
    return unique


def format_events_digest(
    conferences: list[dict],
    regulatory: list[dict],
    launches: list[dict],
    config: dict,
) -> str:
    """Format all events into a markdown digest."""
    lines = [
        f"# Events Digest — {datetime.utcnow().strftime('%Y-%m-%d')}",
        f"**Thesis:** {config['thesis'].get('name', 'N/A')}",
        "",
        "## Signal Summary",
        f"- **{len(conferences)}** conference/event triggers",
        f"- **{len(regulatory)}** regulatory triggers",
        f"- **{len(launches)}** product launch triggers",
        f"- **{len(conferences) + len(regulatory) + len(launches)}** total outbound triggers",
        "",
        "---",
        "",
    ]

    if conferences:
        lines.append("### Conferences & Events\n")
        for evt in sorted(conferences, key=lambda x: x.get("urgency", "low") == "high", reverse=True):
            urgency_icon = "🔴" if evt.get("urgency") == "high" else "🟡" if evt.get("urgency") == "medium" else "🔵"
            lines.append(f"{urgency_icon} **{evt.get('event', 'Unknown')}**")
            if evt.get("date"):
                lines.append(f"   Date: {evt['date']}")
            if evt.get("location"):
                lines.append(f"   Location: {evt['location']}")
            if evt.get("speakers_or_startups"):
                speakers = ", ".join(evt["speakers_or_startups"][:5])
                lines.append(f"   Notable: {speakers}")
            if evt.get("outbound_trigger"):
                lines.append(f"   → *Outbound trigger: {evt['outbound_trigger']}*")
            lines.append("")

    if regulatory:
        lines.append("### Regulatory Triggers\n")
        for evt in sorted(regulatory, key=lambda x: x.get("urgency", "low") == "high", reverse=True):
            urgency_icon = "🔴" if evt.get("urgency") == "high" else "🟡" if evt.get("urgency") == "medium" else "🔵"
            lines.append(f"{urgency_icon} **{evt.get('event', 'Unknown')}**")
            if evt.get("date"):
                lines.append(f"   Deadline: {evt['date']}")
            if evt.get("affected_sectors"):
                sectors = ", ".join(evt["affected_sectors"][:3])
                lines.append(f"   Affected: {sectors}")
            if evt.get("outbound_trigger"):
                lines.append(f"   → *Outbound trigger: {evt['outbound_trigger']}*")
            lines.append("")

    if launches:
        lines.append("### Product Launches\n")
        for evt in sorted(launches, key=lambda x: x.get("urgency", "low") == "high", reverse=True):
            urgency_icon = "🔴" if evt.get("urgency") == "high" else "🟡" if evt.get("urgency") == "medium" else "🔵"
            company = evt.get("company", "Unknown")
            launch = evt.get("launch", "")
            lines.append(f"{urgency_icon} **{company}**: {launch}")
            if evt.get("outbound_trigger"):
                lines.append(f"   → *Outbound trigger: {evt['outbound_trigger']}*")
            lines.append("")

    if not conferences and not regulatory and not launches:
        lines.append("*No outbound triggers detected this week.*\n")

    lines.extend([
        "---",
        f"*Generated by [thesis-agent](https://github.com/lachlan-sear/thesis-agent) on {datetime.utcnow().strftime('%Y-%m-%d')}.*",
    ])

    return "\n".join(lines)


def run_events(
    config: dict = None,
    output_dir: str = "outputs/weekly",
    dry_run: bool = False,
) -> dict:
    """Run the events agent."""
    if config is None:
        config = load_config()

    init_db()

    print("\n" + "=" * 60)
    print("  EVENTS AGENT — Outbound Trigger Intelligence")
    print("=" * 60)

    conferences = []
    regulatory = []
    launches = []

    if not dry_run:
        print("\n[1/3] Scanning conferences and events...")
        conferences = scan_conferences(config)
        conferences = deduplicate_events(conferences)
        print(f"  Found {len(conferences)} conference triggers")

        print("\n[2/3] Scanning regulatory hearings...")
        regulatory = scan_regulatory_hearings(config)
        regulatory = deduplicate_events(regulatory)
        print(f"  Found {len(regulatory)} regulatory triggers")

        print("\n[3/3] Scanning product launches...")
        launches = scan_product_launches(config)
        launches = deduplicate_events(launches)
        print(f"  Found {len(launches)} product launch triggers")
    else:
        print("\n  [DRY RUN] Skipping event collection")

    total = len(conferences) + len(regulatory) + len(launches)

    # Write output
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    digest = format_events_digest(conferences, regulatory, launches, config)
    brief_file = output_path / f"events_{datetime.utcnow().strftime('%Y-%m-%d')}.md"
    brief_file.write_text(digest, encoding="utf-8")
    print(f"\n  Digest written to: {brief_file}")

    log_run("events", raw_count=total, output_path=str(brief_file))

    print(f"\n{'=' * 60}")
    print(f"  EVENTS COMPLETE — {total} outbound triggers detected")
    print(f"  Conferences: {len(conferences)} | Regulatory: {len(regulatory)} | Launches: {len(launches)}")
    print(f"{'=' * 60}\n")

    return {
        "conferences": conferences,
        "regulatory": regulatory,
        "launches": launches,
    }
