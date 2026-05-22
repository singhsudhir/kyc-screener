from __future__ import annotations

import asyncio
import functools
from typing import Any

import structlog
from langchain_google_genai import ChatGoogleGenerativeAI

logger = structlog.get_logger(__name__)

_MODEL = "gemini-2.5-flash"
_MAX_ATTEMPTS = 4
_BASE_DELAY = 5.0   # seconds before first retry
_MAX_DELAY = 60.0

# Daily quota exhaustion — retrying will never succeed until the next day
_PERMANENT_MARKERS = ("PerDay", "per_day", "daily")
# Transient capacity issues — worth retrying after a short wait
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "overloaded", "PerMinute", "per_minute")


@functools.lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    """Return a shared Gemini Flash LLM instance."""
    return ChatGoogleGenerativeAI(model=_MODEL, temperature=0, max_retries=2)


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc)
    # Daily quota exhaustion is permanent until reset — fail fast
    if any(m in msg for m in _PERMANENT_MARKERS):
        return False
    return any(m in msg for m in _TRANSIENT_MARKERS)


async def ainvoke_with_retry(chain: Any, kwargs: dict[str, Any]) -> Any:
    """Invoke *chain* with exponential-backoff retry on transient Gemini errors."""
    delay = _BASE_DELAY
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await chain.ainvoke(kwargs)
        except Exception as exc:
            if attempt == _MAX_ATTEMPTS or not _is_transient(exc):
                raise
            wait = min(delay, _MAX_DELAY)
            logger.warning(
                "gemini_transient_error",
                attempt=attempt,
                wait=wait,
                error=str(exc)[:120],
            )
            await asyncio.sleep(wait)
            delay *= 2
