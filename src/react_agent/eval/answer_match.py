"""Shared answer text matching for eval suites (e.g. public RAG)."""

from __future__ import annotations

import re


def normalize_text(s: str) -> str:
    """Normalize case and whitespace for containment matching."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("'", "'").replace("'", "'")
    return s


def match_gold(pred_text: str, gold: str, benchmark: str = "hotpotqa") -> tuple[bool, str]:
    """Loose text match against gold (HotpotQA-style containment / token cover).

    ``benchmark`` is retained for call-site compatibility; numeric GSM8K matching
    was removed with the public_benchmark suite.
    """
    _ = benchmark
    gold = (gold or "").strip()
    if not gold:
        return False, "empty gold"
    p = normalize_text(pred_text)
    g = normalize_text(gold)
    if not g:
        return False, "empty gold"
    if g in p or p in g:
        return True, "contains"
    if len(g) <= 40 and all(tok in p for tok in g.split() if len(tok) > 2):
        return True, "token_cover"
    return False, f"gold {gold!r} not found in prediction"
