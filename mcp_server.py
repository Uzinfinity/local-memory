#!/usr/bin/env python3
"""
MCP Server for Local Memory Bridge
Integrates with Claude Desktop via Model Context Protocol.

This server exposes memory tools that Claude can use to:
- Save important information to persistent local memory
- Search through past memories and preferences
"""
import requests
from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP("Local Memory Brain")

# API endpoint (our FastAPI server)
API_URL = "http://localhost:8000"


def check_api():
    """Check if the API server is running."""
    try:
        response = requests.get(f"{API_URL}/health", timeout=2)
        return response.status_code == 200
    except:
        return False


@mcp.tool()
def save_memory(content: str, category: str = "claude_desktop") -> str:
    """
    Save important information, code snippets, preferences, or decisions to local persistent memory.

    Use this tool when the user:
    - Expresses a preference (e.g., "I prefer tabs over spaces")
    - Makes a project decision (e.g., "We'll use PostgreSQL for this project")
    - Shares important context (e.g., "My name is Marc, I'm a software engineer")
    - Asks you to remember something

    Args:
        content: The information to remember. Be specific and include context.
        category: Category tag (e.g., "coding", "project_x", "personal"). Defaults to "claude_desktop".

    Returns:
        Success or error message.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        response = requests.post(
            f"{API_URL}/add",
            json={
                "text": content,
                "category": category,
                "source": "claude_desktop"
            },
            timeout=30
        )
        if response.status_code == 200:
            return f"Memory saved successfully: {content[:50]}..."
        else:
            return f"Error saving memory: {response.text}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def search_memory(query: str, limit: int = 5) -> str:
    """
    Search through past memories, preferences, project details, and saved information.

    Use this tool when:
    - You need to recall the user's preferences
    - Looking for past project decisions or context
    - The user asks "what did I say about X" or "do you remember Y"
    - You need context to provide a personalized response

    Args:
        query: What you're looking for. Can be a question or keywords.
        limit: Maximum number of results to return (default: 5).

    Returns:
        Relevant memories or "No memories found" message.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        response = requests.get(
            f"{API_URL}/search",
            params={"q": query, "limit": limit},
            timeout=10
        )

        if response.status_code != 200:
            return f"Error searching: {response.text}"

        data = response.json()
        results = data.get("results", [])

        if not results:
            return "No memories found matching your query."

        output = f"Found {len(results)} relevant memories:\n\n"
        for i, mem in enumerate(results, 1):
            memory_text = mem.get("memory", "No content")
            score = mem.get("score", 0)
            category = mem.get("metadata", {}).get("category", "general")
            output += f"{i}. [{category}] (relevance: {score:.2f})\n   {memory_text}\n\n"

        return output

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def list_memories(limit: int = 10) -> str:
    """
    List recent memories stored in the local memory brain.

    Use this when the user wants to see what has been remembered.

    Args:
        limit: Maximum number of memories to list (default: 10).

    Returns:
        List of recent memories.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        response = requests.get(
            f"{API_URL}/list",
            params={"limit": limit},
            timeout=10
        )

        if response.status_code != 200:
            return f"Error listing memories: {response.text}"

        data = response.json()
        results = data.get("results", [])

        if not results:
            return "No memories stored yet."

        output = f"Showing {len(results)} memories:\n\n"
        for i, mem in enumerate(results, 1):
            memory_text = mem.get("memory", "No content")
            category = mem.get("metadata", {}).get("category", "general")
            mem_id = mem.get("id", "N/A")
            # Truncate long memories
            if len(memory_text) > 100:
                memory_text = memory_text[:100] + "..."
            output += f"{i}. [{category}] {memory_text}\n   ID: {mem_id}\n\n"

        return output

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def get_project_context(project_name: str) -> str:
    """
    Get all memories and context related to a specific project.

    Use this at the start of a conversation about a project to load relevant context.

    Args:
        project_name: The project name (e.g., "job-search", "personal-crm", "content-refinery")

    Returns:
        Relevant project context and past decisions.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        response = requests.get(
            f"{API_URL}/context",
            params={"project": project_name, "limit": 10},
            timeout=10
        )

        if response.status_code != 200:
            return f"Error getting context: {response.text}"

        data = response.json()
        context = data.get("context", "")
        count = data.get("count", 0)

        if not context:
            return f"No memories found for project: {project_name}"

        return f"Context for {project_name} ({count} memories):\n\n{context}"

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def memory_stats() -> str:
    """
    Get statistics about stored memories.

    Use this to see how many memories are stored and their categories.

    Returns:
        Memory statistics including total count and breakdown by category.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        response = requests.get(f"{API_URL}/stats", timeout=10)

        if response.status_code != 200:
            return f"Error getting stats: {response.text}"

        data = response.json()
        total = data.get("total_memories", 0)
        categories = data.get("by_category", {})

        output = f"Memory Statistics:\n"
        output += f"Total memories: {total}\n\n"
        output += "By category:\n"
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            output += f"  - {cat}: {count}\n"

        return output

    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    mcp.run()
