from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .task_graph import MissionTaskGraph


def _default_path() -> Path:
    root = Path(
        os.getenv("LOCALAPPDATA")
        or os.getenv("XDG_STATE_HOME")
        or Path.home()
    )
    return root / "JarvisPersonal" / "task_graphs.sqlite3"


class TaskGraphStore:
    """Persistent DAG state for long-running mission pause/resume."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mission_task_graphs (
                    mission_id TEXT PRIMARY KEY,
                    graph_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _serialize(graph: MissionTaskGraph) -> str:
        return json.dumps(
            graph.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def save(self, graph: MissionTaskGraph) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mission_task_graphs (
                    mission_id, graph_json, updated_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(mission_id) DO UPDATE SET
                    graph_json=excluded.graph_json,
                    updated_at=excluded.updated_at
                """,
                (
                    graph.mission_id,
                    self._serialize(graph),
                    time.time(),
                ),
            )

    def load(self, mission_id: str) -> MissionTaskGraph | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT graph_json
                FROM mission_task_graphs
                WHERE mission_id=?
                """,
                (str(mission_id),),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(row["graph_json"] or "{}")
        raw.setdefault("mission_id", str(mission_id))
        return MissionTaskGraph.from_dict(raw)

    def delete(self, mission_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM mission_task_graphs WHERE mission_id=?",
                (str(mission_id),),
            )
            return cursor.rowcount > 0
