#!/usr/bin/env python3
"""
Local Memory FastAPI Server
Provides HTTP endpoints for Chrome extension and MCP integration.

Endpoints:
    POST /add - Add a memory
    GET /search - Search memories
    GET /list - List all memories
    DELETE /delete/{memory_id} - Delete a memory
    GET /health - Health check
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from mem0 import Memory
import uvicorn
import chromadb
from chromadb.config import Settings
import ollama
from datetime import datetime, timedelta

from config import (
    MEM0_CONFIG,
    USER_ID,
    SERVER_HOST,
    SERVER_PORT,
    CHROMA_PATH,
    PROJECT_CATEGORIES,
    MEMORY_DIR,
    MEMORY_INDEX_PATH,
)
from memory_store import MemoryStore, memory_to_response, normalize_project_category

app = FastAPI(
    title="Local Memory API",
    description="Local memory bridge for AI assistants",
    version="2.0.0"
)

# Enable CORS for Chrome extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local use
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Memory instance with Chroma
print("Initializing Memory with OpenRouter (cloud LLM) + Ollama (local embeddings) + Chroma...")
try:
    m = Memory.from_config(MEM0_CONFIG)
    print("Memory Brain Loaded!")
except Exception as e:
    print(f"Error loading memory: {e}")
    print("Make sure Ollama is running: brew services start ollama")
    m = None

store: Optional[MemoryStore] = None


class MemoryItem(BaseModel):
    text: str
    user_id: str = USER_ID
    category: str = "general"
    project: str = "general"
    source: str = "api"
    source_ref: Optional[str] = None
    ttl_days: Optional[int] = None  # None = never expires
    importance: float = 0.5
    confidence: float = 0.8
    tags: list[str] = []


class SessionData(BaseModel):
    transcript: list[dict] = []
    cwd: str = ""
    session_id: str = ""


class MemoryResponse(BaseModel):
    status: str
    message: str
    data: Optional[dict] = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "memory_initialized": m is not None,
        "canonical_initialized": get_memory_store() is not None,
        "user_id": USER_ID
    }


@app.post("/add", response_model=MemoryResponse)
async def add_memory(item: MemoryItem):
    """Add a new memory with project categorization and optional TTL."""
    try:
        ttl = resolve_ttl(item.project, item.category, item.ttl_days)
        memory = get_memory_store().add_memory(
            text=item.text,
            project=item.project,
            category=item.category,
            source=item.source,
            source_ref=item.source_ref,
            ttl_days=ttl,
            importance=item.importance,
            confidence=item.confidence,
            tags=item.tags,
            metadata={"user_id": item.user_id},
        )
        return MemoryResponse(
            status="success",
            message=f"Memory saved [{memory.project}:{memory.category}]",
            data={"id": memory.id, "embedding_status": memory.embedding_status}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def filter_expired(results: list) -> list:
    """Filter out expired memories."""
    now = datetime.now()
    valid = []
    for r in results:
        expires_at = r.get("metadata", {}).get("expires_at")
        if expires_at:
            try:
                exp_date = datetime.fromisoformat(expires_at)
                if exp_date < now:
                    continue  # Skip expired
            except ValueError:
                pass  # Invalid date format, keep it
        valid.append(r)
    return valid


@app.get("/search")
async def search_memory(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Number of results"),
    user_id: str = Query(USER_ID, description="User ID"),
    project: str = Query(None, description="Filter by project"),
    category: str = Query(None, description="Filter by category"),
    source: str = Query(None, description="Filter by source"),
    since: str = Query(None, description="Filter by created_at lower bound")
):
    """Search memories with optional project filter and expiration handling."""
    try:
        del user_id  # Canonical v2 is single-user for this local store.
        results = get_memory_store().search(
            q,
            project=project,
            category=category,
            source=source,
            since=since,
            limit=limit,
        )

        return {
            "status": "success",
            "query": q,
            "project": project,
            "results": [memory_to_response(memory, score) for memory, score in results]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list")
async def list_memories(
    limit: int = Query(20, description="Number of results"),
    user_id: str = Query(USER_ID, description="User ID"),
    project: str = Query(None, description="Filter by project"),
    category: str = Query(None, description="Filter by category"),
    source: str = Query(None, description="Filter by source"),
    since: str = Query(None, description="Filter by created_at lower bound")
):
    """List all memories with optional project filter and expiration handling."""
    try:
        del user_id
        memories = get_memory_store().recent(
            project=project,
            category=category,
            source=source,
            since=since,
            limit=limit,
        )

        return {
            "status": "success",
            "project": project,
            "results": [memory_to_response(memory) for memory in memories]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete/{memory_id}")
async def delete_memory(memory_id: str):
    """Delete a specific memory."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        m.delete(memory_id)
        return {
            "status": "success",
            "message": f"Deleted memory: {memory_id}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/context")
async def get_project_context(
    project: str = Query(..., description="Project name or category"),
    limit: int = Query(10, description="Number of results"),
    workflow: str = Query("default", description="Workflow name")
):
    """Get context/memories for a specific project."""
    try:
        pack = get_memory_store().context_pack(project=project, workflow=workflow, limit=limit)

        return {
            "status": "success",
            "project": project,
            "context": pack["context"],
            "sections": pack["sections"],
            "count": pack["count"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats():
    """Get memory statistics."""
    try:
        stats = get_memory_store().stats()
        stats["status"] = "success"
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== DIRECT CHROMADB ENDPOINTS (no LLM needed) =====

def get_chroma_collection():
    """Get ChromaDB collection from mem0's internal vector store."""
    if m and hasattr(m, 'vector_store') and hasattr(m.vector_store, 'collection'):
        return m.vector_store.collection
    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False)
    )
    return client.get_or_create_collection(name="local_memory")


def get_embedding(text: str) -> list[float]:
    """Get embedding from local Ollama."""
    response = ollama.embeddings(model="nomic-embed-text", prompt=text)
    return response["embedding"]


def get_memory_store() -> MemoryStore:
    """Return the canonical memory store, with vector indexing when available."""
    global store
    if store is None:
        try:
            collection = get_chroma_collection()
            embed_func = get_embedding
        except Exception:
            collection = None
            embed_func = None
        store = MemoryStore(
            root_dir=MEMORY_DIR,
            index_path=MEMORY_INDEX_PATH,
            collection=collection,
            embed_func=embed_func,
        )
    return store


def resolve_ttl(project: str, category: str, ttl_days: Optional[int]) -> Optional[int]:
    if ttl_days is not None:
        return ttl_days
    project, category = normalize_project_category(project, category)
    if project in PROJECT_CATEGORIES:
        cat_config = PROJECT_CATEGORIES[project].get(category, {})
        return cat_config.get("ttl_days")
    return None


@app.post("/direct/add")
async def direct_add(item: MemoryItem):
    """
    Direct add to ChromaDB - bypasses LLM extraction.
    Use when the caller (e.g., Claude) has already extracted the insight.
    Only uses local Ollama embeddings.
    """
    try:
        ttl = resolve_ttl(item.project, item.category, item.ttl_days)
        memory = get_memory_store().add_memory(
            text=item.text,
            project=item.project,
            category=item.category,
            source=item.source,
            source_ref=item.source_ref,
            ttl_days=ttl,
            importance=item.importance,
            confidence=item.confidence,
            tags=item.tags,
            metadata={"user_id": item.user_id},
        )

        return MemoryResponse(
            status="success",
            message=f"Memory saved directly [{memory.project}:{memory.category}]",
            data={"id": memory.id, "embedding_status": memory.embedding_status}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/direct/search")
async def direct_search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Number of results"),
    category: str = Query(None, description="Filter by category"),
    project: str = Query(None, description="Filter by project"),
    source: str = Query(None, description="Filter by source"),
    since: str = Query(None, description="Filter by created_at lower bound")
):
    """Direct ChromaDB search - no LLM needed, uses local embeddings only."""
    try:
        results = get_memory_store().search(
            q,
            project=project,
            category=category,
            source=source,
            since=since,
            limit=limit,
        )

        return {
            "status": "success",
            "query": q,
            "results": [memory_to_response(memory, score) for memory, score in results]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/direct/list")
async def direct_list(
    limit: int = Query(20, description="Number of results"),
    category: str = Query(None, description="Filter by category"),
    project: str = Query(None, description="Filter by project"),
    source: str = Query(None, description="Filter by source"),
    since: str = Query(None, description="Filter by created_at lower bound")
):
    """Direct list from ChromaDB."""
    try:
        memories = get_memory_store().recent(
            project=project,
            category=category,
            source=source,
            since=since,
            limit=limit,
        )

        return {
            "status": "success",
            "results": [memory_to_response(memory) for memory in memories]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/direct/stats")
async def direct_stats():
    """Direct stats from ChromaDB."""
    try:
        stats = get_memory_store().stats()
        stats["status"] = "success"
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v2/recent")
async def v2_recent(
    project: str = Query(None),
    category: str = Query(None),
    source: str = Query(None),
    since: str = Query(None),
    limit: int = Query(20),
):
    memories = get_memory_store().recent(
        project=project,
        category=category,
        source=source,
        since=since,
        limit=limit,
    )
    return {"status": "success", "results": [memory_to_response(memory) for memory in memories]}


@app.get("/v2/search")
async def v2_search(
    q: str = Query(...),
    project: str = Query(None),
    category: str = Query(None),
    source: str = Query(None),
    since: str = Query(None),
    limit: int = Query(5),
):
    results = get_memory_store().search(
        q,
        project=project,
        category=category,
        source=source,
        since=since,
        limit=limit,
    )
    return {
        "status": "success",
        "query": q,
        "results": [memory_to_response(memory, score) for memory, score in results],
    }


@app.get("/v2/context_pack")
async def v2_context_pack(
    project: str = Query(...),
    workflow: str = Query("default"),
    limit: int = Query(20),
):
    pack = get_memory_store().context_pack(project=project, workflow=workflow, limit=limit)
    pack["status"] = "success"
    return pack


@app.post("/v2/reindex")
async def v2_reindex(skip_vectors: bool = Query(False)):
    result = get_memory_store().rebuild_from_markdown(rebuild_vectors=not skip_vectors)
    result["status"] = "success"
    return result


@app.get("/v2/schema_audit")
async def v2_schema_audit():
    result = get_memory_store().schema_audit()
    result["status"] = "success"
    return result


# ===== MEMORY PRUNING ENDPOINT =====

class PruneResponse(BaseModel):
    status: str
    pruned_count: int
    total_before: int
    total_after: int
    by_category: dict


@app.post("/prune", response_model=PruneResponse)
async def prune_expired_memories(
    dry_run: bool = Query(False, description="Preview what would be pruned without deleting")
):
    """
    Prune expired memories based on their TTL.

    Memories with an `expires_at` field in metadata that is in the past
    will be deleted. Use dry_run=true to preview without deleting.
    """
    try:
        result = get_memory_store().archive_expired(dry_run=dry_run)
        return PruneResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/expired")
async def list_expired_memories(
    limit: int = Query(50, description="Maximum expired memories to list")
):
    """List all currently expired memories (preview before pruning)."""
    try:
        now = datetime.now()
        expired = []
        for memory in get_memory_store().expired(limit=limit):
            exp_date = datetime.fromisoformat(memory.expires_at)
            expired.append({
                "id": memory.id,
                "memory": memory.text[:100] + "..." if len(memory.text) > 100 else memory.text,
                "category": memory.category,
                "project": memory.project,
                "expired_at": memory.expires_at,
                "days_expired": (now - exp_date).days
            })

        return {
            "status": "success",
            "expired_count": len(expired),
            "memories": expired
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info"
    )
