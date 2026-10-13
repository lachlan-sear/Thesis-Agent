"""
Source checks for the weekly refresh.

A proposed change (a new round, an exit, a shutdown) is only applied when the
page it cites actually says so: the company's name, and the amount or the
acquirer, must appear in that page's text (or, when the page can't be fetched,
in the passage the search tool quoted from it). Anything else is held for a
human in data/review.json. The model proposes; the source decides.
"""

from __future__ import annotations

import html
import re
import urllib.request

UA = "Mozilla/5.0 (compatible; thesis-agent/3.0; +https://github.com/lachlan-sear/thesis-agent)"
CURRENCY = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR",
            "£": "GBP", "gbp": "GBP", "chf": "CHF", "sek": "SEK"}
_AMOUNT = re.compile(
    r"(us\$|\$|€|£|usd|eur|gbp|chf|sek)\s?(\d+(?:[.,]\d+)?)\s?"
    r"(billion|million|bn|mn|m|b|k|thousand)\b",
    re.I,
)
_AMOUNT_SUFFIX = re.compile(
    r"(\d+(?:[.,]\d+)?)\s?(billion|million|bn|mn|m|b)\s?(dollars|euros|pounds|usd|eur|gbp)\b", re.I)
EXIT_WORDS = re.compile(r"acqui|to buy|bought|buys|purchase|merg|takeover|take-over|ipo|listing|went public", re.I)
SHUT_WORDS = re.compile(r"shut|wind(?:s|ing)? down|wound down|clos(?:e|es|ed|ing) (?:its|the) doors|ceas|administration|insolven|bankrupt", re.I)


def fetch_text(url: str, timeout: int = 15, limit: int = 2_000_000) -> str | None:
    """Fetch a page and return its visible text, or None if it can't be read."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(limit).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return None
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return normalise(html.unescape(raw))


def normalise(text: str) -> str:
    text = text.replace(" ", " ").replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _scale(word: str) -> float:
    w = word.lower()
    if w in ("billion", "bn", "b"):
        return 1000.0
    if w in ("k", "thousand"):
        return 0.001
    return 1.0


_DECIMAL_COMMA = re.compile(r"(\d),(\d{1,2})(?!\d)")


def _numbers(text: str) -> str:
    """'€3,2M' (European decimal comma) -> '€3.2M'; then drop thousands separators."""
    return _DECIMAL_COMMA.sub(r"\1.\2", text).replace(",", "")


def parse_amount(s: str | None) -> tuple[str, float] | None:
    """'$50M' / '€32 million' / '£4.5m' -> ('USD', 50.0) in millions."""
    if not s:
        return None
    flat = _numbers(s)
    m = _AMOUNT.search(flat)
    if m:
        return CURRENCY[m.group(1).lower()], round(float(m.group(2)) * _scale(m.group(3)), 3)
    m = _AMOUNT_SUFFIX.search(flat)
    if m:
        cur = {"dollars": "USD", "euros": "EUR", "pounds": "GBP"}.get(m.group(3).lower(), m.group(3).upper())
        return cur, round(float(m.group(1)) * _scale(m.group(2)), 3)
    return None


def amounts_in(text: str) -> set[tuple[str, float]]:
    flat = _numbers(text)
    found = {(CURRENCY[m.group(1).lower()], round(float(m.group(2)) * _scale(m.group(3)), 3))
             for m in _AMOUNT.finditer(flat)}
    for m in _AMOUNT_SUFFIX.finditer(flat):
        cur = {"dollars": "USD", "euros": "EUR", "pounds": "GBP"}.get(m.group(3).lower(), m.group(3).upper())
        found.add((cur, round(float(m.group(1)) * _scale(m.group(2)), 3)))
    return found


def amount_in(claim: str | None, text: str) -> bool:
    want = parse_amount(claim)
    if not want:
        return False
    cur, val = want
    return any(c == cur and abs(v - val) <= max(0.05, val * 0.01) for c, v in amounts_in(text))


def name_in(name: str, text: str) -> bool:
    """Company name appears as a word (case-insensitive); '.ai' / ' AI' suffixes are optional."""
    base = re.sub(r"(\.ai|\s+ai)$", "", name.strip(), flags=re.I)
    pattern = r"(?<![\w])" + re.escape(base).replace(r"\ ", r"[\s-]?") + r"(?![\w])"
    return re.search(pattern, text, re.I) is not None


def evidence_for(change: dict, citations: list[dict], fetch=fetch_text) -> list[tuple[str, str]]:
    """Texts to check, in order of trust: the cited page itself, then the search tool's quotes from it."""
    url = (change.get("source") or "").strip()
    texts = []
    if url:
        page = fetch(url)
        if page:
            texts.append((url, page))
        quoted = " ".join(c.get("cited_text", "") for c in citations if c.get("url") == url)
        if quoted.strip():
            texts.append((url, normalise(quoted)))
    return texts


def check(company: str, change: dict, citations: list[dict], fetch=fetch_text) -> tuple[bool, str, str | None]:
    """
    Decide whether a proposed change is supported by its own source.
    Returns (ok, reason, url_that_supported_it).
    """
    kind = change.get("kind")
    texts = evidence_for(change, citations, fetch)
    if not texts:
        return False, "source could not be read and the search quoted nothing from it", None
    for url, text in texts:
        if not name_in(company, text):
            continue
        if kind == "round":
            if change.get("amount"):
                if amount_in(change["amount"], text):
                    return True, f"name and {change['amount']} found on the source", url
            elif change.get("round") and change["round"].lower() in text.lower():
                return True, f"name and '{change['round']}' found on the source (amount undisclosed)", url
        elif kind == "exit":
            acq = change.get("acquirer") or ""
            if acq and name_in(acq, text) and EXIT_WORDS.search(text):
                return True, f"name, acquirer '{acq}' and a deal verb found on the source", url
        elif kind == "shutdown":
            if SHUT_WORDS.search(text):
                return True, "name and a shutdown term found on the source", url
        elif kind == "baseline":
            if change.get("raised") and amount_in(change["raised"], text):
                return True, f"name and total {change['raised']} found on the source", url
    return False, "the source does not state this change for this company", None
