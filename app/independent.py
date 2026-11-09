from __future__ import annotations

from . import matching
from .models import DataStatus, IndependentOpinion, ResearchDecision, ResearchGame


LINE_THRESHOLD = 0.25       # a half-point line change counts as a move
IMPLIED_THRESHOLD = 0.005   # 0.5 probability points of price change counts as a move


def _same_sign(a: int, b: int) -> bool:
    return (a > 0) == (b > 0)


def movement_records(game: ResearchGame, markets: tuple[str, ...] = ("spread", "moneyline", "total")) -> list[dict]:
    """Movement per series (bookmaker, market, side, period, line id). Each series is compared only with itself:
    never across books, across the two sides of a market, or across alternate lines.

    Statuses are descriptive market facts, not betting signals:
      STABLE, LINE_ONLY_MOVE, PRICE_ONLY_MOVE, LINE_AND_PRICE_MOVE, INSUFFICIENT_HISTORY, UNKNOWN.
    (STEAM_MOVE / REVERSE_LINE_MOVEMENT need betting-percentage and cross-book timing data we do not have.)
    `toward_selection` is True/False for spreads and moneylines (the market got more/less favorable to that
    selection) and for sided totals, else None.
    """
    series: dict[tuple, list] = {}
    for m in game.market:
        if m.market in markets:
            series.setdefault(matching.series_key(m), []).append(m)
    out: list[dict] = []
    for (book, market, side, period, line_id), snaps in series.items():
        snaps = sorted(snaps, key=lambda x: x.timestamp)
        first, last = snaps[0], snaps[-1]
        rec: dict = {"bookmaker": first.bookmaker, "market": market, "side": first.side, "period": period, "line_id": line_id,
                     "snapshots": len(snaps), "opening_line": first.line, "current_line": last.line,
                     "opening_price": first.price, "current_price": last.price,
                     "opening_timestamp": first.timestamp.isoformat(), "current_timestamp": last.timestamp.isoformat(),
                     "line_delta": None, "price_delta": None, "implied_delta": None,
                     "status": "INSUFFICIENT_HISTORY", "toward_selection": None}
        if len(snaps) >= 2:
            line_delta = round(last.line - first.line, 4) if first.line is not None and last.line is not None else None
            p0, p1 = matching._raw(first), matching._raw(last)
            implied_delta = round(p1 - p0, 4) if p0 is not None and p1 is not None else None
            rec["line_delta"], rec["implied_delta"] = line_delta, implied_delta
            # A raw American delta is only meaningful on the same side of even money (+105 -> -105 is not -210).
            if first.price is not None and last.price is not None and _same_sign(first.price, last.price):
                rec["price_delta"] = last.price - first.price
            line_moved = line_delta is not None and abs(line_delta) >= LINE_THRESHOLD
            price_moved = implied_delta is not None and abs(implied_delta) >= IMPLIED_THRESHOLD
            if line_delta is None and implied_delta is None:
                rec["status"] = "UNKNOWN"
            elif line_moved and price_moved:
                rec["status"] = "LINE_AND_PRICE_MOVE"
            elif line_moved:
                rec["status"] = "LINE_ONLY_MOVE"
            elif price_moved:
                rec["status"] = "PRICE_ONLY_MOVE"
            else:
                rec["status"] = "STABLE"
            if rec["status"] not in ("STABLE", "UNKNOWN"):
                if market == "spread":      # smaller handicap (or shorter price) = market likes the team more
                    score = -line_delta if line_moved else implied_delta
                elif market == "moneyline":
                    score = implied_delta
                elif market == "total" and side in ("over", "under"):
                    # a higher total favors the over; if only the price moved, a shorter price favors that side
                    score = (line_delta if side == "over" else -line_delta) if line_moved else implied_delta
                else:
                    score = None
                rec["toward_selection"] = None if score is None else score > 0
        out.append(rec)
    return sorted(out, key=lambda r: (r["market"], r["bookmaker"] or "", r["side"] or "", r["period"], r["line_id"] or ""))


def _movement(game: ResearchGame, market: str) -> str:
    """Coarse, order-independent summary of per-series movement for one market."""
    recs = [r for r in movement_records(game, (market,)) if r["status"] != "INSUFFICIENT_HISTORY"]
    if not recs or all(r["status"] == "UNKNOWN" for r in recs):
        return "unknown"
    moved = {r["status"] for r in recs}
    if moved == {"STABLE"}:
        return "stable"
    if moved & {"LINE_ONLY_MOVE", "LINE_AND_PRICE_MOVE"}:
        return "line_moved"
    return "price_moved"


def _availability_signal(game: ResearchGame) -> str:
    statuses = {a.status.lower() for a in game.availability}
    if not statuses:
        return "no_reported_uncertainty"
    if statuses & {"out", "confirmed_out"}:
        return "material_out_possible"
    if statuses & {"questionable", "probable", "projected"}:
        return "unresolved"
    return "confirmed_or_stable"


def _data_quality(game: ResearchGame) -> str:
    statuses = {s.status for s in game.sources}
    if DataStatus.ERROR in statuses:
        return "poor"
    if DataStatus.PARTIAL in statuses:
        return "mixed"
    if DataStatus.SKIPPED in statuses:
        return "mixed"
    if not game.sources:
        return "unknown"
    return "good"


def _confidence(
    game: ResearchGame,
    market_probabilities: list[float],
    data_quality: str,
    availability: str,
) -> float:
    score = 0.45

    if len(market_probabilities) >= 3:
        score += 0.15
    elif len(market_probabilities) >= 2:
        score += 0.08

    if len(market_probabilities) >= 2:
        spread = max(market_probabilities) - min(market_probabilities)
        if spread < 0.02:
            score += 0.15
        elif spread > 0.07:
            score -= 0.10

    if data_quality == "good":
        score += 0.15
    elif data_quality == "mixed":
        score -= 0.08
    elif data_quality == "poor":
        score -= 0.20

    if availability == "unresolved":
        score -= 0.15
    elif availability == "material_out_possible":
        score -= 0.08

    return max(0.05, min(0.95, round(score, 3)))


def build_independent_opinion(game: ResearchGame) -> IndependentOpinion:
    # The market probability is for ONE named team: the model's perspective if set, else the home team.
    team = matching.resolve_team(game, game.model.perspective) or game.home_team
    fm = matching.fair_moneyline(game, team)
    probabilities = list(fm["per_book"].values())
    market_probability = fm["probability"]

    spread = matching.market_spread_for(game, team)
    total = matching.latest(game, "total", bookmaker=matching.REFERENCE_BOOK) or matching.latest(game, "total")

    records = movement_records(game)
    movement = _movement(game, "spread")
    availability = _availability_signal(game)
    quality = _data_quality(game)
    confidence = _confidence(game, probabilities, quality, availability)
    if fm["basis"] == "raw_implied_vig_included":
        confidence = max(0.05, round(confidence - 0.05, 3))  # a margin-inflated price is weaker evidence

    reasons: list[str] = []
    warnings: list[str] = []

    if market_probability is not None:
        if fm["basis"] == "no_vig_consensus":
            reasons.append(
                f"Independent market consensus for {team} is {market_probability:.1%} "
                f"(no-vig, paired sides, {len(fm['books'])} book{'s' if len(fm['books']) != 1 else ''}: {', '.join(fm['books'])})."
            )
        else:
            reasons.append(f"Market price for {team} is {market_probability:.1%} but includes the bookmaker margin.")
            warnings.append(
                f"Only one side of the moneyline was quoted, so the margin could not be removed; "
                f"the {team} probability is overstated by roughly the book's hold."
            )
    else:
        warnings.append(f"No usable {team} moneyline probability is available.")

    if fm["basis"] == "no_vig_consensus" and fm["excluded"]:
        warnings.append("Excluded from the moneyline consensus: " + "; ".join(f"{b} ({r})" for b, r in fm["excluded"].items()) + ".")

    if len(probabilities) >= 2:
        dispersion = max(probabilities) - min(probabilities)
        reasons.append(f"Cross-book moneyline dispersion is {dispersion:.1%}.")
        if dispersion > 0.07:
            warnings.append("Books disagree materially on the moneyline.")
    else:
        warnings.append("Only one usable moneyline probability is available.")

    if movement == "stable":
        reasons.append("Stored spread history is stable (each book and side compared only with itself).")
    elif movement != "unknown":
        reasons.append(f"Stored spread history shows {movement} (see per-book movement records).")

    if matching.ambiguous_snapshots(game):
        warnings.append("Some series were quoted twice at one timestamp with different values (possible unlabelled alternate line).")

    if availability == "unresolved":
        warnings.append("Availability remains unresolved, so confidence is deliberately reduced.")
    elif availability == "material_out_possible":
        warnings.append("Reported availability may materially change the research conclusion.")

    if quality != "good":
        warnings.append(f"Underlying source quality is {quality}.")

    if confidence < 0.45 or market_probability is None:
        decision = ResearchDecision.INSUFFICIENT
    else:
        decision = ResearchDecision.WATCH

    return IndependentOpinion(
        market_probability=market_probability,
        market_probability_side=team,
        market_probability_basis=fm["basis"],
        market_books=fm["books"],
        market_excluded=fm["excluded"],
        market_spread=spread.line if spread else None,
        market_total=total.line if total else None,
        movement_signal=movement,
        movement=records,
        availability_signal=availability,
        data_quality=quality,
        confidence=confidence,
        decision=decision,
        reasons=reasons,
        warnings=warnings,
    )
