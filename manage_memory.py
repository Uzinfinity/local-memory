#!/usr/bin/env python3
"""Admin CLI for Local Memory v2."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
import ollama
from chromadb.config import Settings

from config import CHROMA_PATH, MEMORY_DIR, MEMORY_INDEX_PATH, USER_ID
from memory_store import (
    CanonicalMemory,
    MemoryStore,
    memory_to_response,
    normalize_project_category,
    now_iso,
    parse_dt,
    stable_memory_id,
)

COLLECTION_NAME = "local_memory"


def get_collection():
    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(name=COLLECTION_NAME)


def get_embedding(text: str) -> list[float]:
    response = ollama.embeddings(model="nomic-embed-text", prompt=text)
    return response["embedding"]


def get_store(with_vectors: bool = False) -> MemoryStore:
    collection = get_collection() if with_vectors else None
    embed_func = get_embedding if with_vectors else None
    return MemoryStore(
        root_dir=MEMORY_DIR,
        index_path=MEMORY_INDEX_PATH,
        collection=collection,
        embed_func=embed_func,
    )


def load_chroma_rows() -> list[dict[str, Any]]:
    collection = get_collection()
    results = collection.get(include=["documents", "metadatas"])
    rows = []
    ids = results.get("ids") or []
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    for idx, legacy_id in enumerate(ids):
        metadata = metadatas[idx] if idx < len(metadatas) and metadatas[idx] else {}
        document = documents[idx] if idx < len(documents) else ""
        text = document or metadata.get("data", "")
        rows.append({"legacy_id": legacy_id, "text": text or "", "metadata": metadata})
    return rows


def row_to_memory(row: dict[str, Any]) -> CanonicalMemory:
    metadata = dict(row["metadata"] or {})
    project, category = normalize_project_category(
        metadata.get("project", "general"),
        metadata.get("category", "general"),
    )
    created_at = metadata.get("created_at") or now_iso()
    updated_at = metadata.get("updated_at") or created_at
    source = metadata.get("source") or "legacy_chroma"
    memory_id = stable_memory_id(
        row["text"],
        {"project": project, "category": category, "created_at": created_at},
        legacy_id=row["legacy_id"],
    )
    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    if not isinstance(tags, list):
        tags = []
    clean_metadata = {
        key: value
        for key, value in metadata.items()
        if key
        not in {
            "project",
            "category",
            "source",
            "source_ref",
            "created_at",
            "updated_at",
            "expires_at",
            "data",
            "chroma:document",
            "tags",
        }
    }
    clean_metadata["user_id"] = clean_metadata.get("user_id") or USER_ID
    return CanonicalMemory(
        id=memory_id,
        text=row["text"],
        project=project,
        category=category,
        source=source,
        source_ref=metadata.get("source_ref"),
        created_at=created_at,
        updated_at=updated_at,
        expires_at=metadata.get("expires_at") or None,
        importance=float(metadata.get("importance", 0.5) or 0.5),
        confidence=float(metadata.get("confidence", 0.8) or 0.8),
        status=metadata.get("status") or "active",
        supersedes=[],
        tags=tags,
        embedding_status="indexed",
        legacy_id=row["legacy_id"],
        metadata=clean_metadata,
    )


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_project = Counter()
    by_category = Counter()
    malformed = []
    missing_metadata = 0
    missing_text = 0
    expired = 0
    duplicate_text = Counter()

    for row in rows:
        metadata = row["metadata"] or {}
        if not metadata:
            missing_metadata += 1
        if not row["text"].strip():
            missing_text += 1
        project, category = normalize_project_category(
            metadata.get("project", "general"),
            metadata.get("category", "general"),
        )
        by_project[project] += 1
        by_category[category] += 1
        if ":" in category:
            malformed.append({"legacy_id": row["legacy_id"], "category": category})
        expires = parse_dt(metadata.get("expires_at"))
        if expires and expires < datetime.now():
            expired += 1
        if row["text"].strip():
            duplicate_text[row["text"].strip()] += 1

    duplicates = [
        {"text": text[:160], "count": count}
        for text, count in duplicate_text.most_common(20)
        if count > 1
    ]
    return {
        "source_count": len(rows),
        "by_project": dict(by_project.most_common()),
        "by_category": dict(by_category.most_common()),
        "malformed_categories": malformed[:50],
        "missing_metadata_count": missing_metadata,
        "missing_text_count": missing_text,
        "expired_count": expired,
        "duplicate_candidates": duplicates,
    }


def write_audit_report(payload: dict[str, Any], prefix: str) -> Path:
    audit_dir = MEMORY_DIR / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def backfill(apply: bool) -> dict[str, Any]:
    rows = load_chroma_rows()
    summary = summarize_rows(rows)
    if not apply:
        summary["status"] = "dry_run"
        return summary

    store = get_store(with_vectors=False)
    imported = 0
    existing = 0
    skipped_missing_text = 0
    for row in rows:
        if not row["text"].strip():
            skipped_missing_text += 1
            continue
        memory = row_to_memory(row)
        already_exists = store.get_memory(memory.id) is not None
        store.upsert_sql(memory)
        if already_exists:
            existing += 1
        else:
            store.append_markdown(memory)
            imported += 1

    summary.update(
        {
            "status": "applied",
            "imported": imported,
            "existing": existing,
            "skipped_missing_text": skipped_missing_text,
        }
    )
    summary["audit_report"] = str(write_audit_report(summary, "backfill"))
    return summary


def cmd_backfill(args: argparse.Namespace) -> None:
    result = backfill(apply=args.apply)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_audit(_: argparse.Namespace) -> None:
    store = get_store(with_vectors=False)
    result = store.schema_audit()
    result["audit_report"] = str(write_audit_report(result, "schema-audit"))
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_reindex(args: argparse.Namespace) -> None:
    store = get_store(with_vectors=not args.skip_vectors)
    result = store.rebuild_from_markdown(rebuild_vectors=not args.skip_vectors)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_recent(args: argparse.Namespace) -> None:
    store = get_store(with_vectors=False)
    memories = store.recent(
        project=args.project,
        category=args.category,
        source=args.source,
        since=args.since,
        limit=args.limit,
    )
    print(json.dumps([memory_to_response(memory) for memory in memories], indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Memory v2 admin CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill_parser = subparsers.add_parser("backfill", help="Backfill canonical store from Chroma")
    mode = backfill_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Inspect Chroma without writing")
    mode.add_argument("--apply", action="store_true", help="Write canonical Markdown and SQLite")
    backfill_parser.set_defaults(func=cmd_backfill)

    audit_parser = subparsers.add_parser("audit", help="Audit canonical memory schema")
    audit_parser.set_defaults(func=cmd_audit)

    reindex_parser = subparsers.add_parser("reindex", help="Rebuild SQLite/FTS and Chroma from Markdown")
    reindex_parser.add_argument("--skip-vectors", action="store_true", help="Only rebuild SQLite/FTS")
    reindex_parser.set_defaults(func=cmd_reindex)

    recent_parser = subparsers.add_parser("recent", help="List recent canonical memories")
    recent_parser.add_argument("--project")
    recent_parser.add_argument("--category")
    recent_parser.add_argument("--source")
    recent_parser.add_argument("--since")
    recent_parser.add_argument("--limit", type=int, default=20)
    recent_parser.set_defaults(func=cmd_recent)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
