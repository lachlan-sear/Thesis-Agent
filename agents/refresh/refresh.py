"""
Refresh agent — keeps the tracker true, every week.

For each tracked company (pending first, then stalest), Claude searches the
web for anything new since the company was last checked: a round, an exit, a
shutdown. Each finding must cite the page that states it. shared/verify.py then
reads that page; a change is applied only if the page names the company and
the amount (or the acquirer). Everything else is held in data/review.json for
a human, with the reason. Nothing is applied on the model's word alone.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from shared import tracker, verify
from shared.config_loader import load_config, sector_map

REVIEW_PATH = tracker.DATA / "review.json"
STAGES = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Growth"]

SYSTEM = """You are a venture analyst keeping a deal tracker accurate.
You check one company for material events since a given date and report only
what a source you opened actually states. Never infer, estimate or round.
If you find nothing new, say so. Return ONLY JSON."""

PROMPT = """Company: {name}
Website: {website}
What it does: {description}
Based in: {geo}
Tracker currently says: stage {stage}; raised {raised}; last round {last_round}.
Check for events after {since}.

Search the web, then return JSON:
{{
  "changes": [
    {{"kind": "round", "round": "Series A", "amount": "$50M", "date": "YYYY-MM",
      "leads": "lead investor(s)", "valuation": "post-money if reported, else empty",
      "total_raised": "total raised if the same source states it, else empty",
      "source": "URL of the page that states this round"}},
    {{"kind": "exit", "acquirer": "who", "type": "acquisition|ipo", "date": "YYYY-MM",
      "value": "if disclosed, else 'Not disclosed'", "state": "announced|completed",
      "source": "URL of the page that states it"}},
    {{"kind": "shutdown", "date": "YYYY-MM", "source": "URL"}}
  ],
  {baseline_block}
  "summary": "one plain sentence on what changed, or 'No change found'"
}}
Rules: include a change only if it happened after {since} and the cited page states it.
Amounts keep their original currency and are written like $50M, €32M, £4.5M, $1.2B.
An empty "changes" list is a good answer when nothing happened."""

BASELINE = """"baseline": {"stage": "latest round name", "raised": "total raised, e.g. $40M",
    "investors": ["notable investors"], "source": "URL that states the total"},"""


def _since(c: dict) -> str:
    return (c.get("lastVerified") or (c.get("lastRound") or {}).get("date") or "2026-01-01")[:10]


def _already_known(company: dict, change: dict) -> bool:
    """The round we already hold (same amount and month). Undated or unparsed rounds are never 'known'."""
    lr = company.get("lastRound") or {}
    a, b = verify.parse_amount(lr.get("amount")), verify.parse_amount(change.get("amount"))
    return bool(a and b and a == b and lr.get("date") and change.get("date")
                and lr["date"][:7] == change["date"][:7])


def _older_than_last_round(company: dict, change: dict) -> bool:
    lr = (company.get("lastRound") or {}).get("date")
    return bool(lr and change.get("date") and change["date"][:7] < lr[:7])


def _stage_from_round(name: str | None, current: str | None) -> str | None:
    if not name:
        return current
    for s in STAGES:
        if s.lower() == name.strip().lower():
            return s
    return current


def _usd_m(amount: str | None) -> float | None:
    p = verify.parse_amount(amount)
    if not p:
        return None
    cur, val = p
    rate = {"USD": 1.0, "GBP": 1.27, "EUR": 1.08, "CHF": 1.1, "SEK": 0.095}.get(cur)
    return round(val * rate, 1) if rate else None


def research(client, company: dict) -> tuple[dict, list[dict]]:
    pending = company.get("verifiedBy") == "pending"
    lr = company.get("lastRound") or {}
    prompt = PROMPT.format(
        name=company["name"], website=company.get("website") or "unknown",
        description=company.get("description", ""), geo=company.get("geo") or "unknown",
        stage=company.get("stage") or "unknown", raised=company.get("raised") or "unknown",
        last_round=f"{lr.get('round', '')} {lr.get('amount', '')} {lr.get('date', '')}".strip() or "unknown",
        since=_since(company), baseline_block=BASELINE if pending else "",
    )
    text, citations = client.search(prompt, task_type="refresh", system=SYSTEM)
    from shared.claude_client import _extract_json
    try:
        result = _extract_json(text)
    except Exception:
        result = None  # an unreadable answer is not a check
    return result, citations


def apply(company: dict, change: dict, today: str) -> dict:
    """Mutate the company with an accepted change; return the edition entry."""
    kind = change["kind"]
    src = change.get("source")
    company.setdefault("sources", [])
    if src and src not in company["sources"]:
        company["sources"].insert(0, src)
    if kind == "round":
        company["lastRound"] = {k: change.get(k, "") for k in ("round", "amount", "date", "leads", "valuation")}
        company["lastRound"]["source"] = src
        company["stage"] = _stage_from_round(change.get("round"), company.get("stage"))
        if change.get("total_raised_verified"):
            company["raised"] = change["total_raised"]
            company["raisedUsdM"] = _usd_m(change["total_raised"])
            company["raisedBasis"] = "total"
        elif company.get("raisedBasis") == "latest_round" or not company.get("raised"):
            # we only ever knew the latest round, so the new round replaces it
            company["raised"] = change.get("amount") or company.get("raised")
            company["raisedUsdM"] = _usd_m(change.get("amount")) or company.get("raisedUsdM")
            company["raisedBasis"] = "latest_round"
        # otherwise a sourced total stands until a source states the new total
        lead = f", led by {change['leads']}" if change.get("leads") else ""
        val = f" at {change['valuation']}" if change.get("valuation") else ""
        headline = f"{company['name']} raised {change.get('amount') or 'an undisclosed amount'} ({change.get('round') or 'round'}){val}{lead}"
    elif kind == "exit":
        company["status"] = "exited"
        company["stage"] = "Public" if change.get("type") == "ipo" else "Acquired"
        company["exit"] = {k: change.get(k, "") for k in ("type", "acquirer", "date", "value", "state")}
        company["exit"]["source"] = src
        verb = "listed" if change.get("type") == "ipo" else f"agreed to be acquired by {change.get('acquirer')}"
        headline = f"{company['name']} {verb}"
    elif kind == "shutdown":
        company["status"] = "shut_down"
        headline = f"{company['name']} shut down"
    else:  # baseline
        company["stage"] = change.get("stage") or company.get("stage")
        company["raised"] = change.get("raised")
        company["raisedUsdM"] = _usd_m(change.get("raised"))
        company["raisedBasis"] = "total"
        if change.get("investors"):
            company["investors"] = change["investors"][:8]
        headline = f"{company['name']}: first verified figures ({company['raised']} raised)"
    company["note"] = headline + "."  # former names live in `aliases`, so nothing is lost here
    return {"company": company["name"], "sector": company.get("sector"), "kind": kind,
            "headline": headline, "date": change.get("date") or today, "source": src}


def run_refresh(config: dict | None = None, client=None, dry_run: bool = False,
                limit: int | None = None, fetch=verify.fetch_text, today: date | None = None) -> dict:
    config = config or load_config()
    today = today or datetime.now(timezone.utc).date()
    today_s = today.isoformat()
    rcfg = config.get("refresh", {})
    limit = limit or rcfg.get("max_companies", 60)
    companies = tracker.load()
    sectors = sector_map(config)
    problems = tracker.validate(companies, set(sectors))
    if problems:
        raise SystemExit("Tracker is inconsistent:\n  " + "\n  ".join(problems))

    print("\n" + "=" * 60 + "\n  REFRESH AGENT — keeping the tracker true\n" + "=" * 60)
    queue = tracker.refresh_order(companies, today)[:limit]
    accepted, held, checked = [], [], 0

    if dry_run:
        print(f"  [DRY RUN] would check {len(queue)} companies; no API calls")
    else:
        if client is None:
            from shared.claude_client import get_client
            client = get_client()
        for c in queue:
            checked += 1
            print(f"  Checking {c['name']} (since {_since(c)})...")
            try:
                result, citations = research(client, c)
            except Exception as e:  # network or API trouble: leave the record as it was
                print(f"    [WARN] {e}")
                continue
            if result is None:
                print("    [WARN] unreadable answer; record left as it was")
                continue
            proposals = [dict(ch) for ch in result.get("changes") or [] if ch.get("kind") in ("round", "exit", "shutdown")]
            if result.get("baseline") and c.get("verifiedBy") == "pending":
                proposals.append(dict(result["baseline"], kind="baseline"))
            ok_any = False
            for ch in proposals:
                if ch.get("kind") == "round" and _already_known(c, ch):
                    continue
                if ch.get("kind") == "round" and _older_than_last_round(c, ch):
                    held.append({"date": today_s, "company": c["name"], "change": ch,
                                 "reason": "older than the round already recorded; check by hand"})
                    continue
                ok, reason, url = verify.check(c["name"], ch, citations, fetch, aliases=c.get("aliases") or [])
                if ok and rcfg.get("require_source_match", True):
                    if ch.get("kind") == "round" and ch.get("total_raised"):
                        ch["total_raised_verified"] = verify.check(
                            c["name"], {"kind": "baseline", "raised": ch["total_raised"], "source": ch.get("source")},
                            citations, fetch, aliases=c.get("aliases") or [])[0]
                    accepted.append(apply(c, ch, today_s))
                    ok_any = True
                    print(f"    ✓ {ch['kind']}: {reason}")
                else:
                    held.append({"date": today_s, "company": c["name"], "change": ch, "reason": reason})
                    print(f"    ✗ held: {ch['kind']} — {reason}")
            c["lastVerified"] = today_s
            if ok_any or c.get("verifiedBy") != "pending":
                c["verifiedBy"] = "weekly-run"
            if not ok_any and result.get("summary", "").lower().startswith("no change"):
                c["confidence"] = c.get("confidence") or "medium"

    if not dry_run:
        tracker.save(companies)
        prior = json.loads(REVIEW_PATH.read_text()) if REVIEW_PATH.exists() else []
        REVIEW_PATH.write_text(json.dumps((held + prior)[:200], indent=2, ensure_ascii=False) + "\n")

    result = {"date": today_s, "kind": "weekly", "checked": checked, "applied": accepted, "held": len(held)}
    if not dry_run:
        (tracker.DATA / "last_run.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"\n  REFRESH COMPLETE — {checked} checked | {len(accepted)} applied | {len(held)} held for review\n")
    return result
