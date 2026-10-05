from datetime import datetime, timezone

from app.engine import (
    build_flags,
    compare_market_model,
    detect_internal_market_changes,
    market_summary,
    research_score,
)
from app.models import AvailabilityItem, MarketSnapshot, ModelView, ResearchGame


def game(line: float = 3.5, probability: float = 0.45) -> ResearchGame:
    return ResearchGame(
        game_id="TEST",
        league="NFL",
        start_time=datetime(2026, 10, 11, 20, 20, tzinfo=timezone.utc),
        home_team="KC",
        away_team="BUF",
        market=[
            MarketSnapshot(
                timestamp=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
                bookmaker="pinnacle",
                market="spread",
                side="BUF",
                line=line,
                price=-110,
            ),
            MarketSnapshot(
                timestamp=datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc),
                bookmaker="pinnacle",
                market="spread",
                side="BUF",
                line=3.0,
                price=-108,
            ),
            MarketSnapshot(
                timestamp=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
                bookmaker="fanduel",
                market="moneyline",
                side="BUF",
                price=135,
                implied_probability=0.4255,
            ),
        ],
        model=ModelView(
            win_probability=probability,
            projected_spread=1.5,
            projected_total=44.5,
            confidence=0.7,
            sample_size=10,
        ),
    )


def test_market_model_compare():
    result = compare_market_model(game())
    assert result["market_win_probability"] == 0.4255
    assert result["disagreement"] == "mild"
    assert result["spread_delta"] == -1.5


def test_internal_market_change_detection():
    changes = detect_internal_market_changes(game())
    assert len(changes) == 1
    assert changes[0].category == "market"
    assert changes[0].new_value["line"] == 3.0


def test_market_summary_tracks_open_and_current():
    summary = market_summary(game())
    spread = next(item for item in summary if item["market"] == "spread")
    assert spread["opening"]["line"] == 3.5
    assert spread["current"]["line"] == 3.0
    assert spread["line_move"] == -0.5


def test_build_flags():
    current = game(probability=0.45)
    current.model.sample_size = 3
    current.availability = [
        AvailabilityItem(
            name="BUF WR1",
            status="Questionable",
            source="ESPN",
            updated_at=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
        )
    ]
    current.unknowns = ["Final availability"]
    flags = build_flags(current)
    codes = {flag.code for flag in flags}
    assert {"SMALL_SAMPLE", "AVAILABILITY_UNRESOLVED", "UNKNOWN_VARIABLES"} <= codes


def test_research_score_increases_for_disagreement():
    current = game(line=3.5, probability=0.55)
    score = research_score(current)
    assert score > 0
