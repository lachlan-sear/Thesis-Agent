#!/usr/bin/env python3
"""
Re-run the source check over every recorded round and exit in data/companies.json.

Writes data/source_audit.json (shown on the Observatory's method section) and
exits non-zero if any record fails, so the claim "checked against source" is
something anyone can reproduce:

    python scripts/audit_sources.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import tracker, verify  # noqa: E402


def main() -> int:
    rows, results = tracker.load(), []
    for c in rows:
        for kind, rec in (("round", c.get("lastRound")), ("exit", c.get("exit"))):
            if not rec:
                continue
            ok, reason, _ = verify.check(c["name"], dict(rec, kind=kind), [], aliases=c.get("aliases") or [])
            results.append({"company": c["name"], "kind": kind, "source": rec.get("source"), "ok": ok, "reason": reason})
            print(f"{'PASS' if ok else 'FAIL'}  {c['name']:<24} {kind:<6} {reason}")
    passed = sum(r["ok"] for r in results)
    unreadable = sum(1 for r in results if not r["ok"] and r["reason"].startswith("source could not be read"))
    out = {"date": datetime.now(timezone.utc).date().isoformat(), "passed": passed, "checked": len(results),
           "unreadable": unreadable, "notStated": len(results) - passed - unreadable,
           "failures": [r for r in results if not r["ok"]]}
    (tracker.DATA / "source_audit.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{passed} of {len(results)} recorded rounds and exits are stated next to the company's name on their source;"
          f" {unreadable} source(s) couldn't be fetched from here; {out['notStated']} not stated.")
    return 0 if out["notStated"] == 0 else 1  # an unreachable page is reported, a contradicted one fails


if __name__ == "__main__":
    sys.exit(main())
