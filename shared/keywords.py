"""
Thesis keywords for the free sources' relevance filters.

The source modules ship with their own default keyword lists; at import they
swap them for the sector keywords in thesis.yaml, so changing the thesis
changes what every source keeps. Set THESIS_CONFIG to point at another file.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _config() -> dict:
    from shared.config_loader import load_config, CONFIG_PATH
    path = Path(os.environ.get("THESIS_CONFIG", CONFIG_PATH))
    try:
        return load_config(path)
    except Exception:
        return {}


def thesis_keywords(fallback: list[str] | None = None) -> list[str]:
    thesis = _config().get("thesis", {})
    # Round-robin across sectors so a short list still covers every orbit.
    lists = [list(s.get("keywords") or []) + [s.get("short") or s.get("name") or ""]
             for s in thesis.get("sectors", [])]
    words: list[str] = []
    while any(lists):
        for lst in lists:
            if lst:
                words.append(lst.pop(0))
    words = [w.lower().strip() for w in words if w and w.strip()]
    if not words:
        return list(fallback or [])
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def thesis_queries(template: str, fallback: list[str] | None = None, limit: int = 12) -> list[str]:
    kws = thesis_keywords()
    if not kws:
        return list(fallback or [])
    return [template.format(kw=k) for k in kws[:limit]]
