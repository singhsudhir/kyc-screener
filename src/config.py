from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"Required environment variable {key!r} is not set")
    return value


GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
TAVILY_API_KEY: str = os.environ.get("TAVILY_API_KEY", "")
OPENSANCTIONS_API_KEY: str = os.environ.get("OPENSANCTIONS_API_KEY", "")
