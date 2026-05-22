#!/usr/bin/env python3
"""Build a SQLite FTS5 index from the OpenSanctions FTM dataset.

Input:  data/sanctions/sanctions.json  (~2.6 GB, FTM newline-delimited JSON)
Output: data/sanctions/sanctions.db   (SQLite with FTS5, ~400–600 MB)

Run from the project root:
    python scripts/build_sanctions_index.py

Only target=true entities (sanctioned, PEP, wanted) are indexed — ~1.3M of 4.3M records.
Subsequent runs drop and rebuild the DB from scratch.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FTM_FILE = ROOT / "data" / "sanctions" / "sanctions.json"
DB_FILE = ROOT / "data" / "sanctions" / "sanctions.db"
BATCH_SIZE = 5_000


def _create_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous  = NORMAL;
        PRAGMA temp_store   = MEMORY;
        PRAGMA cache_size   = -65536;

        DROP TABLE IF EXISTS entities;
        DROP TABLE IF EXISTS names_fts;

        CREATE TABLE entities (
            id         TEXT PRIMARY KEY,
            caption    TEXT NOT NULL,
            schema     TEXT NOT NULL,
            datasets   TEXT NOT NULL,
            topics     TEXT NOT NULL,
            country    TEXT NOT NULL,
            properties TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE names_fts USING fts5(
            entity_id  UNINDEXED,
            name,
            tokenize = 'unicode61 remove_diacritics 1'
        );
    """)
    con.commit()


def _flush(
    con: sqlite3.Connection,
    entity_rows: list[tuple],
    name_rows: list[tuple],
) -> None:
    con.executemany("INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?,?)", entity_rows)
    con.executemany("INSERT INTO names_fts VALUES (?,?)", name_rows)
    con.commit()


def build_index() -> None:
    if not FTM_FILE.exists():
        sys.exit(f"FTM file not found: {FTM_FILE}\nDownload it first:\n"
                 "  mkdir -p data/sanctions\n"
                 "  curl -o data/sanctions/sanctions.json "
                 "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json")

    print(f"Building index from {FTM_FILE} → {DB_FILE}")
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DB_FILE.exists():
        DB_FILE.unlink()

    con = sqlite3.connect(DB_FILE)
    _create_schema(con)

    entity_rows: list[tuple] = []
    name_rows: list[tuple] = []
    count = 0
    total_lines = 0
    t0 = time.monotonic()

    with open(FTM_FILE, encoding="utf-8") as f:
        for line in f:
            total_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not rec.get("target"):
                continue

            eid = rec["id"]
            caption = rec.get("caption", "")
            schema = rec.get("schema", "")
            datasets = json.dumps(rec.get("datasets", []))
            props = rec.get("properties", {})
            topics = json.dumps(props.get("topics", []))
            country = json.dumps(props.get("country", []))
            properties = json.dumps(props)

            entity_rows.append((eid, caption, schema, datasets, topics, country, properties))

            names: set[str] = {caption}
            for n in props.get("name", []):
                if n:
                    names.add(n)
            for a in props.get("alias", []):
                if a:
                    names.add(a)
            for n in names:
                name_rows.append((eid, n))

            count += 1
            if count % BATCH_SIZE == 0:
                _flush(con, entity_rows, name_rows)
                entity_rows.clear()
                name_rows.clear()
                elapsed = time.monotonic() - t0
                rate = count / elapsed
                print(
                    f"\r  {count:>9,} entities | {total_lines:>10,} lines | "
                    f"{elapsed:5.0f}s | {rate:,.0f} ent/s",
                    end="",
                    flush=True,
                )

    if entity_rows:
        _flush(con, entity_rows, name_rows)

    print(f"\n  Optimising FTS index...")
    con.execute("INSERT INTO names_fts(names_fts) VALUES('optimize')")
    con.commit()

    size_mb = DB_FILE.stat().st_size / 1024 / 1024
    elapsed = time.monotonic() - t0
    print(f"Done: {count:,} entities indexed in {elapsed:.0f}s → {DB_FILE} ({size_mb:.0f} MB)")
    con.close()


if __name__ == "__main__":
    build_index()
