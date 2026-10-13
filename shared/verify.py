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
EXIT_WORDS = re.compile(r"acquir|acquisition|to buy|bought|agreed to buy|merg(?:e|er|ed|ing)|takeover|take-over|\bipo\b|went public|goes public", re.I)
SHUT_WORDS = re.compile(r"shut(?:s|ting)? down|wind(?:s|ing)? down|wound down|clos(?:e|es|ed|ing) (?:its|the) doors|"
                        r"ceased (?:trading|operations)|(?:entered|into|in) administration|insolven|bankrupt|liquidat", re.I)
RAISE_WORDS = re.compile(r"rais|funding|financing|round|investment", re.I)
WINDOW = 300  # the figure must sit within this many characters of the company's name


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


def _name_pattern(name: str) -> re.Pattern:
    n = name.strip()
    if re.search(r"\.ai$", n, re.I):  # "Orca.AI" may appear as "Orca AI" or "Orca.ai", never bare "Orca"
        core = re.escape(n[:-3])
        pat = core + r"(?:\.ai|[\s-]ai)"
    else:
        pat = re.escape(n).replace(r"\ ", r"[\s-]?")
    return re.compile(r"(?<![\w.])" + pat + r"(?![\w])", re.I)


def name_spans(names, text: str) -> list[int]:
    """Start offsets of every mention of the company (name or alias) in the text."""
    out = []
    for n in names:
        if n:
            out.extend(m.start() for m in _name_pattern(n).finditer(text))
    return sorted(out)


def name_in(name: str, text: str) -> bool:
    return bool(name_spans([name], text))


def _near(text: str, spans: list[int], window: int = WINDOW):
    """The slices of text around each mention of the company."""
    for i in spans:
        yield text[max(0, i - window): i + window]


def _norm_url(u: str) -> str:
    u = (u or "").strip().split("#")[0]
    u = re.sub(r"[?&]utm_[^&]*", "", u).rstrip("?&")
    return re.sub(r"^https?://(www\.)?", "", u).rstrip("/").lower()


def evidence_for(change: dict, citations: list[dict], fetch=fetch_text) -> list[tuple[str, str]]:
    """Texts to check, in order of trust: the cited page itself, then the passage the search retrieved from it."""
    url = (change.get("source") or "").strip()
    texts = []
    if url:
        page = fetch(url)
        if page:
            texts.append((url, page))
        quoted = " ".join(c.get("cited_text", "") for c in citations if _norm_url(c.get("url", "")) == _norm_url(url))
        if quoted.strip():
            texts.append((url, normalise(quoted)))
    return texts


def check(company: str, change: dict, citations: list[dict], fetch=fetch_text,
          aliases: list[str] | tuple = ()) -> tuple[bool, str, str | None]:
    """
    Decide whether a proposed change is supported by its own source.

    The company (or an alias) must be named, and the evidence must sit within
    WINDOW characters of that mention: the amount for a round, the acquirer and
    a deal word for an exit, a shutdown phrase for a shutdown. This is what
    stops "Tony Stark ... ceasefire" or "humanoid robots ... Figure raised $152M"
    from passing for Stark or Humanoid.
    Returns (ok, reason, url_that_supported_it).
    """
    kind = change.get("kind")
    names = [company, *aliases]
    texts = evidence_for(change, citations, fetch)
    if not texts:
        return False, "source could not be read and the search retrieved nothing from it", None
    for url, text in texts:
        spans = name_spans(names, text)
        if not spans:
            continue
        for near in _near(text, spans):
            if kind == "round":
                if change.get("amount"):
                    if amount_in(change["amount"], near):
                        return True, f"{change['amount']} stated next to the company's name", url
                elif change.get("round") and change["round"].lower() in near.lower() and RAISE_WORDS.search(near):
                    return True, f"'{change['round']}' and a funding word next to the name (amount undisclosed)", url
            elif kind == "exit":
                acq = change.get("acquirer") or ""
                if acq and name_in(acq, near) and EXIT_WORDS.search(near):
                    return True, f"acquirer '{acq}' and a deal word next to the name", url
            elif kind == "shutdown":
                if SHUT_WORDS.search(near):
                    return True, "a shutdown phrase next to the name", url
            elif kind == "baseline":
                if change.get("raised") and amount_in(change["raised"], near):
                    return True, f"total {change['raised']} stated next to the name", url
    return False, "the source does not state this change next to the company's name", None
