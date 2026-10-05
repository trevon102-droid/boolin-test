from datetime import datetime, timezone

from app.engine import compare_market_model, detect_changes, research_score
from app.models import MarketSnapshot, ModelView, ResearchGame


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
    assert result["spread_delta"] == -2.0


def test_detect_market_change():
    previous = game(line=3.5)
    current = game(line=3.0)
    current.market[1].timestamp = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
    current.start_time = datetime(2026, 10, 11, 20, 20, tzinfo=timezone.utc)

    changes = detect_changes(previous, current)
    assert any(c.category == "market" for c in changes)


def test_research_score_increases_for_disagreement():
    current = game(line=3.5, probability=0.55)
    score = research_score(current)
    assert score > 0
