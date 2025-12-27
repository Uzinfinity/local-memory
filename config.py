"""
Shared configuration for Local Memory Bridge.
Hybrid setup: OpenRouter (cloud LLM) + Ollama (local embeddings) + Chroma (local storage)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent / ".env")

# Paths
PROJECT_DIR = Path(__file__).parent
CHROMA_PATH = PROJECT_DIR / "chroma_data"
HISTORY_DB_PATH = PROJECT_DIR / "history.db"
LOG_PATH = PROJECT_DIR / "logs"
PID_FILE = PROJECT_DIR / ".server.pid"

# Ensure directories exist
CHROMA_PATH.mkdir(exist_ok=True)
LOG_PATH.mkdir(exist_ok=True)

# API Keys and settings
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.0-flash-exp:free")
USER_ID = os.getenv("USER_ID", "marc_wu")


# Mem0 configuration (Hybrid: Cloud LLM + Local Embeddings + Chroma)
MEM0_CONFIG = {
    "llm": {
        "provider": "openai",
        "config": {
            "model": LLM_MODEL,
            "api_key": OPENROUTER_API_KEY,
            "openai_base_url": "https://openrouter.ai/api/v1",
            "temperature": 0.1,
            "max_tokens": 2000
        }
    },
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": "nomic-embed-text",
            "ollama_base_url": "http://localhost:11434"
        }
    },
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "local_memory",
            "path": str(CHROMA_PATH)
        }
    },
    "history_db_path": str(HISTORY_DB_PATH)
}

# Server settings
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

# Project Category Schemas for memory organization
# Format: project -> category -> {description, ttl_days (None = never expires)}
PROJECT_CATEGORIES = {
    "content-refinery": {
        "content_preference": {
            "description": "Style, format, platform preferences",
            "ttl_days": None
        },
        "publishing_decision": {
            "description": "What worked, what didn't, posting patterns",
            "ttl_days": None
        },
        "emotional_insight": {
            "description": "Mood patterns, energy levels, triggers",
            "ttl_days": None
        },
        "source_learning": {
            "description": "Insights from books, podcasts, commits",
            "ttl_days": None
        }
    },
    "job-search": {
        "role_preference": {
            "description": "Target roles, companies, industries",
            "ttl_days": None
        },
        "application_insight": {
            "description": "What resonated in applications",
            "ttl_days": None
        },
        "interview_learning": {
            "description": "Feedback, question patterns",
            "ttl_days": None  # Manually set per interview
        },
        "match_feedback": {
            "description": "Which matches were accurate",
            "ttl_days": None
        },
        "job_lead": {
            "description": "Specific opportunities to pursue",
            "ttl_days": 30
        }
    },
    "personal-crm": {
        "relationship_context": {
            "description": "Key facts about contacts",
            "ttl_days": None
        },
        "communication_pattern": {
            "description": "Preferred channels, response times",
            "ttl_days": None
        },
        "voice_style": {
            "description": "Writing patterns, greetings, closings",
            "ttl_days": None
        },
        "interaction_insight": {
            "description": "What made conversations effective",
            "ttl_days": None
        }
    },
    "general": {
        "preference": {
            "description": "General preferences and settings",
            "ttl_days": None
        },
        "learning": {
            "description": "General learnings and insights",
            "ttl_days": None
        },
        "decision": {
            "description": "Decisions and their rationale",
            "ttl_days": None
        }
    }
}

# Default TTL for time-sensitive memories (days)
DEFAULT_TTL_DAYS = 30
