from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog

from src.tools.sanctions_local import is_index_available, query_local_sanctions

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.opensanctions.org"
_MATCH_ENDPOINT = "/match/default"
_TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    api_key = os.environ.get("OPENSANCTIONS_API_KEY", "")
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    return headers


async def query_opensanctions(name: str, jurisdiction: str | None = None) -> dict[str, Any]:
    """Query sanctions data for *name*.

    Uses the local FTM SQLite index when available (fast, no API key required).
    Falls back to the live OpenSanctions /match API otherwise.
    """
    if is_index_available():
        logger.bind(tool="sanctions_api", name=name).info("using_local_index")
        return await query_local_sanctions(name, jurisdiction)

    return await _query_live_api(name, jurisdiction)


async def _query_live_api(name: str, jurisdiction: str | None = None) -> dict[str, Any]:
    """Query the live OpenSanctions /match endpoint."""
    log = logger.bind(tool="sanctions_api_live", name=name)
    log.info("querying")

    payload: dict[str, Any] = {
        "queries": {
            "entity": {
                "schema": "Company",
                "properties": {"name": [name]},
            }
        }
    }
    if jurisdiction:
        payload["queries"]["entity"]["properties"]["jurisdiction"] = [jurisdiction]

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    f"{_BASE_URL}{_MATCH_ENDPOINT}",
                    json=payload,
                    headers=_headers(),
                )
                response.raise_for_status()
                data = response.json()
                log.info("done", results=len(data.get("responses", {}).get("entity", {}).get("results", [])))
                return data
        except httpx.HTTPStatusError as exc:
            log.warning("http_error", status=exc.response.status_code, attempt=attempt)
            if exc.response.status_code == 429 or attempt == 3:
                return {"error": str(exc), "responses": {}}
            await asyncio.sleep(2 ** attempt)
        except Exception as exc:
            log.warning("retry", attempt=attempt, error=str(exc))
            if attempt == 3:
                log.error("failed", error=str(exc))
                return {"error": str(exc), "responses": {}}
            await asyncio.sleep(2 ** attempt)

    return {"responses": {}}
