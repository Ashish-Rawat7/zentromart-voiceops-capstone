from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    """SQLite-backed session state for a single-instance capstone deployment."""

    def __init__(
        self,
        db_path: Path | None = None,
        ttl_hours: int | None = None,
    ):
        self.db_path = Path(db_path or settings.session_db_path)
        self.ttl_hours = ttl_hours or settings.session_ttl_hours
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Manage the transaction and always close the SQLite connection."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions(updated_at)
                """
            )

    @staticmethod
    def default_state() -> dict:
        return {
            "pending_order_id": None,
            "verified_order_id": None,
            "verified": False,
            "verification_attempts": 0,
            "verification_locked": False,
            "verified_order_details": {},
            "last_intent": None,
            "pending_intent": None,
        }

    def get(self, session_id: str) -> dict:
        cutoff = (
            _now() - timedelta(hours=self.ttl_hours)
        ).isoformat()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT state_json
                FROM sessions
                WHERE session_id = ? AND updated_at >= ?
                """,
                (session_id, cutoff),
            ).fetchone()

        if not row:
            return self.default_state()

        try:
            state = json.loads(row["state_json"])
            default = self.default_state()

            if not isinstance(state, dict):
                return default

            default.update(state)
            return default

        except (json.JSONDecodeError, TypeError):
            return self.default_state()

    def save(self, session_id: str, state: dict) -> None:
        # Persist only approved session state.
        safe = {
            "pending_order_id": state.get("pending_order_id"),
            "verified_order_id": state.get("verified_order_id"),
            "verified": bool(state.get("verified", False)),
            "verification_attempts": min(
                2,
                max(0, int(state.get("verification_attempts", 0))),
            ),
            "verification_locked": bool(
                state.get("verification_locked", False)
            ),
            "verified_order_details": (
                state.get("verified_order_details")
                if isinstance(state.get("verified_order_details"), dict)
                else {}
            ),
            "last_intent": state.get("last_intent"),
            "pending_intent": state.get("pending_intent"),
        }

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, state_json, updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    json.dumps(safe, ensure_ascii=False),
                    _now().isoformat(),
                ),
            )

    def cleanup_expired(self) -> None:
        cutoff = (
            _now() - timedelta(hours=self.ttl_hours)
        ).isoformat()

        with self._connection() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE updated_at < ?",
                (cutoff,),
            )
