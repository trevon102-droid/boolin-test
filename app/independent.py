from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from .models import DataStatus, IndependentOpinion, ResearchDecision, ResearchGame


def _latest(game: ResearchGame, market: str, bookmaker: str | None = None):
    values = [m for m in game.market if m.market == market]
    if bookmaker:
        values = [m for m in values if m.bookmaker.lower() == bookmaker.lower()]
    return max(values, key=lambda x: x.timestamp) if values else None


def _latest_by_book(game: ResearchGame, market: str) -> list:
    values = [m for m in game.market if m.market == market]
    latest: dict[str, object] = {}
    for value in values:
        key = value.bookmaker.lower()
        if key not in latest or value.timestamp > latest[key].timestamp:
            latest[key] = value
    return list(latest.values())


def _movement(game: ResearchGame, market: str) -> str:
    snapshots = sorted(
        [m for m in game.market if m.market == market],
        key=lambda x: x.timestamp,
    )
    if len(snapshots) < 2:
        return "unknown"
    first, last = snapshots[0], snapshots[-1]
    if first.line is not None and last.line is not None:
        delta = last.line - first.line
        if abs(delta) < 0.25:
            return "stable"
        return "toward_higher_line" if delta > 0 else "toward_lower_line"
    if first.price is not None and last.price is not None:
        delta = last.price - first.price
        if abs(delta) < 5:
            return "stable"
        return "price_moved"
    return "unknown"


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


def _market_probability(game: ResearchGame) -> float | None:
    latest = _latest_by_book(game, "moneyline")
    probabilities = [m.implied_probability for m in latest if m.implied_probability is not None]
    return round(mean(probabilities), 4) if probabilities else None


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
    moneylines = _latest_by_book(game, "moneyline")
    probabilities = [
        m.implied_probability
        for m in moneylines
        if m.implied_probability is not None
    ]
    market_probability = round(mean(probabilities), 4) if probabilities else None

    spread = _latest(game, "spread", "pinnacle") or _latest(game, "spread")
    total = _latest(game, "total", "pinnacle") or _latest(game, "total")

    movement = _movement(game, "spread")
    availability = _availability_signal(game)
    quality = _data_quality(game)
    confidence = _confidence(game, probabilities, quality, availability)

    reasons: list[str] = []
    warnings: list[str] = []

    if market_probability is not None:
        reasons.append(
            f"Independent market consensus is {market_probability:.1%} from the latest available moneyline prices."
        )
    else:
        warnings.append("No usable moneyline probability is available.")

    if len(probabilities) >= 2:
        dispersion = max(probabilities) - min(probabilities)
        reasons.append(f"Cross-book moneyline dispersion is {dispersion:.1%}.")
        if dispersion > 0.07:
            warnings.append("Books disagree materially on the moneyline.")
    else:
        warnings.append("Only one usable moneyline probability is available.")

    if movement == "stable":
        reasons.append("Stored spread history is stable.")
    elif movement != "unknown":
        reasons.append(f"Stored spread history shows {movement}.")

    if availability == "unresolved":
        warnings.append("Availability remains unresolved, so confidence is deliberately reduced.")
    elif availability == "material_out_possible":
        warnings.append("Reported availability may materially change the research conclusion.")

    if quality != "good":
        warnings.append(f"Underlying source quality is {quality}.")

    if confidence < 0.45 or market_probability is None:
        decision = ResearchDecision.INSUFFICIENT
    elif warnings and confidence < 0.60:
        decision = ResearchDecision.WATCH
    else:
        decision = ResearchDecision.WATCH

    return IndependentOpinion(
        market_probability=market_probability,
        market_spread=spread.line if spread else None,
        market_total=total.line if total else None,
        movement_signal=movement,
        availability_signal=availability,
        data_quality=quality,
        confidence=confidence,
        decision=decision,
        reasons=reasons,
        warnings=warnings,
    )
