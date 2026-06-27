#!/usr/bin/env python3
"""
Canonical Local Memory v2 store.

Markdown files are the durable source of truth. SQLite provides metadata,
recent lookups, and FTS search. Chroma remains a rebuildable vector index.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


DEFAULT_IMPORTANCE = 0.5
DEFAULT_CONFIDENCE = 0.8
DEFAULT_STATUS = "active"
DEFAULT_EMBEDDING_STATUS = "pending"
MEMORY_START = "<!-- memory-v2"
MEMORY_END = "<!-- /memory-v2 -->"


def now_iso() -> str:
    return datetime.now().isoformat()


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def since_to_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.endswith("h") and value[:-1].isdigit():
        return (datetime.now() - timedelta(hours=int(value[:-1]))).isoformat()
    if value.endswith("d") and value[:-1].isdigit():
        return (datetime.now() - timedelta(days=int(value[:-1]))).isoformat()
    return value


def normalize_project_category(project: Optional[str], category: Optional[str]) -> tuple[str, str]:
    clean_project = (project or "general").strip() or "general"
    clean_category = (category or "general").strip() or "general"
    if ":" in clean_category:
        split_project, split_category = clean_category.split(":", 1)
        if split_project.strip() and split_category.strip():
            clean_project = split_project.strip()
            clean_category = split_category.strip()
    return clean_project, clean_category


def stable_memory_id(text: str, metadata: dict[str, Any], legacy_id: Optional[str] = None) -> str:
    if legacy_id and re.fullmatch(r"[A-Za-z0-9_-]{6,128}", legacy_id):
        return legacy_id
    raw = "|".join(
        [
            text,
            str(metadata.get("project", "")),
            str(metadata.get("category", "")),
            str(metadata.get("created_at", "")),
            str(legacy_id or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def memory_to_response(memory: "CanonicalMemory", score: float = 0.0) -> dict[str, Any]:
    metadata = memory.metadata.copy()
    metadata.update(
        {
            "project": memory.project,
            "category": memory.category,
            "source": memory.source,
            "source_ref": memory.source_ref,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            "expires_at": memory.expires_at,
            "importance": memory.importance,
            "confidence": memory.confidence,
            "status": memory.status,
            "tags": memory.tags,
            "legacy_id": memory.legacy_id,
        }
    )
    return {
        "id": memory.id,
        "memory": memory.text,
        "text": memory.text,
        "score": score,
        "metadata": metadata,
    }


@dataclass
class CanonicalMemory:
    id: str
    text: str
    project: str = "general"
    category: str = "general"
    source: str = "api"
    source_ref: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    expires_at: Optional[str] = None
    importance: float = DEFAULT_IMPORTANCE
    confidence: float = DEFAULT_CONFIDENCE
    status: str = DEFAULT_STATUS
    supersedes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    embedding_status: str = DEFAULT_EMBEDDING_STATUS
    legacy_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        expires = parse_dt(self.expires_at)
        return bool(expires and expires < datetime.now())


class MemoryStore:
    def __init__(
        self,
        root_dir: Path,
        index_path: Path,
        collection: Any = None,
        embed_func: Optional[Callable[[str], list[float]]] = None,
    ):
        self.root_dir = Path(root_dir)
        self.events_dir = self.root_dir / "events"
        self.index_path = Path(index_path)
        self.collection = collection
        self.embed_func = embed_func
        self.root_dir.mkdir(exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.index_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    project TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_ref TEXT,
                    legacy_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    importance REAL NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    supersedes TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    embedding_status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_tags (
                    memory_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (memory_id, tag)
                );
                CREATE TABLE IF NOT EXISTS memory_links (
                    memory_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    PRIMARY KEY (memory_id, relation, target_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(id UNINDEXED, text, project, category, source);
                CREATE INDEX IF NOT EXISTS idx_memories_project_created
                    ON memories(project, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_category_created
                    ON memories(category, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_source_created
                    ON memories(source, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_status_expires
                    ON memories(status, expires_at);
                """
            )

    def add_memory(
        self,
        text: str,
        project: str = "general",
        category: str = "general",
        source: str = "api",
        source_ref: Optional[str] = None,
        ttl_days: Optional[int] = None,
        importance: float = DEFAULT_IMPORTANCE,
        confidence: float = DEFAULT_CONFIDENCE,
        tags: Optional[list[str]] = None,
        supersedes: Optional[list[str]] = None,
        legacy_id: Optional[str] = None,
        created_at: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        write_markdown: bool = True,
        index_vector: bool = True,
    ) -> CanonicalMemory:
        project, category = normalize_project_category(project, category)
        created = created_at or now_iso()
        updated = now_iso()
        expires_at = None
        if ttl_days is not None:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()

        metadata = dict(metadata or {})
        metadata.pop("project", None)
        metadata.pop("category", None)
        metadata.pop("source", None)
        metadata.pop("created_at", None)
        metadata.pop("updated_at", None)
        metadata.pop("expires_at", None)
        memory_id = stable_memory_id(
            text,
            {"project": project, "category": category, "created_at": created},
            legacy_id=legacy_id,
        )
        memory = CanonicalMemory(
            id=memory_id,
            text=text,
            project=project,
            category=category,
            source=source or "api",
            source_ref=source_ref,
            created_at=created,
            updated_at=updated,
            expires_at=expires_at,
            importance=float(importance),
            confidence=float(confidence),
            status=DEFAULT_STATUS,
            supersedes=list(supersedes or []),
            tags=list(tags or []),
            embedding_status=DEFAULT_EMBEDDING_STATUS,
            legacy_id=legacy_id,
            metadata=metadata,
        )
        if index_vector:
            memory.embedding_status = self.upsert_vector(memory)
        self.upsert_sql(memory)
        if write_markdown:
            self.append_markdown(memory)
        return memory

    def upsert_sql(self, memory: CanonicalMemory) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    id, text, project, category, source, source_ref, legacy_id,
                    created_at, updated_at, expires_at, importance, confidence,
                    status, supersedes, tags, embedding_status, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text=excluded.text,
                    project=excluded.project,
                    category=excluded.category,
                    source=excluded.source,
                    source_ref=excluded.source_ref,
                    legacy_id=excluded.legacy_id,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at,
                    importance=excluded.importance,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    supersedes=excluded.supersedes,
                    tags=excluded.tags,
                    embedding_status=excluded.embedding_status,
                    metadata_json=excluded.metadata_json
                """,
                (
                    memory.id,
                    memory.text,
                    memory.project,
                    memory.category,
                    memory.source,
                    memory.source_ref,
                    memory.legacy_id,
                    memory.created_at,
                    memory.updated_at,
                    memory.expires_at,
                    memory.importance,
                    memory.confidence,
                    memory.status,
                    json.dumps(memory.supersedes, ensure_ascii=False),
                    json.dumps(memory.tags, ensure_ascii=False),
                    memory.embedding_status,
                    json.dumps(memory.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (memory.id,))
            conn.execute(
                "INSERT INTO memory_fts(id, text, project, category, source) VALUES (?, ?, ?, ?, ?)",
                (memory.id, memory.text, memory.project, memory.category, memory.source),
            )
            conn.execute("DELETE FROM memory_tags WHERE memory_id = ?", (memory.id,))
            conn.executemany(
                "INSERT OR IGNORE INTO memory_tags(memory_id, tag) VALUES (?, ?)",
                [(memory.id, tag) for tag in memory.tags],
            )

    def upsert_vector(self, memory: CanonicalMemory) -> str:
        if not self.collection or not self.embed_func:
            return "pending"
        try:
            embedding = self.embed_func(memory.text)
            metadata = {
                "project": memory.project,
                "category": memory.category,
                "source": memory.source,
                "source_ref": memory.source_ref or "",
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
                "expires_at": memory.expires_at or "",
                "status": memory.status,
                "user_id": memory.metadata.get("user_id", ""),
                "data": memory.text,
            }
            self.collection.upsert(
                ids=[memory.id],
                embeddings=[embedding],
                documents=[memory.text],
                metadatas=[metadata],
            )
            return "indexed"
        except Exception:
            return "pending"

    def append_markdown(self, memory: CanonicalMemory) -> None:
        day = (parse_dt(memory.created_at) or datetime.now()).strftime("%Y-%m-%d")
        path = self.events_dir / f"{day}.md"
        payload = asdict(memory)
        entry = (
            f"\n{MEMORY_START}\n"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
            f"-->\n\n"
            f"{memory.text.rstrip()}\n\n"
            f"{MEMORY_END}\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry)

    def row_to_memory(self, row: sqlite3.Row) -> CanonicalMemory:
        return CanonicalMemory(
            id=row["id"],
            text=row["text"],
            project=row["project"],
            category=row["category"],
            source=row["source"],
            source_ref=row["source_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            importance=row["importance"],
            confidence=row["confidence"],
            status=row["status"],
            supersedes=json.loads(row["supersedes"] or "[]"),
            tags=json.loads(row["tags"] or "[]"),
            embedding_status=row["embedding_status"],
            legacy_id=row["legacy_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def get_memory(self, memory_id: str) -> Optional[CanonicalMemory]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self.row_to_memory(row) if row else None

    def recent(
        self,
        project: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 20,
        include_expired: bool = False,
    ) -> list[CanonicalMemory]:
        query = "SELECT * FROM memories WHERE status = 'active'"
        params: list[Any] = []
        if project:
            query += " AND project = ?"
            params.append(project)
        if category:
            query += " AND category = ?"
            params.append(category)
        if source:
            query += " AND source = ?"
            params.append(source)
        since_iso = since_to_iso(since)
        if since_iso:
            query += " AND created_at >= ?"
            params.append(since_iso)
        if not include_expired:
            query += " AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?)"
            params.append(now_iso())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self.row_to_memory(row) for row in rows]

    def search(
        self,
        query_text: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 5,
        include_expired: bool = False,
    ) -> list[tuple[CanonicalMemory, float]]:
        candidate_scores: dict[str, dict[str, float]] = {}
        vector_scores = self.vector_search(query_text, limit=max(limit * 8, 40))
        for memory_id, score in vector_scores.items():
            candidate_scores.setdefault(memory_id, {})["vector"] = score
        fts_scores = self.fts_search(query_text, limit=max(limit * 8, 40))
        for memory_id, score in fts_scores.items():
            candidate_scores.setdefault(memory_id, {})["bm25"] = score

        filtered: list[tuple[CanonicalMemory, float]] = []
        for memory_id, scores in candidate_scores.items():
            memory = self.get_memory(memory_id)
            if not memory:
                continue
            if not self.matches_filters(memory, project, category, source, since, include_expired):
                continue
            score = self.rank_score(memory, scores, project, category, source)
            filtered.append((memory, score))

        filtered.sort(key=lambda item: item[1], reverse=True)
        return filtered[:limit]

    def matches_filters(
        self,
        memory: CanonicalMemory,
        project: Optional[str],
        category: Optional[str],
        source: Optional[str],
        since: Optional[str],
        include_expired: bool,
    ) -> bool:
        if memory.status != "active":
            return False
        if project and memory.project != project:
            return False
        if category and memory.category != category:
            return False
        if source and memory.source != source:
            return False
        since_iso = since_to_iso(since)
        if since_iso and memory.created_at < since_iso:
            return False
        if not include_expired and memory.is_expired:
            return False
        return True

    def fts_search(self, query_text: str, limit: int) -> dict[str, float]:
        fts_query = self.make_fts_query(query_text)
        if not fts_query:
            return {}
        try:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, bm25(memory_fts) AS rank
                    FROM memory_fts
                    WHERE memory_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return {}
        raw_ranks = [abs(float(row["rank"])) for row in rows]
        max_rank = max(raw_ranks) if raw_ranks else 1.0
        scores: dict[str, float] = {}
        for row in rows:
            rank = abs(float(row["rank"]))
            scores[row["id"]] = rank / max_rank if max_rank else 0.0
        return scores

    def vector_search(self, query_text: str, limit: int) -> dict[str, float]:
        if not self.collection or not self.embed_func:
            return {}
        try:
            embedding = self.embed_func(query_text)
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=limit,
                include=["distances"],
            )
        except Exception:
            return {}
        scores: dict[str, float] = {}
        ids = results.get("ids", [[]])[0] if results.get("ids") else []
        distances = results.get("distances", [[]])[0] if results.get("distances") else []
        for idx, memory_id in enumerate(ids):
            distance = float(distances[idx]) if idx < len(distances) else 1.0
            scores[memory_id] = 1.0 / (1.0 + max(distance, 0.0))
        return scores

    def rank_score(
        self,
        memory: CanonicalMemory,
        scores: dict[str, float],
        project: Optional[str],
        category: Optional[str],
        source: Optional[str],
    ) -> float:
        vector = scores.get("vector", 0.0)
        bm25 = scores.get("bm25", 0.0)
        recency = self.recency_score(memory.created_at)
        exact = 0.0
        if project and memory.project == project:
            exact += 0.04
        if category and memory.category == category:
            exact += 0.03
        if source and memory.source == source:
            exact += 0.03
        return (0.45 * vector) + (0.30 * bm25) + (0.15 * recency) + exact

    def recency_score(self, created_at: str) -> float:
        created = parse_dt(created_at)
        if not created:
            return 0.0
        age_days = max((datetime.now() - created).total_seconds() / 86400, 0)
        return math.exp(-age_days / 30)

    def context_pack(self, project: str, workflow: str = "default", limit: int = 20) -> dict[str, Any]:
        recent = self.recent(project=project, since="72h", limit=limit)
        open_loops = self.search(
            "open loop priority blocker next tomorrow decision follow-up",
            project=project,
            limit=limit,
        )
        durable = self.search(
            "preference pattern decision learning voice style relationship career signal",
            project=project,
            limit=limit,
        )
        sections = {
            "recent_72h": [memory_to_response(m) for m in recent],
            "open_loops": [memory_to_response(m, s) for m, s in open_loops],
            "durable_patterns": [memory_to_response(m, s) for m, s in durable],
        }
        if workflow == "nightly":
            nightly = self.search(
                "nightly work insight decision pattern emotional insight health routine career signal",
                project=project,
                limit=limit,
            )
            sections["nightly_signals"] = [memory_to_response(m, s) for m, s in nightly]

        lines = []
        for name, rows in sections.items():
            if not rows:
                continue
            lines.append(f"## {name}")
            for row in rows[:limit]:
                meta = row["metadata"]
                date = str(meta.get("created_at", ""))[:10]
                lines.append(
                    f"- [{date} {meta.get('project')}:{meta.get('category')}] {row['memory']}"
                )
            lines.append("")
        return {
            "project": project,
            "workflow": workflow,
            "sections": sections,
            "context": "\n".join(lines).strip(),
            "count": sum(len(rows) for rows in sections.values()),
        }

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            active = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
            by_category = {
                row["category"]: row["count"]
                for row in conn.execute(
                    "SELECT category, COUNT(*) AS count FROM memories GROUP BY category ORDER BY count DESC"
                ).fetchall()
            }
            by_project = {
                row["project"]: row["count"]
                for row in conn.execute(
                    "SELECT project, COUNT(*) AS count FROM memories GROUP BY project ORDER BY count DESC"
                ).fetchall()
            }
        return {
            "total_memories": total,
            "active_memories": active,
            "by_category": by_category,
            "by_project": by_project,
        }

    def expired(self, limit: int = 50) -> list[CanonicalMemory]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM memories
                WHERE expires_at IS NOT NULL
                  AND expires_at != ''
                  AND expires_at <= ?
                ORDER BY expires_at DESC
                LIMIT ?
                """,
                (now_iso(), limit),
            ).fetchall()
        return [self.row_to_memory(row) for row in rows]

    def archive_expired(self, dry_run: bool = False) -> dict[str, Any]:
        expired = self.expired(limit=100000)
        by_category = Counter(memory.category for memory in expired)
        if not dry_run and expired:
            ids = [(now_iso(), memory.id) for memory in expired]
            with self.connect() as conn:
                conn.executemany(
                    "UPDATE memories SET status = 'archived', updated_at = ? WHERE id = ?",
                    ids,
                )
        total_after = self.stats()["active_memories"]
        return {
            "status": "dry_run" if dry_run else "success",
            "pruned_count": len(expired),
            "total_before": total_after + (0 if dry_run else len(expired)),
            "total_after": total_after,
            "by_category": dict(by_category),
        }

    def schema_audit(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            colon_categories = conn.execute(
                "SELECT id, category FROM memories WHERE category LIKE '%:%' LIMIT 50"
            ).fetchall()
            missing_text = conn.execute("SELECT COUNT(*) FROM memories WHERE trim(text) = ''").fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE expires_at IS NOT NULL AND expires_at != '' AND expires_at <= ?",
                (now_iso(),),
            ).fetchone()[0]
            duplicate_rows = conn.execute(
                """
                SELECT text, COUNT(*) AS count
                FROM memories
                GROUP BY text
                HAVING count > 1
                ORDER BY count DESC
                LIMIT 20
                """
            ).fetchall()
            pending_embeddings = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE embedding_status != 'indexed'"
            ).fetchone()[0]
        return {
            "total_memories": total,
            "colon_categories": [dict(row) for row in colon_categories],
            "missing_text_count": missing_text,
            "expired_count": expired,
            "duplicate_candidates": [
                {"text": row["text"][:160], "count": row["count"]} for row in duplicate_rows
            ],
            "pending_embeddings": pending_embeddings,
        }

    def rebuild_from_markdown(self, rebuild_vectors: bool = True) -> dict[str, Any]:
        memories = list(self.read_markdown_memories())
        with self.connect() as conn:
            conn.executescript(
                """
                DELETE FROM memories;
                DELETE FROM memory_tags;
                DELETE FROM memory_links;
                DELETE FROM memory_fts;
                """
            )
        if rebuild_vectors and self.collection:
            try:
                existing = self.collection.get()
                ids = existing.get("ids") or []
                for index in range(0, len(ids), 500):
                    self.collection.delete(ids=ids[index:index + 500])
            except Exception:
                pass
        indexed = 0
        for memory in memories:
            if rebuild_vectors:
                memory.embedding_status = self.upsert_vector(memory)
            self.upsert_sql(memory)
            indexed += 1
        return {"status": "success", "indexed": indexed, "vectors": rebuild_vectors}

    def read_markdown_memories(self) -> Iterable[CanonicalMemory]:
        pattern = re.compile(
            re.escape(MEMORY_START) + r"\n(.*?)\n-->\n\n(.*?)\n\n" + re.escape(MEMORY_END),
            re.DOTALL,
        )
        for path in sorted(self.events_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                payload = json.loads(match.group(1))
                payload["text"] = payload.get("text") or match.group(2)
                yield CanonicalMemory(**payload)

    def make_fts_query(self, query_text: str) -> str:
        tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", query_text.lower())
        if not tokens:
            return ""
        tokens = tokens[:12]
        return " OR ".join(f'"{token}"' for token in tokens)


def chroma_where_filter(
    project: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    clauses = []
    if project:
        clauses.append({"project": project})
    if category:
        clauses.append({"category": category})
    if source:
        clauses.append({"source": source})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}
