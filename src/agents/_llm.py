from __future__ import annotations

import asyncio
import functools
import os
from typing import Any

import structlog
from langchain_google_genai import ChatGoogleGenerativeAI

logger = structlog.get_logger(__name__)

_MODEL_GEMINI = "gemini-2.5-flash"
_MODEL_GROQ   = "llama-3.3-70b-versatile"

_PERMANENT_MARKERS = ("PerDay", "per_day", "daily")
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "overloaded", "PerMinute", "per_minute")
_MAX_ATTEMPTS = 4
_BASE_DELAY   = 5.0
_MAX_DELAY    = 60.0


@functools.lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=_MODEL_GEMINI, temperature=0, max_retries=2)


def _groq_available() -> bool:
    if not os.environ.get("GROQ_API_KEY"):
        return False
    try:
        import langchain_groq  # noqa: F401
        return True
    except ImportError:
        return False


@functools.lru_cache(maxsize=1)
def _get_groq():
    from langchain_groq import ChatGroq  # type: ignore[import]
    return ChatGroq(model=_MODEL_GROQ, temperature=0)


def _is_permanent(exc: BaseException) -> bool:
    msg = str(exc)
    return any(m in msg for m in _PERMANENT_MARKERS)


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc)
    if _is_permanent(exc):
        return False
    return any(m in msg for m in _TRANSIENT_MARKERS)


class _SmartChain:
    """LangChain-compatible chain with exponential-backoff retry and Groq fallback.

    On transient 503 / per-minute 429: retries up to _MAX_ATTEMPTS with doubling delay.
    On daily quota exhaustion: falls back to Groq if GROQ_API_KEY is set, else re-raises.
    """

    def __init__(self, prompt: Any, output_model: Any) -> None:
        self._prompt = prompt
        self._output_model = output_model
        self._gemini_chain: Any = None
        self._groq_chain: Any = None

    @property
    def _gemini(self) -> Any:
        if self._gemini_chain is None:
            self._gemini_chain = (
                self._prompt | get_llm().with_structured_output(self._output_model)
            )
        return self._gemini_chain

    @property
    def _groq(self) -> Any:
        if self._groq_chain is None:
            self._groq_chain = (
                self._prompt | _get_groq().with_structured_output(self._output_model)
            )
        return self._groq_chain

    async def ainvoke(self, kwargs: dict[str, Any]) -> Any:
        delay = _BASE_DELAY
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self._gemini.ainvoke(kwargs)
            except Exception as exc:
                if _is_permanent(exc):
                    if _groq_available():
                        logger.info("gemini_daily_quota_fallback_groq")
                        return await self._groq.ainvoke(kwargs)
                    raise
                if _is_transient(exc) and attempt < _MAX_ATTEMPTS:
                    wait = min(delay, _MAX_DELAY)
                    logger.warning(
                        "gemini_transient_retry",
                        attempt=attempt,
                        wait=wait,
                        error=str(exc)[:120],
                    )
                    await asyncio.sleep(wait)
                    delay *= 2
                else:
                    raise
        raise RuntimeError("ainvoke loop exhausted")  # unreachable


def build_chain(prompt: Any, output_model: Any) -> _SmartChain:
    """Create a retry-aware, Groq-fallback chain. Use instead of prompt | llm.with_structured_output()."""
    return _SmartChain(prompt, output_model)


# ── Backward-compatible shim for any callers that still use ainvoke_with_retry ──
async def ainvoke_with_retry(chain: Any, kwargs: dict[str, Any]) -> Any:
    delay = _BASE_DELAY
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await chain.ainvoke(kwargs)
        except Exception as exc:
            if _is_permanent(exc):
                raise
            if _is_transient(exc) and attempt < _MAX_ATTEMPTS:
                wait = min(delay, _MAX_DELAY)
                logger.warning(
                    "gemini_transient_retry",
                    attempt=attempt,
                    wait=wait,
                    error=str(exc)[:120],
                )
                await asyncio.sleep(wait)
                delay *= 2
            else:
                raise
    raise RuntimeError("ainvoke_with_retry loop exhausted")  # unreachable
