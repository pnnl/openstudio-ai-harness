"""User-local, review-gated learning records for OpenStudio AI."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LearningStore:
    """Persist untrusted evidence and approved personal lessons separately."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS learning_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source TEXT NOT NULL,
                    workflow_id TEXT,
                    scope_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    candidate_type TEXT NOT NULL DEFAULT 'lesson',
                    summary TEXT NOT NULL,
                    guidance TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    evidence_event_ids_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL CHECK(status IN ('candidate', 'approved', 'rejected')),
                    reviewer_note TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS personal_lessons (
                    lesson_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    guidance TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approved_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS learning_events_workflow ON learning_events(workflow_id);
                CREATE INDEX IF NOT EXISTS learning_candidates_status ON learning_candidates(status);
                CREATE INDEX IF NOT EXISTS learning_candidates_type ON learning_candidates(candidate_type);
                """
            )
            self._add_column_if_missing(
                connection, "learning_candidates", "candidate_type", "TEXT NOT NULL DEFAULT 'lesson'"
            )
            self._add_column_if_missing(
                connection, "learning_candidates", "evidence_event_ids_json", "TEXT NOT NULL DEFAULT '[]'"
            )

    @staticmethod
    def _add_column_if_missing(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def capture_event(
        self,
        *,
        event_type: str,
        summary: str,
        source: str,
        workflow_id: str | None,
        scope: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(uuid4())
        created_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO learning_events
                (event_id, event_type, summary, source, workflow_id, scope_json, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, event_type, summary, source, workflow_id, json.dumps(scope, sort_keys=True),
                 json.dumps(evidence, sort_keys=True), created_at),
            )
        return self.get_event(event_id)  # type: ignore[return-value]

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM learning_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._event(row) if row else None

    def create_candidate(
        self,
        *,
        event_id: str,
        summary: str,
        guidance: str,
        tags: list[str],
        scope: dict[str, Any],
        candidate_type: str = "lesson",
        evidence_event_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.get_event(event_id) is None:
            raise KeyError(f"Unknown learning event: {event_id}")
        candidate_id = str(uuid4())
        created_at = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO learning_candidates
                (candidate_id, event_id, candidate_type, summary, guidance, tags_json, scope_json,
                 evidence_event_ids_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?)""",
                (candidate_id, event_id, candidate_type, summary, guidance, json.dumps(sorted(set(tags))),
                 json.dumps(scope, sort_keys=True), json.dumps(evidence_event_ids or [event_id]), created_at),
            )
        return self.get_candidate(candidate_id)  # type: ignore[return-value]

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM learning_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return self._candidate(row) if row else None

    def list_candidates(
        self, *, status: str | None = None, candidate_type: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM learning_candidates"
        filters: list[str] = []
        values: list[str] = []
        if status is not None:
            filters.append("status = ?")
            values.append(status)
        if candidate_type is not None:
            filters.append("candidate_type = ?")
            values.append(candidate_type)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._candidate(row) for row in rows]

    def candidate_event_sets(self, *, candidate_type: str) -> set[frozenset[str]]:
        """Return existing evidence groups for one candidate type in one query."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT evidence_event_ids_json FROM learning_candidates WHERE candidate_type = ?",
                (candidate_type,),
            ).fetchall()
        return {
            frozenset(json.loads(row["evidence_event_ids_json"])) for row in rows
        }

    def list_events(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM learning_events ORDER BY created_at ASC").fetchall()
        return [self._event(row) for row in rows]

    def prune_preview(
        self, *, candidate_days: int, rejected_days: int
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        candidates: list[dict[str, Any]] = []
        for candidate in self.list_candidates():
            if candidate["status"] == "approved":
                continue
            days = rejected_days if candidate["status"] == "rejected" else candidate_days
            created = datetime.fromisoformat(candidate["created_at"])
            if created <= now - timedelta(days=days):
                candidates.append(candidate)
        return candidates

    def prune_candidates(self, candidate_ids: list[str]) -> list[str]:
        candidates = {item["candidate_id"]: item for item in self.list_candidates()}
        protected = [item for item in candidate_ids if candidates.get(item, {}).get("status") == "approved"]
        if protected:
            raise ValueError("Approved personal lessons cannot be pruned with this command.")
        ids = [candidate_id for candidate_id in candidate_ids if candidate_id in candidates]
        with self._connect() as connection:
            connection.executemany(
                "DELETE FROM learning_candidates WHERE candidate_id = ?", [(candidate_id,) for candidate_id in ids]
            )
        return ids

    def review_candidate(
        self, *, candidate_id: str, approved: bool, reviewer_note: str | None = None
    ) -> dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown learning candidate: {candidate_id}")
        if candidate["status"] != "candidate":
            raise ValueError(f"Candidate {candidate_id} has already been reviewed.")
        now = _utc_now()
        status = "approved" if approved else "rejected"
        with self._connect() as connection:
            connection.execute(
                "UPDATE learning_candidates SET status = ?, reviewer_note = ?, reviewed_at = ? WHERE candidate_id = ?",
                (status, reviewer_note, now, candidate_id),
            )
            if approved:
                connection.execute(
                    """INSERT INTO personal_lessons
                    (lesson_id, candidate_id, summary, guidance, tags_json, scope_json, created_at, approved_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid4()), candidate_id, candidate["summary"], candidate["guidance"],
                     json.dumps(candidate["tags"]), json.dumps(candidate["scope"], sort_keys=True), now, now),
                )
        reviewed = self.get_candidate(candidate_id)
        return {"candidate": reviewed, "lesson": self.lesson_for_candidate(candidate_id)}

    def lesson_for_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM personal_lessons WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return self._lesson(row) if row else None

    def search_lessons(self, *, query: str, tags: list[str], limit: int) -> list[dict[str, Any]]:
        terms = {part.lower() for part in query.split() if len(part) > 2}
        requested_tags = {tag.lower() for tag in tags}
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM personal_lessons ORDER BY approved_at DESC").fetchall()
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            lesson = self._lesson(row)
            searchable = f"{lesson['summary']} {lesson['guidance']} {' '.join(lesson['tags'])}".lower()
            score = sum(term in searchable for term in terms)
            score += 2 * len(requested_tags.intersection({tag.lower() for tag in lesson["tags"]}))
            if score or (not terms and not requested_tags):
                scored.append((score, lesson))
        return [lesson for _, lesson in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        return {**dict(row), "scope": json.loads(row["scope_json"]), "evidence": json.loads(row["evidence_json"])}

    @staticmethod
    def _candidate(row: sqlite3.Row) -> dict[str, Any]:
        return {
            **dict(row),
            "tags": json.loads(row["tags_json"]),
            "scope": json.loads(row["scope_json"]),
            "evidence_event_ids": json.loads(row["evidence_event_ids_json"]),
        }

    @staticmethod
    def _lesson(row: sqlite3.Row) -> dict[str, Any]:
        return {**dict(row), "tags": json.loads(row["tags_json"]), "scope": json.loads(row["scope_json"])}
