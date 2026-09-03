from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp for registry records."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    kind: str
    path: str
    status: str
    created_at: str
    updated_at: str
    last_accessed_at: str
    job_id: str | None
    model_id: str | None
    artifact_id: str | None
    size_bytes: int
    pinned: bool
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeStateStore:
    """SQLite-backed local registry for MCP artifacts, jobs, and workspaces.

    The registry stores metadata only. Heavy files such as OSM, SQL, and logs
    remain on disk under the workspace root and are pruned through registry
    decisions.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    parent_id TEXT,
                    kind TEXT NOT NULL,
                    tool_trace_id TEXT,
                    job_id TEXT,
                    workspace_id TEXT,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    job_id TEXT,
                    model_id TEXT,
                    artifact_id TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    run_mode TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    warnings_count INTEGER NOT NULL DEFAULT 0,
                    severe_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    error_json TEXT
                );

                CREATE TABLE IF NOT EXISTS blackboard_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL
                );
                """)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
            }
            needs_backfill = False
            if "job_id" not in columns:
                conn.execute("ALTER TABLE artifacts ADD COLUMN job_id TEXT")
                needs_backfill = True
            if "workspace_id" not in columns:
                conn.execute("ALTER TABLE artifacts ADD COLUMN workspace_id TEXT")
                needs_backfill = True
            conn.execute(
                "CREATE INDEX IF NOT EXISTS artifacts_available_job_id "
                "ON artifacts(status, job_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS artifacts_available_workspace_id "
                "ON artifacts(status, workspace_id)"
            )
            if needs_backfill:
                legacy_artifacts = conn.execute(
                    "SELECT artifact_id, metadata_json FROM artifacts"
                ).fetchall()
                for artifact in legacy_artifacts:
                    metadata = json.loads(artifact["metadata_json"])
                    conn.execute(
                        "UPDATE artifacts SET job_id = ?, workspace_id = ? "
                        "WHERE artifact_id = ?",
                        (
                            metadata.get("job_id"),
                            metadata.get("workspace_id"),
                            artifact["artifact_id"],
                        ),
                    )

    def upsert_artifact(
        self,
        *,
        artifact_id: str,
        created_at: str,
        parent_id: str | None,
        kind: str,
        tool_trace_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        job_id = metadata.get("job_id")
        workspace_id = metadata.get("workspace_id")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, created_at, parent_id, kind, tool_trace_id, job_id,
                    workspace_id,
                    metadata_json, status, pinned, last_accessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', 0, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    kind = excluded.kind,
                    tool_trace_id = excluded.tool_trace_id,
                    job_id = excluded.job_id,
                    workspace_id = excluded.workspace_id,
                    metadata_json = excluded.metadata_json,
                    last_accessed_at = excluded.last_accessed_at
                """,
                (
                    artifact_id,
                    created_at,
                    parent_id,
                    kind,
                    tool_trace_id,
                    job_id if isinstance(job_id, str) else None,
                    workspace_id if isinstance(workspace_id, str) else None,
                    json.dumps(metadata, sort_keys=True),
                    utc_now(),
                ),
            )

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return self._artifact_row_to_dict(row) if row else None

    def touch_artifact(self, artifact_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET last_accessed_at = ? WHERE artifact_id = ?",
                (utc_now(), artifact_id),
            )

    def mark_artifact_status(self, artifact_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET status = ?, last_accessed_at = ? WHERE artifact_id = ?",
                (status, utc_now(), artifact_id),
            )

    def pin_artifact(self, artifact_id: str, pinned: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET pinned = ?, last_accessed_at = ? WHERE artifact_id = ?",
                (1 if pinned else 0, utc_now(), artifact_id),
            )

    def upsert_workspace(
        self,
        *,
        workspace_id: str,
        kind: str,
        path: str | Path,
        job_id: str | None = None,
        model_id: str | None = None,
        artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        size_bytes: int = 0,
    ) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, kind, path, status, created_at, updated_at,
                    last_accessed_at, job_id, model_id, artifact_id, size_bytes,
                    pinned, metadata_json
                )
                VALUES (?, ?, ?, 'available', ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    kind = excluded.kind,
                    path = excluded.path,
                    updated_at = excluded.updated_at,
                    last_accessed_at = excluded.last_accessed_at,
                    job_id = excluded.job_id,
                    model_id = excluded.model_id,
                    artifact_id = excluded.artifact_id,
                    size_bytes = excluded.size_bytes,
                    metadata_json = excluded.metadata_json
                """,
                (
                    workspace_id,
                    kind,
                    str(Path(path).resolve()),
                    now,
                    now,
                    now,
                    job_id,
                    model_id,
                    artifact_id,
                    size_bytes,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )

    def touch_workspace(
        self, workspace_id: str, *, size_bytes: int | None = None
    ) -> None:
        assignments = ["last_accessed_at = ?", "updated_at = ?"]
        values: list[Any] = [utc_now(), utc_now()]
        if size_bytes is not None:
            assignments.append("size_bytes = ?")
            values.append(size_bytes)
        values.append(workspace_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE workspaces SET {', '.join(assignments)} WHERE workspace_id = ?",
                values,
            )

    def update_workspace_artifact(self, workspace_id: str, artifact_id: str) -> None:
        """Link the primary artifact for an existing workspace record."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workspaces
                SET artifact_id = ?, updated_at = ?, last_accessed_at = ?
                WHERE workspace_id = ?
                """,
                (artifact_id, utc_now(), utc_now(), workspace_id),
            )

    def mark_workspace_status(self, workspace_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workspaces
                SET status = ?, updated_at = ?, last_accessed_at = ?
                WHERE workspace_id = ?
                """,
                (status, utc_now(), utc_now(), workspace_id),
            )

    def list_workspaces(self) -> list[WorkspaceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workspaces ORDER BY created_at"
            ).fetchall()
        return [self._workspace_row_to_record(row) for row in rows]

    def upsert_job(
        self,
        *,
        job_id: str,
        model_id: str,
        run_mode: str,
        options: dict[str, Any],
        state: str,
        progress: int,
        warnings_count: int,
        severe_count: int,
        created_at: str,
        updated_at: str,
        artifacts: dict[str, str],
        error: dict[str, Any] | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, model_id, run_mode, options_json, state, progress,
                    warnings_count, severe_count, created_at, updated_at,
                    artifacts_json, error_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    model_id = excluded.model_id,
                    run_mode = excluded.run_mode,
                    options_json = excluded.options_json,
                    state = excluded.state,
                    progress = excluded.progress,
                    warnings_count = excluded.warnings_count,
                    severe_count = excluded.severe_count,
                    updated_at = excluded.updated_at,
                    artifacts_json = excluded.artifacts_json,
                    error_json = excluded.error_json
                """,
                (
                    job_id,
                    model_id,
                    run_mode,
                    json.dumps(options, sort_keys=True),
                    state,
                    progress,
                    warnings_count,
                    severe_count,
                    created_at,
                    updated_at,
                    json.dumps(artifacts, sort_keys=True),
                    json.dumps(error, sort_keys=True) if error is not None else None,
                ),
            )

    def get_job_artifact_ids(self, job_id: str) -> set[str]:
        """Return all artifact IDs recorded for a simulation job."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT artifacts_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return set()
        artifacts = json.loads(row["artifacts_json"])
        return {
            artifact_id
            for artifact_id in artifacts.values()
            if isinstance(artifact_id, str)
        }

    def get_artifact_ids_for_job(self, job_id: str) -> set[str]:
        """Return available artifact IDs indexed to a simulation job."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT artifact_id FROM artifacts WHERE status = 'available' AND job_id = ?",
                (job_id,),
            ).fetchall()
        return {row["artifact_id"] for row in rows}

    def get_artifact_ids_for_workspace(self, workspace_id: str) -> set[str]:
        """Return available artifact IDs indexed to a workspace."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT artifact_id FROM artifacts "
                "WHERE status = 'available' AND workspace_id = ?",
                (workspace_id,),
            ).fetchall()
        return {row["artifact_id"] for row in rows}

    def workspace_usage(self) -> dict[str, Any]:
        records = self.list_workspaces()
        by_kind: dict[str, dict[str, int]] = {}
        for record in records:
            bucket = by_kind.setdefault(record.kind, {"count": 0, "size_bytes": 0})
            bucket["count"] += 1
            bucket["size_bytes"] += record.size_bytes
        return {
            "db_path": str(self.db_path),
            "workspace_count": len(records),
            "total_size_bytes": sum(record.size_bytes for record in records),
            "by_kind": by_kind,
            "workspaces": [record.to_dict() for record in records],
        }

    def upsert_blackboard_workflow(self, state: dict[str, Any]) -> None:
        """Persist a workflow state document in the MCP blackboard table."""
        workflow_id = str(state["workflow_id"])
        now = utc_now()
        created_at = str(state.get("created_at") or now)
        updated_at = str(state.get("updated_at") or now)
        status = str(state.get("status") or "active")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO blackboard_workflows (
                    workflow_id, state_json, status, created_at, updated_at,
                    last_accessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    last_accessed_at = excluded.last_accessed_at
                """,
                (
                    workflow_id,
                    json.dumps(state, sort_keys=True),
                    status,
                    created_at,
                    updated_at,
                    now,
                ),
            )

    def get_blackboard_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        """Load one MCP blackboard workflow state document."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT state_json
                FROM blackboard_workflows
                WHERE workflow_id = ?
                """,
                (workflow_id,),
            ).fetchone()
            if row is not None:
                conn.execute(
                    """
                    UPDATE blackboard_workflows
                    SET last_accessed_at = ?
                    WHERE workflow_id = ?
                    """,
                    (utc_now(), workflow_id),
                )
        if row is None:
            return None
        loaded = json.loads(row["state_json"])
        return loaded if isinstance(loaded, dict) else None

    def list_blackboard_workflows(self) -> list[dict[str, Any]]:
        """Return lightweight metadata for MCP blackboard workflows."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT workflow_id, status, created_at, updated_at, last_accessed_at
                FROM blackboard_workflows
                ORDER BY updated_at DESC
                """).fetchall()
        return [
            {
                "workflow_id": row["workflow_id"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_accessed_at": row["last_accessed_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _artifact_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "artifact_id": row["artifact_id"],
            "created_at": row["created_at"],
            "parent_id": row["parent_id"],
            "kind": row["kind"],
            "tool_trace_id": row["tool_trace_id"],
            "metadata": json.loads(row["metadata_json"]),
            "status": row["status"],
            "pinned": bool(row["pinned"]),
            "last_accessed_at": row["last_accessed_at"],
        }

    @staticmethod
    def _workspace_row_to_record(row: sqlite3.Row) -> WorkspaceRecord:
        return WorkspaceRecord(
            workspace_id=row["workspace_id"],
            kind=row["kind"],
            path=row["path"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            job_id=row["job_id"],
            model_id=row["model_id"],
            artifact_id=row["artifact_id"],
            size_bytes=int(row["size_bytes"]),
            pinned=bool(row["pinned"]),
            metadata=json.loads(row["metadata_json"]),
        )
