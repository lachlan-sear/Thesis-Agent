"""
Publish: turn the tracker and the latest run into data/observatory.json.

The Observatory (a separate Next.js app) fetches that one file, so a fund that
forks this repo gets its own map by pointing the Observatory at its own copy.
Each run also writes a dated edition to data/editions/, which is the archive
the Observatory lists as "Editions".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from shared import tracker
from shared.config_loader import exclusions, load_config

DATA = tracker.DATA
LAST_RUN = DATA / "last_run.json"
EDITIONS = DATA / "editions"
OUT = DATA / "observatory.json"
CANDIDATES = DATA / "candidates.json"
REVIEW = DATA / "review.json"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_edition(run: dict) -> dict:
    """Write data/editions/<date>.json for this run (idempotent per date)."""
    EDITIONS.mkdir(parents=True, exist_ok=True)
    existing = sorted(EDITIONS.glob("*.json"))
    path = EDITIONS / f"{run['date']}.json"
    number = next((json.loads(p.read_text())["number"] for p in existing if p.name == path.name),
                  len(existing) + 1)
    edition = {
        "number": number,
        "date": run["date"],
        "kind": run.get("kind", "weekly"),
        "checked": run.get("checked", 0),
        "applied": len(run.get("applied", [])),
        "held": run.get("held", 0),
        "changes": run.get("applied", []),
        "note": run.get("note", ""),
    }
    path.write_text(json.dumps(edition, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return edition


def build(config: dict | None = None) -> dict:
    config = config or load_config()
    thesis = config["thesis"]
    hidden = exclusions(config)
    run = _read(LAST_RUN, None)
    edition = write_edition(run) if run else None

    companies = [c for c in tracker.load() if c["name"].lower() not in hidden]
    editions = []
    for p in sorted(EDITIONS.glob("*.json"), reverse=True):
        e = _read(p, None)
        if e:
            editions.append({k: e[k] for k in ("number", "date", "kind", "checked", "applied", "held")} |
                            {"headlines": [c["headline"] for c in e.get("changes", [])][:4]})
    latest = edition or (_read(sorted(EDITIONS.glob("*.json"))[-1], None) if list(EDITIONS.glob("*.json")) else None)

    candidates = [c for c in _read(CANDIDATES, []) if c["name"].lower() not in hidden]
    if candidates:
        newest = candidates[0]["date"]
        candidates = [c for c in candidates if c["date"] == newest]

    out = {
        "schema": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thesis": {
            "fund": thesis.get("fund", ""),
            "name": thesis.get("name", ""),
            "coreBelief": " ".join((thesis.get("core_belief") or "").split()),
            "updated": thesis.get("updated", ""),
            "stage": thesis.get("stage_focus", {}).get("sweet_spot", ""),
            "geography": thesis.get("geography", {}),
            "sectors": [{k: s.get(k) for k in ("id", "name", "short", "description", "color")}
                        | {"description": " ".join((s.get("description") or "").split())}
                        for s in thesis.get("sectors", [])],
            "lenses": [f["name"] for f in thesis.get("frameworks", [])],
        },
        "edition": latest and {k: latest[k] for k in ("number", "date", "kind", "checked", "applied", "held", "note") if k in latest},
        "changes": (latest or {}).get("changes", []),
        "editions": editions,
        "companies": companies,
        "candidates": candidates,
        "heldForReview": len(_read(REVIEW, [])),
        "method": {
            "schedule": config.get("scheduling", {}).get("weekly", "Weekly"),
            "requireSourceMatch": config.get("refresh", {}).get("require_source_match", True),
            "excludedCount": len(hidden),
        },
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
