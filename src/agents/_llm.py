from __future__ import annotations

import asyncio
import functools
import os
from typing import Any

import structlog
from langchain_google_genai import ChatGoogleGenerativeAI

logger = structlog.get_logger(__name__)

_MODEL_GEMINI_PRIMARY  = "gemini-2.5-flash"       # 20 RPD free tier — best quality
_MODEL_GEMINI_FALLBACK = "gemini-2.5-flash-lite"  # higher RPD free tier — same API key
_MODEL_GROQ            = "llama-3.3-70b-versatile"

_PERMANENT_MARKERS = ("PerDay", "per_day", "daily", "FreeTier")
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "overloaded", "PerMinute", "per_minute")
_MAX_ATTEMPTS = 4
_BASE_DELAY   = 5.0
_MAX_DELAY    = 60.0


@functools.lru_cache(maxsize=1)
def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=_MODEL_GEMINI_PRIMARY, temperature=0, max_retries=2)


@functools.lru_cache(maxsize=1)
def _get_gemini_fallback() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model=_MODEL_GEMINI_FALLBACK, temperature=0, max_retries=2)


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
    """Retry-aware chain with three-tier fallback.

    Tier 1 — gemini-2.5-flash (best quality, 20 RPD free)
    Tier 2 — gemini-1.5-flash (same API key, 1,500 RPD free)
    Tier 3 — Groq llama-3.3-70b (optional, requires GROQ_API_KEY)

    Transient 503 / per-minute 429 → exponential backoff within the current tier.
    Daily quota exhausted → cascade to next tier.
    """

    def __init__(self, prompt: Any, output_model: Any) -> None:
        self._prompt = prompt
        self._output_model = output_model
        self._gemini_primary_chain: Any = None
        self._gemini_fallback_chain: Any = None
        self._groq_chain: Any = None

    @property
    def _gemini_primary(self) -> Any:
        if self._gemini_primary_chain is None:
            self._gemini_primary_chain = (
                self._prompt | get_llm().with_structured_output(self._output_model)
            )
        return self._gemini_primary_chain

    @property
    def _gemini_fallback(self) -> Any:
        if self._gemini_fallback_chain is None:
            self._gemini_fallback_chain = (
                self._prompt | _get_gemini_fallback().with_structured_output(self._output_model)
            )
        return self._gemini_fallback_chain

    @property
    def _groq(self) -> Any:
        if self._groq_chain is None:
            self._groq_chain = (
                self._prompt | _get_groq().with_structured_output(self._output_model)
            )
        return self._groq_chain

    async def _invoke_with_retry(self, chain: Any, label: str, kwargs: dict[str, Any]) -> Any:
        """Try *chain* with exponential backoff on transient errors."""
        delay = _BASE_DELAY
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await chain.ainvoke(kwargs)
            except Exception as exc:
                if _is_permanent(exc) or not _is_transient(exc):
                    raise
                if attempt < _MAX_ATTEMPTS:
                    wait = min(delay, _MAX_DELAY)
                    logger.warning(
                        "llm_transient_retry",
                        model=label,
                        attempt=attempt,
                        wait=wait,
                        error=str(exc)[:120],
                    )
                    await asyncio.sleep(wait)
                    delay *= 2
                else:
                    raise
        raise RuntimeError("_invoke_with_retry exhausted")  # unreachable

    async def ainvoke(self, kwargs: dict[str, Any]) -> Any:
        # Tier 1: gemini-2.5-flash
        try:
            return await self._invoke_with_retry(
                self._gemini_primary, _MODEL_GEMINI_PRIMARY, kwargs
            )
        except Exception as exc:
            if not _is_permanent(exc):
                raise
            logger.info("gemini_primary_quota_exhausted", fallback=_MODEL_GEMINI_FALLBACK)

        # Tier 2: gemini-1.5-flash (same API key, 1,500 RPD)
        try:
            return await self._invoke_with_retry(
                self._gemini_fallback, _MODEL_GEMINI_FALLBACK, kwargs
            )
        except Exception as exc:
            if not _is_permanent(exc):
                raise
            logger.info("gemini_fallback_quota_exhausted", fallback="groq" if _groq_available() else "none")

        # Tier 3: Groq (optional)
        if _groq_available():
            return await self._groq.ainvoke(kwargs)

        raise RuntimeError(
            "All LLM tiers exhausted. Add GROQ_API_KEY or wait for quota reset."
        )


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
