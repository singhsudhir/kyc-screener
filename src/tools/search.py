from __future__ import annotations

import os
import asyncio
from typing import Any

import structlog
from tavily import AsyncTavilyClient

logger = structlog.get_logger(__name__)

_MAX_RESULTS = 8


async def web_search(query: str, max_results: int = _MAX_RESULTS) -> list[dict[str, Any]]:
    """Search the web via Tavily and return a list of {url, title, content} dicts."""
    log = logger.bind(tool="web_search", query=query)
    log.info("searching")

    # Create a fresh client per call — AsyncTavilyClient wraps an httpx.AsyncClient
    # that is bound to the current event loop. Reusing a cached client across
    # separate asyncio.run() calls (each creates a new loop) causes
    # "TCPTransport closed" errors on the second and subsequent screenings.
    client = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])

    for attempt in range(1, 4):
        try:
            response = await client.search(
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
            if attempt == 3:
                log.error("failed", error=str(exc))
                return []
            log.warning("retry", attempt=attempt, error=str(exc))
            await asyncio.sleep(2 ** attempt)

    return []
