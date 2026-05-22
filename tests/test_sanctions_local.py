from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.sanctions_local import _normalise, _token_score, query_local_sanctions


# ── unit helpers ──────────────────────────────────────────────────────────────

def test_normalise_strips_diacritics():
    assert _normalise("Société Générale") == "societe generale"


def test_normalise_collapses_punctuation():
    assert _normalise("ACME, Corp.") == "acme corp"


def test_token_score_exact():
    assert _token_score("Acme Corp", "Acme Corp") == pytest.approx(1.0)


def test_token_score_partial():
    score = _token_score("Acme Corporation", "Acme Corp International")
    assert 0.0 < score < 1.0


def test_token_score_no_overlap():
    assert _token_score("Alpha Bank", "Beta Holdings") == pytest.approx(0.0)


# ── integration: in-memory DB ────────────────────────────────────────────────

def _make_test_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, caption TEXT NOT NULL, schema TEXT NOT NULL,
            datasets TEXT NOT NULL, topics TEXT NOT NULL,
            country TEXT NOT NULL, properties TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(
            entity_id UNINDEXED, name,
            tokenize='unicode61 remove_diacritics 1'
        );
    """)
    entities = [
        ("E1", "Acme Weapons Ltd", "Company",
         '["us_ofac_sdn"]', '["sanction"]', '["us"]',
         '{"name":["Acme Weapons Ltd","Acme Arms"],"country":["us"],"topics":["sanction"]}'),
        ("E2", "John Smith", "Person",
         '["interpol_red_notices"]', '["wanted"]', '["gb"]',
         '{"name":["John Smith"],"country":["gb"],"topics":["wanted"]}'),
        ("E3", "Totally Unrelated GmbH", "Company",
         '["eu_fsf"]', '["sanction"]', '["de"]',
         '{"name":["Totally Unrelated GmbH"],"country":["de"],"topics":["sanction"]}'),
    ]
    con.executemany("INSERT INTO entities VALUES (?,?,?,?,?,?,?)", entities)
    name_rows = [
        ("E1", "Acme Weapons Ltd"), ("E1", "Acme Arms"),
        ("E2", "John Smith"),
        ("E3", "Totally Unrelated GmbH"),
    ]
    con.executemany("INSERT INTO names_fts VALUES (?,?)", name_rows)
    con.commit()
    con.close()


@pytest.mark.asyncio
async def test_query_local_finds_match():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "sanctions.db"
        _make_test_db(db_path)
        with patch("src.tools.sanctions_local._DB_PATH", db_path):
            result = await query_local_sanctions("Acme Weapons")
    hits = result["responses"]["entity"]["results"]
    assert len(hits) >= 1
    assert hits[0]["id"] == "E1"
    assert hits[0]["score"] > 0.5


@pytest.mark.asyncio
async def test_query_local_no_match():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "sanctions.db"
        _make_test_db(db_path)
        with patch("src.tools.sanctions_local._DB_PATH", db_path):
            result = await query_local_sanctions("XYZ Holdings")
    hits = result["responses"]["entity"]["results"]
    assert hits == []


@pytest.mark.asyncio
async def test_query_local_missing_index():
    with patch("src.tools.sanctions_local._DB_PATH", Path("/nonexistent/path.db")):
        result = await query_local_sanctions("Acme")
    assert "error" in result


@pytest.mark.asyncio
async def test_jurisdiction_boost():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "sanctions.db"
        _make_test_db(db_path)
        with patch("src.tools.sanctions_local._DB_PATH", db_path):
            result_with = await query_local_sanctions("Acme Weapons", jurisdiction="US")
            result_without = await query_local_sanctions("Acme Weapons", jurisdiction=None)
    hits_with = result_with["responses"]["entity"]["results"]
    hits_without = result_without["responses"]["entity"]["results"]
    assert hits_with[0]["score"] >= hits_without[0]["score"]
