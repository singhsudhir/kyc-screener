from __future__ import annotations

import gzip
import json
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_SANCTIONS_DIR = Path("data/sanctions")
_DB_PATH       = _SANCTIONS_DIR / "sanctions.db"    # full 1.3M-entity index (local only)
_FOCUSED_DB    = _SANCTIONS_DIR / "focused.db"      # decompressed focused index
_FOCUSED_GZ    = _SANCTIONS_DIR / "focused.db.gz"   # committed compressed index

_MAX_CANDIDATES = 200
_MAX_RESULTS = 15
_MIN_SCORE = 0.35

# Cached path to the SQLite file to use this process lifetime
_resolved_db: Path | None = None


def _decompress_focused() -> Path | None:
    """Decompress focused.db.gz to a temp file; return its path or None on failure."""
    if not _FOCUSED_GZ.exists():
        return None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="kyc_sanctions_"))
        dest = tmp_dir / "focused.db"
        logger.info("decompressing_sanctions_index", src=str(_FOCUSED_GZ), dest=str(dest))
        with gzip.open(_FOCUSED_GZ, "rb") as f_in, open(dest, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        logger.info("decompressed_ok", size_mb=round(dest.stat().st_size / 1_048_576, 1))
        return dest
    except Exception as exc:
        logger.error("decompress_failed", error=str(exc))
        return None


def _resolve_db() -> Path | None:
    """Return the SQLite DB path to use, decompressing if needed. Cached after first call."""
    global _resolved_db
    if _resolved_db is not None and _resolved_db.exists():
        return _resolved_db

    if _DB_PATH.exists():
        _resolved_db = _DB_PATH
    elif _FOCUSED_DB.exists():
        _resolved_db = _FOCUSED_DB
    else:
        _resolved_db = _decompress_focused()

    return _resolved_db


def is_index_available() -> bool:
    return _resolve_db() is not None


def _normalise(text: str) -> str:
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


def _build_fts_query(name: str) -> str:
    tokens = [t for t in _normalise(name).split() if len(t) > 2]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


async def query_local_sanctions(
    name: str,
    jurisdiction: str | None = None,
) -> dict[str, Any]:
    """Search the local SQLite FTS5 index for sanctioned entities matching *name*.

    Returns a dict in the same shape as the live OpenSanctions /match response.
    Tries (in order): sanctions.db → focused.db → focused.db.gz (auto-decompressed).
    """
    log = logger.bind(tool="sanctions_local", name=name)

    db_path = _resolve_db()
    if db_path is None:
        log.warning("index_missing")
        return {"error": "Local sanctions index not available", "responses": {}}

    fts_query = _build_fts_query(name)
    if not fts_query:
        return {"responses": {"entity": {"results": []}}}

    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            # For external-content FTS5 (focused.db) the name column is in entity_names;
            # for the original full index it's stored directly in names_fts.
            # Both schemas expose entity_id and name through the same virtual table interface.
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

    log.info("done", candidates=len(rows), hits=len(results), db=db_path.name)
    return {"responses": {"entity": {"results": results}}}
