"""Odds math for the independent layer.

Mirrors boolin's pipeline/oddsmath.py (separate repository, so the ~30 lines are duplicated on purpose; keep
the two in sync). `implied` is the RAW implied probability (includes the book's margin). `devig` removes the
margin proportionally across a COMPLETE set of outcomes and returns None for anything incomplete or invalid.
"""
from __future__ import annotations

import math


def _num(x) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def implied(american) -> float | None:
    a = _num(american)
    if a is None or -100 < a < 100:
        return None
    return -a / (-a + 100) if a < 0 else 100 / (a + 100)


def devig(raw_probs: list[float | None]) -> list[float] | None:
    """Proportional no-vig from raw implied probabilities of ALL outcomes (>= 2). None if incomplete."""
    if not raw_probs or len(raw_probs) < 2 or any(p is None or not (0 < p < 1) for p in raw_probs):
        return None
    total = sum(raw_probs)  # type: ignore[arg-type]
    return [p / total for p in raw_probs]  # type: ignore[operator]
