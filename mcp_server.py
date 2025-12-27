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
def save_memory(content: str, category: str = "general") -> str:
    """
    Save important information, code snippets, preferences, or decisions to local persistent memory.

    Use this tool when the user:
    - Expresses a preference (e.g., "I prefer tabs over spaces")
    - Makes a project decision (e.g., "We'll use PostgreSQL for this project")
    - Shares important context (e.g., "My name is Marc, I'm a software engineer")
    - Asks you to remember something

    Args:
        content: The information to remember. Be specific and include context.
        category: Category in format "project:type" or just "type".
            Projects: content-refinery, job-search, personal-crm, general
            Types vary by project:
            - content-refinery: content_preference, publishing_decision, emotional_insight, source_learning
            - job-search: role_preference, application_insight, interview_learning, match_feedback, job_lead
            - personal-crm: relationship_context, communication_pattern, voice_style, interaction_insight
            - general: preference, learning, decision
            Examples: "job-search:role_preference", "personal-crm:relationship_context"

    Returns:
        Success or error message.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    # Parse category format (project:type or just type)
    if ":" in category:
        project, cat_type = category.split(":", 1)
    else:
        project = "general"
        cat_type = category

    try:
        response = requests.post(
            f"{API_URL}/add",
            json={
                "text": content,
                "category": cat_type,
                "project": project,
                "source": "claude_code"
            },
            timeout=30
        )
        if response.status_code == 200:
            return f"Memory saved [{project}:{cat_type}]: {content[:50]}..."
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


# ===== EMOTIONAL PATTERN TOOLS =====

EMOTIONAL_CATEGORIES = [
    "emotional_pattern",
    "thinking_trap",
    "trigger",
    "coping_strategy",
    "growth_insight",
    "core_value",
    "emotional",
]


@mcp.tool()
def search_emotional_patterns(query: str, limit: int = 5) -> str:
    """
    Search through emotional patterns, thinking traps, and psychological insights.

    AUTOMATICALLY USE THIS when the conversation involves:
    - User expressing anxiety, stress, frustration, or difficult emotions
    - Career uncertainty or job-related stress
    - Decision-making paralysis or overthinking
    - Self-doubt or imposter syndrome
    - Work-life balance struggles

    This searches patterns extracted from Rosebud emotional journal entries.

    Args:
        query: What emotional context you're looking for (e.g., "anxiety about career", "feeling overwhelmed")
        limit: Maximum results (default: 5)

    Returns:
        Relevant emotional patterns, triggers, and insights.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        # Use direct endpoint (no LLM needed)
        response = requests.get(
            f"{API_URL}/direct/search",
            params={"q": query, "limit": limit * 2},
            timeout=30
        )

        if response.status_code != 200:
            return f"Error searching: {response.text}"

        data = response.json()
        results = data.get("results", [])

        # Filter to emotional categories
        emotional_results = [
            r for r in results
            if r.get("metadata", {}).get("category", "") in EMOTIONAL_CATEGORIES
        ][:limit]

        if not emotional_results:
            return "No emotional patterns found matching your query."

        output = f"Found {len(emotional_results)} emotional patterns:\n\n"
        for i, mem in enumerate(emotional_results, 1):
            memory_text = mem.get("memory", "No content")
            category = mem.get("metadata", {}).get("category", "emotional")
            output += f"{i}. [{category}]\n   {memory_text}\n\n"

        return output

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def get_coping_strategies(situation: str) -> str:
    """
    Retrieve coping strategies that have worked for specific emotions or situations.

    USE THIS when the user:
    - Is experiencing anxiety, stress, or overwhelm
    - Needs help managing difficult emotions
    - Is facing a triggering situation (interviews, deadlines, conflicts)
    - Asks "what helps with X" or "how do I handle Y"

    Args:
        situation: The emotional situation (e.g., "feeling anxious", "burnout", "interview stress")

    Returns:
        Coping strategies that have been effective in similar situations.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        # Use direct endpoint (no LLM needed)
        response = requests.get(
            f"{API_URL}/direct/search",
            params={"q": f"coping strategy {situation}", "limit": 10},
            timeout=30
        )

        if response.status_code != 200:
            return f"Error searching: {response.text}"

        data = response.json()
        results = data.get("results", [])

        # Filter to coping strategies and related
        coping_results = [
            r for r in results
            if r.get("metadata", {}).get("category", "") in ["coping_strategy", "growth_insight"]
        ][:5]

        if not coping_results:
            return f"No specific coping strategies found for: {situation}"

        output = f"Coping strategies for '{situation}':\n\n"
        for i, mem in enumerate(coping_results, 1):
            memory_text = mem.get("memory", "No content")
            output += f"{i}. {memory_text}\n\n"

        return output

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def get_thinking_traps() -> str:
    """
    List all identified thinking traps and cognitive distortions.

    USE THIS when:
    - User is catastrophizing or spiraling
    - User shows signs of black-and-white thinking
    - User is comparing themselves unfavorably to others
    - To help identify unhelpful thought patterns

    Returns:
        List of thinking traps with descriptions.
    """
    if not check_api():
        return "Error: Local Memory server is not running. Please run 'brain start' in terminal."

    try:
        # Use direct endpoint with category filter (no LLM needed)
        response = requests.get(
            f"{API_URL}/direct/list",
            params={"category": "thinking_trap", "limit": 15},
            timeout=30
        )

        if response.status_code != 200:
            return f"Error searching: {response.text}"

        data = response.json()
        results = data.get("results", [])

        if not results:
            return "No thinking traps found in memory."

        output = "Identified thinking traps:\n\n"
        for i, mem in enumerate(results, 1):
            memory_text = mem.get("memory", "No content")
            output += f"{i}. {memory_text}\n\n"

        return output

    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    mcp.run()
