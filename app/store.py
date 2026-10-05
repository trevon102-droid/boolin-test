from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AnalystNote, AnalystNoteCreate, PostgameReview, PostgameReviewCreate, ResearchGame


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA = BASE_DIR / "data" / "latest" / "games.json"


class AnalystStore:
    def __init__(self, data_path: str | None = None, db_path: str | None = None) -> None:
        self.data_path = Path(data_path or os.getenv("BOOLIN_GAMES_PATH", DEFAULT_DATA))
        self.db_path = Path(db_path or os.getenv("ANALYST_DB_PATH", BASE_DIR / "data" / "analyst.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def load_games(self) -> list[ResearchGame]:
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        return [ResearchGame.model_validate(item) for item in payload]

    def get_game(self, game_id: str) -> ResearchGame | None:
        return next((g for g in self.load_games() if g.game_id == game_id), None)

    def save_note(self, game_id: str, note: AnalystNoteCreate) -> AnalystNote:
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notes(game_id,payload,created_at,updated_at) VALUES(?,?,?,?,?)",
                (game_id, note.model_dump_json(), now.isoformat(), now.isoformat()),
            )
            note_id = int(cur.lastrowid)
        return AnalystNote(
            id=note_id,
            game_id=game_id,
            created_at=now,
            updated_at=now,
            **note.model_dump(),
        )

    def list_notes(self, game_id: str) -> list[AnalystNote]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,payload,created_at,updated_at FROM notes WHERE game_id=? ORDER BY id DESC",
                (game_id,),
            ).fetchall()

        result = []
        for row in rows:
            payload: dict[str, Any] = json.loads(row["payload"])
            result.append(
                AnalystNote(
                    id=row["id"],
                    game_id=game_id,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    **payload,
                )
            )
        return result

    def save_review(self, game_id: str, review: PostgameReviewCreate) -> PostgameReview:
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reviews(game_id,payload,created_at) VALUES(?,?,?)",
                (game_id, review.model_dump_json(), now.isoformat()),
            )
            review_id = int(cur.lastrowid)
        return PostgameReview(
            id=review_id,
            game_id=game_id,
            created_at=now,
            **review.model_dump(),
        )

    def list_reviews(self, game_id: str) -> list[PostgameReview]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id,payload,created_at FROM reviews WHERE game_id=? ORDER BY id DESC",
                (game_id,),
            ).fetchall()

        result = []
        for row in rows:
            payload: dict[str, Any] = json.loads(row["payload"])
            result.append(
                PostgameReview(
                    id=row["id"],
                    game_id=game_id,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    **payload,
                )
            )
        return result
