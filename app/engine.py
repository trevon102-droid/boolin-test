from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import matching
from .models import (
    ChangeEvent,
    DataStatus,
    ResearchFlag,
    ResearchGame,
)


def age_seconds(fetched_at: datetime, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - fetched_at).total_seconds()))


def _health_status_label(status: DataStatus) -> str:
    return {
        DataStatus.OK: "healthy",
        DataStatus.PARTIAL: "partial",
        DataStatus.ERROR: "failed",
        DataStatus.SKIPPED: "skipped",
    }[status]


def build_flags(game: ResearchGame) -> list[ResearchFlag]:
    flags: list[ResearchFlag] = []

    if any(s.status in {DataStatus.PARTIAL, DataStatus.ERROR} for s in game.sources):
        flags.append(
            ResearchFlag(
                code="PARTIAL_DATA",
                severity="high",
                title="Partial or failed data source",
                explanation="At least one research source is not fully healthy. Treat affected fields as incomplete until resolved.",
                source_fields=["sources"],
            )
        )

    if any(s.status == DataStatus.SKIPPED for s in game.sources):
        flags.append(
            ResearchFlag(
                code="SKIPPED_SOURCE",
                severity="medium",
                title="Source unavailable or intentionally skipped",
                explanation="At least one expected research source was skipped. Do not interpret missing fields as negative evidence.",
                source_fields=["sources"],
            )
        )

    if game.model.sample_size is not None and game.model.sample_size < 5:
        flags.append(
            ResearchFlag(
                code="SMALL_SAMPLE",
                severity="medium",
                title="Small model sample",
                explanation=f"The current model view is based on only {game.model.sample_size} observations.",
                source_fields=["model.sample_size"],
            )
        )

    if any(a.status.lower() in {"questionable", "probable", "projected"} for a in game.availability):
        flags.append(
            ResearchFlag(
                code="AVAILABILITY_UNRESOLVED",
                severity="medium",
                title="Availability unresolved",
                explanation="At least one player or starter remains projected/questionable rather than confirmed.",
                source_fields=["availability"],
            )
        )

    if game.unknowns:
        flags.append(
            ResearchFlag(
                code="UNKNOWN_VARIABLES",
                severity="medium",
                title="Important unknowns remain",
                explanation="The research card contains unresolved variables that could materially change the conclusion.",
                source_fields=["unknowns"],
            )
        )

    return flags


def market_current(game: ResearchGame, market: str, bookmaker: str | None = None, side: str | None = None,
                   period: str = "full_game", line_id: str | None = None) -> Any | None:
    """Latest main-line quote. Pass `side` for any two-sided market: without it the latest quote of EITHER
    side is returned, and which side that is depends on input order."""
    return matching.latest(game, market, side=side, bookmaker=bookmaker, period=period, line_id=line_id)


def market_summary(game: ResearchGame, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    groups: dict[tuple, list[Any]] = {}
    ambiguous = {(a["bookmaker"], a["market"], a["side"]) for a in matching.ambiguous_snapshots(game)}

    for snapshot in game.market:
        # period and line_id are part of the identity: an alternate line is a different series, not a "move".
        key = (snapshot.bookmaker, snapshot.market, snapshot.side, snapshot.period, snapshot.line_id)
        groups.setdefault(key, []).append(snapshot)

    result: list[dict[str, Any]] = []
    for (bookmaker, market, side, period, line_id), snapshots in groups.items():
        ordered = sorted(snapshots, key=lambda x: x.timestamp)
        opening = ordered[0]
        current = ordered[-1]
        close_candidates = [m for m in ordered if m.timestamp <= game.start_time]
        closing = close_candidates[-1] if game.start_time <= now and close_candidates else None

        result.append(
            {
                "bookmaker": bookmaker,
                "market": market,
                "side": side,
                "period": period,
                "line_id": line_id,
                "ambiguous": (bookmaker, market, side) in ambiguous,
                "opening": opening.model_dump(mode="json"),
                "current": current.model_dump(mode="json"),
                "closing": closing.model_dump(mode="json") if closing else None,
                "snapshot_count": len(ordered),
                "line_move": (
                    round(current.line - opening.line, 2)
                    if current.line is not None and opening.line is not None
                    else None
                ),
                "price_move": (
                    current.price - opening.price
                    if current.price is not None and opening.price is not None
                    else None
                ),
            }
        )

    return sorted(result, key=lambda x: (x["market"], x["bookmaker"], x["side"] or "", x["period"], x["line_id"] or ""))


def freshness(game: ResearchGame, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    result = []

    for source in game.sources:
        age = age_seconds(source.fetched_at, now)
        result.append(
            {
                "source": source.name,
                "status": source.status.value,
                "health": _health_status_label(source.status),
                "source_type": source.source_type.value,
                "fetched_at": source.fetched_at,
                "age_seconds": age,
                "age_minutes": round(age / 60, 1),
                "fields": source.fields,
                "error": source.error,
            }
        )

    return sorted(result, key=lambda x: x["age_seconds"], reverse=True)


def compare_market_model(game: ResearchGame) -> dict[str, Any]:
    """Compare the model to the market, side-matched.

    The model's win probability and projected spread are FROM `game.model.perspective`; they are only compared
    to quotes for that same team. If the perspective is unset, the side-dependent comparisons are skipped and a
    warning is returned (the previous behavior compared against whichever side was quoted last).
    """
    result: dict[str, Any] = {}
    warnings: list[str] = []
    team = matching.resolve_team(game, game.model.perspective)
    needs_side = game.model.win_probability is not None or game.model.projected_spread is not None
    if needs_side and team is None:
        warnings.append(
            "MODEL_PERSPECTIVE_UNSPECIFIED: set model.perspective (team code, 'home' or 'away') so the model can be "
            "compared with the matching side of the market; moneyline and spread comparisons were skipped."
            if game.model.perspective is None else
            f"MODEL_PERSPECTIVE_INVALID: '{game.model.perspective}' is not {game.home_team}, {game.away_team}, 'home' or 'away'; "
            "moneyline and spread comparisons were skipped."
        )

    if team is not None:
        result["perspective_team"] = team

    if game.model.win_probability is not None and team is not None:
        fm = matching.fair_moneyline(game, team)
        if fm["probability"] is not None:
            delta = game.model.win_probability - fm["probability"]
            result["market_win_probability"] = fm["probability"]
            result["market_probability_basis"] = fm["basis"]
            result["market_books"] = fm["books"]
            result["model_win_probability"] = game.model.win_probability
            result["probability_delta"] = round(delta, 4)
            if abs(delta) >= 0.05:
                result["disagreement"] = "significant"
            elif abs(delta) >= 0.02:
                result["disagreement"] = "mild"
            else:
                result["disagreement"] = "aligned"
            if fm["basis"] != "no_vig_consensus":
                warnings.append("MARKET_PROBABILITY_INCLUDES_VIG: only one side was quoted, so the book margin was not removed.")
        else:
            warnings.append(f"NO_COMPARABLE_MONEYLINE: no usable {team} moneyline ({'; '.join(f'{b}: {r}' for b, r in fm['excluded'].items()) or 'none quoted'}).")
        if fm["basis"] == "no_vig_consensus":
            for book, reason in fm["excluded"].items():
                warnings.append(f"EXCLUDED_BOOK {book}: {reason}")

    if team is not None:
        spread = matching.market_spread_for(game, team)
        if spread and game.model.projected_spread is not None and spread.line is not None:
            result["market_spread"] = spread.line
            result["projected_spread"] = game.model.projected_spread
            result["spread_delta"] = round(game.model.projected_spread - spread.line, 2)

    # Totals have no side that matters: both sides carry the same line, so the latest main-line total is valid.
    total = market_current(game, "total")
    if total and game.model.projected_total is not None and total.line is not None:
        result["market_total"] = total.line
        result["projected_total"] = game.model.projected_total
        result["total_delta"] = round(game.model.projected_total - total.line, 2)

    if matching.ambiguous_snapshots(game):
        warnings.append("MARKET_AMBIGUOUS_SNAPSHOTS: same series quoted twice at one timestamp with different values (unlabelled alternate line?).")
    if warnings:
        result["warnings"] = warnings
    return result


def detect_changes(previous: ResearchGame, current: ResearchGame) -> list[ChangeEvent]:
    changes: list[ChangeEvent] = []

    if previous.model.model_dump() != current.model.model_dump():
        changes.append(
            ChangeEvent(
                timestamp=current.start_time,
                category="model",
                field="model",
                old_value=previous.model.model_dump(mode="json"),
                new_value=current.model.model_dump(mode="json"),
                source="research_engine",
                explanation="Model output changed between snapshots; stored data does not establish a single causal reason.",
            )
        )

    prev_market = {(m.bookmaker, m.market, m.side, m.period, m.line_id): m for m in previous.market}
    for m in current.market:
        old = prev_market.get((m.bookmaker, m.market, m.side, m.period, m.line_id))
        if old and (old.line != m.line or old.price != m.price):
            changes.append(
                ChangeEvent(
                    timestamp=m.timestamp,
                    category="market",
                    field=f"{m.bookmaker}.{m.market}.{m.side or ''}",
                    old_value={"line": old.line, "price": old.price},
                    new_value={"line": m.line, "price": m.price},
                    source=m.bookmaker,
                )
            )

    prev_availability = {a.name: a for a in previous.availability}
    for a in current.availability:
        old = prev_availability.get(a.name)
        if old and old.status != a.status:
            changes.append(
                ChangeEvent(
                    timestamp=a.updated_at,
                    category="availability",
                    field=a.name,
                    old_value=old.status,
                    new_value=a.status,
                    source=a.source,
                )
            )

    return sorted(changes, key=lambda x: x.timestamp)


def detect_internal_market_changes(game: ResearchGame) -> list[ChangeEvent]:
    changes: list[ChangeEvent] = []
    grouped: dict[tuple, list[Any]] = {}

    for snapshot in game.market:
        grouped.setdefault((snapshot.bookmaker, snapshot.market, snapshot.side, snapshot.period, snapshot.line_id), []).append(snapshot)

    for (bookmaker, market, side, period, line_id), snapshots in grouped.items():
        ordered = sorted(snapshots, key=lambda x: x.timestamp)
        for old, new in zip(ordered, ordered[1:]):
            if old.line == new.line and old.price == new.price:
                continue
            changes.append(
                ChangeEvent(
                    timestamp=new.timestamp,
                    category="market",
                    field=f"{bookmaker}.{market}.{side or ''}",
                    old_value={"line": old.line, "price": old.price},
                    new_value={"line": new.line, "price": new.price},
                    source=bookmaker,
                    explanation="Market value changed between stored snapshots; causality is not confirmed.",
                )
            )

    return sorted(changes, key=lambda x: x.timestamp)


def research_score(game: ResearchGame) -> int:
    score = 0
    flags = build_flags(game)
    score += min(40, len(flags) * 10)

    comparison = compare_market_model(game)
    if abs(comparison.get("probability_delta", 0)) >= 0.05:
        score += 25
    if abs(comparison.get("spread_delta", 0)) >= 1.5:
        score += 20
    if game.unknowns:
        score += min(15, len(game.unknowns) * 5)

    return min(100, score)
