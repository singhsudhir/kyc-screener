from __future__ import annotations

import os
import asyncio
from typing import Any

import structlog
from tavily import AsyncTavilyClient

logger = structlog.get_logger(__name__)

_MAX_RESULTS = 8
_client: AsyncTavilyClient | None = None


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        api_key = os.environ["TAVILY_API_KEY"]
        _client = AsyncTavilyClient(api_key=api_key)
    return _client


async def web_search(query: str, max_results: int = _MAX_RESULTS) -> list[dict[str, Any]]:
    """Search the web via Tavily and return a list of {url, title, content} dicts."""
    log = logger.bind(tool="web_search", query=query)
    log.info("searching")

    for attempt in range(1, 4):
        try:
            response = await _get_client().search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_raw_content=False,
            )
            results = [
                {"url": r["url"], "title": r.get("title", ""), "content": r.get("content", "")}
                for r in response.get("results", [])
            ]
            log.info("done", count=len(results))
            return results
        except Exception as exc:
            log.warning("retry", attempt=attempt, error=str(exc))
            if attempt == 3:
                log.error("failed", error=str(exc))
                return []
            await asyncio.sleep(2 ** attempt)

    return []
