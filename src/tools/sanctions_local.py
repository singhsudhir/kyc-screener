from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_DB_PATH = Path("data/sanctions/sanctions.db")
_MAX_CANDIDATES = 200
_MAX_RESULTS = 15
_MIN_SCORE = 0.35


def _normalise(text: str) -> str:
    """Lowercase, strip diacritics, collapse non-word characters."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _token_score(query: str, candidate: str) -> float:
    """Jaccard token-overlap score between two name strings."""
    q_toks = set(_normalise(query).split())
    c_toks = set(_normalise(candidate).split())
    stopwords = {"the", "ltd", "limited", "llc", "inc", "co", "and", "of", "for", "sa", "gmbh", "bv"}
    q_toks -= stopwords
    c_toks -= stopwords
    if not q_toks or not c_toks:
        return 0.0
    overlap = q_toks & c_toks
    return len(overlap) / len(q_toks | c_toks)


def is_index_available() -> bool:
    return _DB_PATH.exists()


def _build_fts_query(name: str) -> str:
    """Build an FTS5 OR query from the significant tokens in name."""
    tokens = [t for t in _normalise(name).split() if len(t) > 2]
    if not tokens:
        return ""
    # Quote each token to treat as a phrase unit, combine with OR
    return " OR ".join(f'"{t}"' for t in tokens)


async def query_local_sanctions(
    name: str,
    jurisdiction: str | None = None,
) -> dict[str, Any]:
    """Search the local FTM SQLite index for sanctioned entities matching *name*.

    Returns a dict in the same shape as the live OpenSanctions /match response so
    the sanctions agent needs no changes.
    """
    log = logger.bind(tool="sanctions_local", name=name)

    if not _DB_PATH.exists():
        log.warning("index_missing", path=str(_DB_PATH))
        return {"error": "Local sanctions index not built", "responses": {}}

    fts_query = _build_fts_query(name)
    if not fts_query:
        return {"responses": {"entity": {"results": []}}}

    try:
        con = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """
                SELECT DISTINCT
                    e.id, e.caption, e.schema, e.datasets,
                    e.topics, e.country, e.properties,
                    nf.name AS matched_name
                FROM names_fts nf
                JOIN entities e ON e.id = nf.entity_id
                WHERE names_fts MATCH ?
                LIMIT ?
                """,
                (fts_query, _MAX_CANDIDATES),
            ).fetchall()
        finally:
            con.close()
    except sqlite3.OperationalError as exc:
        log.error("db_error", error=str(exc))
        return {"error": str(exc), "responses": {}}

    # Score every candidate against the query name
    scored: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for row in rows:
        eid = row["id"]
        if eid in seen_ids:
            continue
        seen_ids.add(eid)

        caption_score = _token_score(name, row["caption"])
        matched_score = _token_score(name, row["matched_name"])
        score = max(caption_score, matched_score)

        # Jurisdiction boost: if the entity's country matches, add +0.05
        if jurisdiction:
            try:
                countries: list[str] = json.loads(row["country"])
                jur_norm = _normalise(jurisdiction)
                if any(jur_norm in _normalise(c) or _normalise(c) in jur_norm for c in countries):
                    score = min(1.0, score + 0.05)
            except (json.JSONDecodeError, TypeError):
                pass

        if score < _MIN_SCORE:
            continue

        props = json.loads(row["properties"])
        datasets = json.loads(row["datasets"])
        topics = json.loads(row["topics"])

        scored.append({
            "id": eid,
            "caption": row["caption"],
            "schema": row["schema"],
            "datasets": datasets,
            "topics": topics,
            "properties": props,
            "score": round(score, 3),
            "match": score >= 0.85,
            "_source": "local_index",
        })

    scored.sort(key=lambda r: r["score"], reverse=True)
    results = scored[:_MAX_RESULTS]

    log.info("done", candidates=len(rows), hits=len(results))
    return {"responses": {"entity": {"results": results}}}
