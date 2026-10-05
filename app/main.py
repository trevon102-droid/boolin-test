from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from .engine import compare_market_model, detect_changes, research_score
from .models import AnalystNote, AnalystNoteCreate, PostgameReview, PostgameReviewCreate, ResearchBoardItem, ResearchGame
from .store import AnalystStore


app = FastAPI(
    title="Boolin Analyst API",
    version="0.1.0",
    description="Research-first sports analysis API for Boolin.",
    docs_url="/docs",
    redoc_url="/redoc",
)


store = AnalystStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/games", response_model=list[ResearchGame])
def list_games(league: str | None = Query(default=None)) -> list[ResearchGame]:
    games = store.load_games()
    if league:
        games = [g for g in games if g.league.lower() == league.lower()]
    return games


@app.get("/games/{game_id}", response_model=ResearchGame)
def get_game(game_id: str) -> ResearchGame:
    game = store.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@app.get("/games/{game_id}/research")
def get_research(game_id: str) -> dict:
    game = get_game(game_id)
    comparison = compare_market_model(game)
    return {
        "game": game,
        "market_vs_model": comparison,
        "supporting_evidence": game.summary_supporting,
        "contradicting_evidence": game.summary_contradicting,
        "unknowns": game.unknowns,
        "flags": game.flags,
        "scenarios": game.scenarios,
        "decision": game.decision,
    }


@app.get("/games/{game_id}/market-history")
def get_market_history(game_id: str) -> list[dict]:
    game = get_game(game_id)
    return [m.model_dump(mode="json") for m in sorted(game.market, key=lambda x: x.timestamp)]


@app.get("/games/{game_id}/changes")
def get_changes(game_id: str) -> list[dict]:
    games = store.load_games()
    current = next((g for g in games if g.game_id == game_id), None)
    if not current:
        raise HTTPException(status_code=404, detail="Game not found")

    previous = next(
        (g for g in games if g.game_id == f"{game_id}:previous"),
        None,
    )
    if not previous:
        return []

    return [c.model_dump(mode="json") for c in detect_changes(previous, current)]


@app.get("/games/{game_id}/compare")
def get_compare(game_id: str) -> dict:
    game = get_game(game_id)
    return compare_market_model(game)


@app.get("/games/{game_id}/notes", response_model=list[AnalystNote])
def list_notes(game_id: str) -> list[AnalystNote]:
    get_game(game_id)
    return store.list_notes(game_id)


@app.post("/games/{game_id}/notes", response_model=AnalystNote, status_code=201)
def create_note(game_id: str, note: AnalystNoteCreate) -> AnalystNote:
    get_game(game_id)
    return store.save_note(game_id, note)


@app.get("/games/{game_id}/reviews", response_model=list[PostgameReview])
def list_reviews(game_id: str) -> list[PostgameReview]:
    get_game(game_id)
    return store.list_reviews(game_id)


@app.post("/games/{game_id}/reviews", response_model=PostgameReview, status_code=201)
def create_review(game_id: str, review: PostgameReviewCreate) -> PostgameReview:
    get_game(game_id)
    return store.save_review(game_id, review)


@app.get("/research-board", response_model=list[ResearchBoardItem])
def research_board() -> list[ResearchBoardItem]:
    games = store.load_games()
    board: list[ResearchBoardItem] = []

    for game in games:
        score = research_score(game)
        reasons: list[str] = []
        if game.flags:
            reasons.extend(flag.title for flag in game.flags)
        comparison = compare_market_model(game)
        if abs(comparison.get("probability_delta", 0)) >= 0.05:
            reasons.append("Model/market probability disagreement")
        if abs(comparison.get("spread_delta", 0)) >= 1.5:
            reasons.append("Large model/market spread disagreement")
        if not reasons:
            reasons.append("No major research trigger detected")

        board.append(
            ResearchBoardItem(
                game_id=game.game_id,
                matchup=f"{game.away_team} @ {game.home_team}",
                research_score=score,
                reasons=reasons[:6],
                flags=[flag.code for flag in game.flags],
                start_time=game.start_time,
            )
        )

    return sorted(board, key=lambda x: (-x.research_score, x.start_time))


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "Boolin Analyst", "docs": "/docs", "openapi": "/openapi.json"}
