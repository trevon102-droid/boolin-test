"""Market identity and matching: the ONE place that decides which quotes may be compared.

Rules (a quote is only usable if all of these hold):
  same event (a ResearchGame), same market, same selection/side, same period, same line series (main vs alternate).
Two-sided markets (moneyline/spread) are only converted to a fair probability from a COMPLETE pair of sides
from the SAME bookmaker with timestamps close together. Anything ambiguous is excluded with a stated reason,
never silently substituted.
"""
from __future__ import annotations

from statistics import fmean
from typing import Any

from .marketmath import devig, implied
from .models import MarketSnapshot, ResearchGame

SYNC_MINUTES = 15  # max gap between the two sides' quotes for a book to count as one synchronized price
REFERENCE_BOOK = "pinnacle"


def norm(s: str | None) -> str | None:
    return s.strip().lower() if isinstance(s, str) and s.strip() else None


def resolve_team(game: ResearchGame, spec: str | None) -> str | None:
    """Turn a perspective ('BUF', 'home', 'away') into one of the game's two team codes, else None."""
    s = norm(spec)
    if s is None:
        return None
    if s == "home":
        return game.home_team
    if s == "away":
        return game.away_team
    for team in (game.home_team, game.away_team):
        if norm(team) == s:
            return team
    return None


def opponent(game: ResearchGame, team: str) -> str:
    return game.away_team if norm(team) == norm(game.home_team) else game.home_team


def series_key(m: MarketSnapshot) -> tuple:
    """One continuous line series: bookmaker, market, selection, period, line id (None = main line)."""
    return (norm(m.bookmaker), m.market, norm(m.side), m.period, m.line_id)


def select(game: ResearchGame, market: str, side: str | None = None, bookmaker: str | None = None,
           period: str = "full_game", line_id: str | None = None) -> list[MarketSnapshot]:
    out = [m for m in game.market if m.market == market and m.period == period and m.line_id == line_id]
    if side is not None:
        out = [m for m in out if norm(m.side) == norm(side)]
    if bookmaker is not None:
        out = [m for m in out if norm(m.bookmaker) == norm(bookmaker)]
    return out


def latest(game: ResearchGame, market: str, side: str | None = None, bookmaker: str | None = None,
           period: str = "full_game", line_id: str | None = None) -> MarketSnapshot | None:
    vals = select(game, market, side, bookmaker, period, line_id)
    return max(vals, key=lambda m: m.timestamp) if vals else None


def ambiguous_snapshots(game: ResearchGame) -> list[dict[str, Any]]:
    """Same series AND same timestamp but different line/price: we can't tell which is real
    (usually an alternate line that was not labelled with `line_id`)."""
    seen: dict[tuple, MarketSnapshot] = {}
    found: list[dict[str, Any]] = []
    for m in game.market:
        k = series_key(m) + (m.timestamp,)
        if k in seen and (seen[k].line != m.line or seen[k].price != m.price):
            found.append({"bookmaker": m.bookmaker, "market": m.market, "side": m.side, "timestamp": m.timestamp.isoformat(),
                          "values": [{"line": seen[k].line, "price": seen[k].price}, {"line": m.line, "price": m.price}]})
        seen.setdefault(k, m)
    return found


def _raw(m: MarketSnapshot | None) -> float | None:
    if m is None:
        return None
    p = implied(m.price) if m.price is not None else None
    return p if p is not None else m.implied_probability


def fair_moneyline(game: ResearchGame, team: str, sync_minutes: int = SYNC_MINUTES) -> dict[str, Any]:
    """Fair win probability for `team` from the market.

    Per bookmaker: take the latest moneyline for `team` and for its opponent (main line, full game), require
    both, require them within `sync_minutes`, then remove the margin. Consensus = mean across eligible books.
    If NO book has a complete pair but some quote `team` alone, fall back to the raw (vig-included) implied
    probability and say so in `basis`; the margin could not be removed.
    """
    opp = opponent(game, team)
    books = sorted({norm(m.bookmaker) for m in select(game, "moneyline")})
    per_book: dict[str, float] = {}
    raw_only: dict[str, float] = {}
    excluded: dict[str, str] = {}
    ambiguous = {(a["bookmaker"].lower(), a["side"] and a["side"].lower()) for a in ambiguous_snapshots(game) if a["market"] == "moneyline"}
    for b in books:
        mine, theirs = latest(game, "moneyline", team, b), latest(game, "moneyline", opp, b)
        if mine is None:
            excluded[b] = f"no {team} moneyline quote"
            continue
        if (b, norm(mine.side)) in ambiguous or (theirs is not None and (b, norm(theirs.side)) in ambiguous):
            excluded[b] = "ambiguous snapshots (same timestamp, different prices)"
            continue
        p_mine, p_theirs = _raw(mine), _raw(theirs)
        if theirs is None or p_mine is None or p_theirs is None:
            if p_mine is not None:
                raw_only[b] = p_mine
            excluded[b] = f"missing {opp} side, so the margin cannot be removed"
            continue
        gap = abs((mine.timestamp - theirs.timestamp).total_seconds()) / 60
        if gap > sync_minutes:
            excluded[b] = f"sides quoted {gap:.0f} min apart (limit {sync_minutes})"
            continue
        fair = devig([p_mine, p_theirs])
        if fair is None:
            excluded[b] = "invalid prices"
            continue
        per_book[b] = fair[0]
    if per_book:
        return {"team": team, "probability": round(fmean(per_book.values()), 4), "basis": "no_vig_consensus",
                "books": sorted(per_book), "per_book": per_book, "excluded": excluded,
                "reference": per_book.get(REFERENCE_BOOK),
                "dispersion": (max(per_book.values()) - min(per_book.values())) if len(per_book) > 1 else None}
    if raw_only:
        return {"team": team, "probability": round(fmean(raw_only.values()), 4), "basis": "raw_implied_vig_included",
                "books": sorted(raw_only), "per_book": raw_only, "excluded": excluded, "reference": None,
                "dispersion": (max(raw_only.values()) - min(raw_only.values())) if len(raw_only) > 1 else None}
    return {"team": team, "probability": None, "basis": "unavailable", "books": [], "per_book": {},
            "excluded": excluded, "reference": None, "dispersion": None}


def market_spread_for(game: ResearchGame, team: str) -> MarketSnapshot | None:
    """Latest main-line spread for exactly `team` (never the opponent's, whose sign is opposite)."""
    return latest(game, "spread", team, REFERENCE_BOOK) or latest(game, "spread", team)
