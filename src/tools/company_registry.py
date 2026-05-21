from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Companies House (UK) — extend with other jurisdiction registries as needed
_UK_BASE = "https://api.company-information.service.gov.uk"


async def lookup_company_registry(
    name: str,
    jurisdiction: str,
    registration_number: str | None = None,
) -> dict[str, Any]:
    """Look up a company in the relevant national registry.

    Currently supports UK (Companies House). Returns empty dict for other jurisdictions.
    """
    log = logger.bind(tool="company_registry", name=name, jurisdiction=jurisdiction)

    if jurisdiction.upper() in ("GB", "UK"):
        return await _lookup_companies_house(name, registration_number, log)

    log.info("no_registry_available", jurisdiction=jurisdiction)
    return {"note": f"No registry integration for jurisdiction {jurisdiction!r}", "name": name}


async def _lookup_companies_house(
    name: str,
    registration_number: str | None,
    log,
) -> dict[str, Any]:
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    if not api_key:
        log.warning("no_api_key")
        return {"error": "COMPANIES_HOUSE_API_KEY not set"}

    auth = httpx.BasicAuth(api_key, "")

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(auth=auth, timeout=15.0) as client:
                if registration_number:
                    resp = await client.get(f"{_UK_BASE}/company/{registration_number}")
                else:
                    resp = await client.get(
                        f"{_UK_BASE}/search/companies",
                        params={"q": name, "items_per_page": 5},
                    )
                resp.raise_for_status()
                data = resp.json()
                log.info("done")
                return data
        except Exception as exc:
            log.warning("retry", attempt=attempt, error=str(exc))
            if attempt == 3:
                return {"error": str(exc)}
            await asyncio.sleep(2 ** attempt)

    return {}
