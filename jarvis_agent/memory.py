from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def _default_db_path() -> Path:
    configured = os.getenv("JARVIS_MEMORY_DB_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path.resolve()
    local = os.getenv("LOCALAPPDATA", "").strip()
    if local:
        root = Path(local) / "JarvisPersonal"
    else:
        root = Path.home() / ".jarvis_personal"
    root.mkdir(parents=True, exist_ok=True)
    return root / "memory.sqlite3"


def _fold(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(text).casefold())
        if not unicodedata.combining(char)
    )


_QUESTION_WORDS = set("""
quel quelle quels quelles que quoi qui est ce cet cette ces de du des le la les
un une mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs je tu il
elle nous vous ils elles sur dans avec pour et ou au aux me te se moi toi
rappelle rappelles souviens comment appelle appellent appele appelee appeler nom noms
peux pouvez pourrais pourrait veux voudrais dire dit dis donne donner rappellez
sais savez souvenir souvient s y en ai as a avait avait ete etre bien deja
remember recall what which the an of about my your how does do is are was were
can could would you tell me please called named name have has it this that
ما ماذا كيف هو هي في من عن هل اسم يسمى تذكر اتذكر
""".split())


def search_terms(query: str) -> list[str]:
    """Keep significant Unicode terms; all retained terms must still match."""
    words = re.findall(r"[^\W_]+", _fold(query or ""), flags=re.UNICODE)
    return list(dict.fromkeys(
        word for word in words if len(word) >= 2 and word not in _QUESTION_WORDS
    ))[:8]


@dataclass(frozen=True)
class MemoryItem:
    id: int
    content: str
    tags: str
    created_at: str


class LocalMemory:
    """Small local-first persistent memory.

    V2 intentionally starts with explicit text memory and SQLite. Semantic
    embeddings can be added later without changing the agent tool contract.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        try:
            conn.create_function("memory_fold", 1, _fold, deterministic=True)
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_created_at "
                "ON memories(created_at)"
            )

    def remember(self, content: str, *, tags: str = "") -> MemoryItem:
        text = (content or "").strip()
        if not text:
            raise ValueError("memory content is empty")

        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memories(content, tags, created_at) VALUES (?, ?, ?)",
                (text, (tags or "").strip(), created_at),
            )
            memory_id = int(cursor.lastrowid)

        return MemoryItem(
            id=memory_id,
            content=text,
            tags=(tags or "").strip(),
            created_at=created_at,
        )

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        text = (query or "").strip()
        if not text:
            return []

        words = search_terms(text)
        if not words:
            return []

        clauses = []
        params: list[str | int] = []
        for word in words[:8]:
            clauses.append(
                "(memory_fold(content) LIKE ? OR memory_fold(tags) LIKE ?)"
            )
            like = f"%{word}%"
            params.extend([like, like])

        sql = (
            "SELECT id, content, tags, created_at FROM memories WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id DESC LIMIT ?"
        )
        params.append(max(1, min(int(limit), 20)))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            MemoryItem(
                id=int(row[0]),
                content=str(row[1]),
                tags=str(row[2]),
                created_at=str(row[3]),
            )
            for row in rows
        ]

    def get(self, memory_id: int) -> MemoryItem | None:
        """Read through a fresh connection, including after a process restart."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, content, tags, created_at FROM memories WHERE id=?",
                (int(memory_id),),
            ).fetchone()
        return MemoryItem(int(row[0]), str(row[1]), str(row[2]), str(row[3])) if row else None


LOCAL_MEMORY = LocalMemory()
