"""
The tracker: data/companies.json is the single source of truth.

Every agent reads it, the weekly refresh writes it, and publish turns it into
data/observatory.json for the Observatory. Only public fields live here: no
contacts, no private notes, nothing a reader of the published page shouldn't see.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TRACKER_PATH = DATA / "companies.json"

STATUSES = {"tracking", "leader", "written_up", "exited", "shut_down"}
FIELDS = [
    "id", "name", "aliases", "website", "sector", "description", "geo", "founded", "stage",
    "raised", "raisedUsdM", "raisedBasis", "investors", "lastRound", "exit", "status", "writeUp",
    "note", "dateAdded", "lastVerified", "verifiedBy", "confidence", "sources",
]


def load(path: Path | None = None) -> list[dict]:
    path = path or TRACKER_PATH
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(companies: list[dict], path: Path | None = None) -> None:
    path = path or TRACKER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [{k: c.get(k) for k in FIELDS} for c in companies]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
        f.write("\n")


def validate(companies: list[dict], sector_ids: set[str]) -> list[str]:
    """Return a list of problems; empty means the tracker is consistent."""
    problems, seen_ids, seen_names = [], set(), set()
    for c in companies:
        tag = c.get("name") or f"id {c.get('id')}"
        if c.get("id") in seen_ids:
            problems.append(f"{tag}: duplicate id")
        seen_ids.add(c.get("id"))
        key = (c.get("name") or "").lower()
        if key in seen_names:
            problems.append(f"{tag}: duplicate name")
        seen_names.add(key)
        if c.get("sector") not in sector_ids:
            problems.append(f"{tag}: sector '{c.get('sector')}' is not in thesis.yaml")
        if c.get("status") not in STATUSES:
            problems.append(f"{tag}: unknown status '{c.get('status')}'")
        if c.get("status") == "exited" and not (c.get("exit") or {}).get("source"):
            problems.append(f"{tag}: exited without a sourced exit record")
        lr = c.get("lastRound")
        if lr and not lr.get("source"):
            problems.append(f"{tag}: last round has no source")
        if c.get("raisedBasis") not in (None, "total", "latest_round", "estimate"):
            problems.append(f"{tag}: raisedBasis must be total, latest_round or estimate")
        if c.get("verifiedBy") != "pending" and not c.get("sources"):
            problems.append(f"{tag}: marked verified but lists no sources")
    return problems


def by_name(companies: list[dict]) -> dict[str, dict]:
    return {c["name"].lower(): c for c in companies}


def days_since(iso: str | None, today: date | None = None) -> int | None:
    if not iso:
        return None
    today = today or date.today()
    try:
        return (today - datetime.fromisoformat(iso[:10]).date()).days
    except ValueError:
        return None


def refresh_order(companies: list[dict], today: date | None = None) -> list[dict]:
    """Pending first, then stalest first. Exited and shut-down companies are not refreshed."""
    live = [c for c in companies if c.get("status") not in ("exited", "shut_down")]

    def key(c):
        d = days_since(c.get("lastVerified"), today)
        return (0 if d is None else 1, -(d or 0))
    return sorted(live, key=key)


def next_id(companies: list[dict]) -> int:
    return max((c.get("id") or 0 for c in companies), default=0) + 1
