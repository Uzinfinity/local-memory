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

from config import MEM0_CONFIG, USER_ID, SERVER_HOST, SERVER_PORT

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
    source: str = "api"


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
    """Add a new memory."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        result = m.add(
            item.text,
            user_id=item.user_id,
            metadata={"category": item.category, "source": item.source}
        )
        return MemoryResponse(
            status="success",
            message="Memory saved",
            data=result
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/search")
async def search_memory(
    q: str = Query(..., description="Search query"),
    limit: int = Query(5, description="Number of results"),
    user_id: str = Query(USER_ID, description="User ID")
):
    """Search memories."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        results = m.search(q, user_id=user_id, limit=limit)
        return {
            "status": "success",
            "query": q,
            "results": results.get("results", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list")
async def list_memories(
    limit: int = Query(20, description="Number of results"),
    user_id: str = Query(USER_ID, description="User ID")
):
    """List all memories."""
    if not m:
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        results = m.get_all(user_id=user_id, limit=limit)
        return {
            "status": "success",
            "results": results.get("results", [])
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


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info"
    )
