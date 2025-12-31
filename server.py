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
import ollama
from pathlib import Path
from datetime import datetime, timedelta

from config import MEM0_CONFIG, USER_ID, SERVER_HOST, SERVER_PORT, CHROMA_PATH, PROJECT_CATEGORIES, DEFAULT_TTL_DAYS

app = FastAPI(
    title="Local Memory API",
    description="Local memory bridge for AI assistants",
    version="1.0.0"
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


class MemoryItem(BaseModel):
    text: str
    user_id: str = USER_ID
    category: str = "general"
    project: str = "general"
    source: str = "api"
    ttl_days: Optional[int] = None  # None = never expires


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
        "user_id": USER_ID
    }


@app.post("/add", response_model=MemoryResponse)
async def add_memory(item: MemoryItem):
    """Add a new memory with project categorization and optional TTL."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        # Build metadata
        metadata = {
            "category": item.category,
            "project": item.project,
            "source": item.source,
            "created_at": datetime.now().isoformat()
        }

        # Calculate expiration if TTL specified or category has default TTL
        ttl = item.ttl_days
        if ttl is None and item.project in PROJECT_CATEGORIES:
            cat_config = PROJECT_CATEGORIES[item.project].get(item.category, {})
            ttl = cat_config.get("ttl_days")

        if ttl is not None:
            expires_at = datetime.now() + timedelta(days=ttl)
            metadata["expires_at"] = expires_at.isoformat()
            metadata["ttl_days"] = ttl

        result = m.add(
            item.text,
            user_id=item.user_id,
            metadata=metadata
        )
        return MemoryResponse(
            status="success",
            message=f"Memory saved [{item.project}:{item.category}]",
            data=result
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
    project: str = Query(None, description="Filter by project")
):
    """Search memories with optional project filter and expiration handling."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        # Fetch more results to account for expired ones being filtered
        results = m.search(q, user_id=user_id, limit=limit * 2)
        memories = results.get("results", [])

        # Filter by project if specified
        if project:
            memories = [r for r in memories if r.get("metadata", {}).get("project") == project]

        # Filter out expired memories
        memories = filter_expired(memories)

        # Limit to requested count
        memories = memories[:limit]

        return {
            "status": "success",
            "query": q,
            "project": project,
            "results": memories
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list")
async def list_memories(
    limit: int = Query(20, description="Number of results"),
    user_id: str = Query(USER_ID, description="User ID"),
    project: str = Query(None, description="Filter by project")
):
    """List all memories with optional project filter and expiration handling."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        # Fetch more results to account for filtered ones
        results = m.get_all(user_id=user_id, limit=limit * 2)
        memories = results.get("results", [])

        # Filter by project if specified
        if project:
            memories = [r for r in memories if r.get("metadata", {}).get("project") == project]

        # Filter out expired memories
        memories = filter_expired(memories)

        # Limit to requested count
        memories = memories[:limit]

        return {
            "status": "success",
            "project": project,
            "results": memories
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
    limit: int = Query(5, description="Number of results")
):
    """Get context/memories for a specific project."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        results = m.search(project, user_id=USER_ID, limit=limit)
        memories = results.get("results", [])

        # Format as context string
        context_lines = []
        for mem in memories:
            text = mem.get("memory", "")
            if text:
                context_lines.append(f"- {text}")

        return {
            "status": "success",
            "project": project,
            "context": "\n".join(context_lines),
            "count": len(memories)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats():
    """Get memory statistics."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        all_memories = m.get_all(user_id=USER_ID, limit=1000)
        memories = all_memories.get("results", [])

        # Count by category
        categories = {}
        for mem in memories:
            cat = mem.get("metadata", {}).get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "status": "success",
            "total_memories": len(memories),
            "by_category": categories
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== DIRECT CHROMADB ENDPOINTS (no LLM needed) =====

def get_chroma_collection():
    """Get ChromaDB collection from mem0's internal vector store."""
    if m and hasattr(m, 'vector_store') and hasattr(m.vector_store, 'collection'):
        return m.vector_store.collection
    # Fallback: access directly (only if mem0 not initialized)
    raise HTTPException(status_code=503, detail="Memory not initialized")


def get_embedding(text: str) -> list[float]:
    """Get embedding from local Ollama."""
    response = ollama.embeddings(model="nomic-embed-text", prompt=text)
    return response["embedding"]


@app.post("/direct/add")
async def direct_add(item: MemoryItem):
    """
    Direct add to ChromaDB - bypasses LLM extraction.
    Use when the caller (e.g., Claude) has already extracted the insight.
    Only uses local Ollama embeddings.
    """
    try:
        # Get embedding from local Ollama
        embedding = get_embedding(item.text)
        collection = get_chroma_collection()

        # Build metadata
        metadata = {
            "category": item.category,
            "project": item.project,
            "source": item.source,
            "created_at": datetime.now().isoformat(),
            "user_id": item.user_id,
            "data": item.text  # Store full text in metadata too
        }

        # Calculate expiration if applicable
        ttl = item.ttl_days
        if ttl is None and item.project in PROJECT_CATEGORIES:
            cat_config = PROJECT_CATEGORIES[item.project].get(item.category, {})
            ttl = cat_config.get("ttl_days")

        if ttl is not None:
            expires_at = datetime.now() + timedelta(days=ttl)
            metadata["expires_at"] = expires_at.isoformat()
            metadata["ttl_days"] = ttl

        # Generate unique ID
        import hashlib
        doc_id = hashlib.md5(f"{item.text}{datetime.now().isoformat()}".encode()).hexdigest()[:16]

        # Insert directly into ChromaDB
        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[item.text],
            metadatas=[metadata]
        )

        return MemoryResponse(
            status="success",
            message=f"Memory saved directly [{item.project}:{item.category}]",
            data={"id": doc_id}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/direct/search")
async def direct_search(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Number of results"),
    category: str = Query(None, description="Filter by category")
):
    """Direct ChromaDB search - no LLM needed, uses local embeddings only."""
    try:
        query_embedding = get_embedding(q)
        collection = get_chroma_collection()

        where_filter = None
        if category:
            where_filter = {"category": category}

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )

        formatted = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                # Memory text can be in document or in metadata.data
                memory_text = doc or meta.get("data", "")
                formatted.append({
                    "memory": memory_text,
                    "metadata": meta,
                    "score": 1 - (results["distances"][0][i] if results["distances"] else 0),
                    "id": results["ids"][0][i] if results["ids"] else None
                })

        return {
            "status": "success",
            "query": q,
            "results": formatted
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/direct/list")
async def direct_list(
    limit: int = Query(20, description="Number of results"),
    category: str = Query(None, description="Filter by category")
):
    """Direct list from ChromaDB."""
    try:
        collection = get_chroma_collection()
        where_filter = None
        if category:
            where_filter = {"category": category}

        results = collection.get(
            limit=limit,
            where=where_filter,
            include=["documents", "metadatas"]
        )

        formatted = []
        if results["documents"]:
            for i, doc in enumerate(results["documents"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                memory_text = doc or meta.get("data", "")
                formatted.append({
                    "memory": memory_text,
                    "metadata": meta,
                    "id": results["ids"][i] if results["ids"] else None
                })

        return {
            "status": "success",
            "results": formatted
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/direct/stats")
async def direct_stats():
    """Direct stats from ChromaDB."""
    try:
        collection = get_chroma_collection()
        all_docs = collection.get(include=["metadatas"])
        total = len(all_docs["ids"]) if all_docs["ids"] else 0

        categories = {}
        if all_docs["metadatas"]:
            for meta in all_docs["metadatas"]:
                cat = meta.get("category", "general")
                categories[cat] = categories.get(cat, 0) + 1

        return {
            "status": "success",
            "total_memories": total,
            "by_category": categories
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        collection = get_chroma_collection()
        all_docs = collection.get(include=["metadatas"])

        if not all_docs["ids"]:
            return PruneResponse(
                status="success",
                pruned_count=0,
                total_before=0,
                total_after=0,
                by_category={}
            )

        total_before = len(all_docs["ids"])
        now = datetime.now()

        # Find expired memories
        expired_ids = []
        expired_by_category = {}

        for i, doc_id in enumerate(all_docs["ids"]):
            meta = all_docs["metadatas"][i] if all_docs["metadatas"] else {}
            expires_at = meta.get("expires_at")

            if expires_at:
                try:
                    exp_date = datetime.fromisoformat(expires_at)
                    if exp_date < now:
                        expired_ids.append(doc_id)
                        cat = meta.get("category", "general")
                        expired_by_category[cat] = expired_by_category.get(cat, 0) + 1
                except ValueError:
                    pass  # Invalid date format, skip

        # Delete expired memories (unless dry run)
        if expired_ids and not dry_run:
            collection.delete(ids=expired_ids)

        total_after = total_before - len(expired_ids) if not dry_run else total_before

        return PruneResponse(
            status="dry_run" if dry_run else "success",
            pruned_count=len(expired_ids),
            total_before=total_before,
            total_after=total_after,
            by_category=expired_by_category
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/expired")
async def list_expired_memories(
    limit: int = Query(50, description="Maximum expired memories to list")
):
    """List all currently expired memories (preview before pruning)."""
    try:
        collection = get_chroma_collection()
        all_docs = collection.get(include=["documents", "metadatas"])

        now = datetime.now()
        expired = []

        if all_docs["ids"]:
            for i, doc_id in enumerate(all_docs["ids"]):
                meta = all_docs["metadatas"][i] if all_docs["metadatas"] else {}
                expires_at = meta.get("expires_at")

                if expires_at:
                    try:
                        exp_date = datetime.fromisoformat(expires_at)
                        if exp_date < now:
                            days_expired = (now - exp_date).days
                            doc = all_docs["documents"][i] if all_docs["documents"] else ""
                            expired.append({
                                "id": doc_id,
                                "memory": doc[:100] + "..." if len(doc) > 100 else doc,
                                "category": meta.get("category", "general"),
                                "project": meta.get("project", "general"),
                                "expired_at": expires_at,
                                "days_expired": days_expired
                            })
                    except ValueError:
                        pass

                if len(expired) >= limit:
                    break

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
