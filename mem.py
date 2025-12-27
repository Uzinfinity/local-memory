#!/usr/bin/env python3
"""
Local Memory CLI Tool
Usage:
    mem add "Your insight here" --cat coding
    mem search "what is my preference"
    mem list
    mem delete <memory_id>
"""
import sys
import argparse
from mem0 import Memory
from config import MEM0_CONFIG, USER_ID

# Initialize Memory instance with Chroma
try:
    m = Memory.from_config(MEM0_CONFIG)
except Exception as e:
    print(f"Error initializing memory: {e}")
    print("Make sure Ollama is running: brew services start ollama")
    sys.exit(1)


def add_memory(text: str, category: str = "general"):
    """Add a memory with optional category."""
    print(f"Processing into local brain...")
    try:
        result = m.add(
            text,
            user_id=USER_ID,
            metadata={"category": category, "source": "cli"}
        )
        print(f"Saved: {text[:60]}{'...' if len(text) > 60 else ''}")
        if result and "results" in result:
            for r in result["results"]:
                print(f"  Memory ID: {r.get('id', 'N/A')}")
    except Exception as e:
        print(f"Error adding memory: {e}")
        sys.exit(1)


def search_memory(query: str, limit: int = 5):
    """Search memories by query."""
    try:
        results = m.search(query, user_id=USER_ID, limit=limit)

        if not results.get("results"):
            print("No related memories found.")
            return

        print(f"\nFound {len(results['results'])} related memories:\n")
        print("-" * 50)
        for i, res in enumerate(results["results"], 1):
            memory = res.get("memory", "No content")
            score = res.get("score", 0.0)
            mem_id = res.get("id", "N/A")
            metadata = res.get("metadata", {})
            category = metadata.get("category", "general")

            print(f"[{i}] (Score: {score:.2f}) [{category}]")
            print(f"    {memory}")
            print(f"    ID: {mem_id}")
            print("-" * 50)
    except Exception as e:
        print(f"Error searching: {e}")
        sys.exit(1)


def list_memories(limit: int = 20):
    """List all memories."""
    try:
        results = m.get_all(user_id=USER_ID, limit=limit)

        if not results.get("results"):
            print("No memories found.")
            return

        print(f"\nShowing {len(results['results'])} memories:\n")
        print("-" * 50)
        for i, res in enumerate(results["results"], 1):
            memory = res.get("memory", "No content")
            mem_id = res.get("id", "N/A")
            metadata = res.get("metadata", {})
            category = metadata.get("category", "general")

            print(f"[{i}] [{category}] {memory[:80]}{'...' if len(memory) > 80 else ''}")
            print(f"    ID: {mem_id}")
            print("-" * 50)
    except Exception as e:
        print(f"Error listing memories: {e}")
        sys.exit(1)


def delete_memory(memory_id: str):
    """Delete a specific memory by ID."""
    try:
        m.delete(memory_id)
        print(f"Deleted memory: {memory_id}")
    except Exception as e:
        print(f"Error deleting memory: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Local Memory CLI - Your personal knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    mem add "I prefer Loguru for Python logging"
    mem add "Project X uses PostgreSQL" --cat project_x
    mem search "logging preference"
    mem list
    mem delete <memory_id>
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new memory")
    add_parser.add_argument("text", type=str, help="The content to remember")
    add_parser.add_argument(
        "--cat", "-c",
        type=str,
        default="general",
        help="Category tag (e.g., coding, project_x)"
    )

    # Search command
    search_parser = subparsers.add_parser("search", help="Search memories")
    search_parser.add_argument("query", type=str, help="What are you looking for?")
    search_parser.add_argument(
        "--limit", "-n",
        type=int,
        default=5,
        help="Number of results (default: 5)"
    )

    # List command
    list_parser = subparsers.add_parser("list", help="List all memories")
    list_parser.add_argument(
        "--limit", "-n",
        type=int,
        default=20,
        help="Number of results (default: 20)"
    )

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a memory")
    delete_parser.add_argument("memory_id", type=str, help="Memory ID to delete")

    args = parser.parse_args()

    if args.command == "add":
        add_memory(args.text, args.cat)
    elif args.command == "search":
        search_memory(args.query, args.limit)
    elif args.command == "list":
        list_memories(args.limit)
    elif args.command == "delete":
        delete_memory(args.memory_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
