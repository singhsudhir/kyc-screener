#!/usr/bin/env python3
"""Build a compact SQLite FTS5 index from high-authority sanctions lists only.

Input:  data/sanctions/sanctions.json  (~2.6 GB, FTM newline-delimited JSON)
Output: data/sanctions/focused.db      (SQLite with FTS5, target ~20–50 MB)

Included datasets (all core, government-issued sanctions + Interpol):
  us_ofac_sdn            US OFAC Specially Designated Nationals
  us_ofac_cons           US OFAC Consolidated (EO-based lists)
  eu_fsf                 EU Consolidated Sanctions
  un_sc_sanctions        UN Security Council
  gb_hmt_sanctions       UK HM Treasury Financial Sanctions
  ch_seco_sanctions      Switzerland SECO
  fr_tresor_gels_avoir   France Treasury asset freezes
  ua_nsdc_sanctions      Ukraine NSDC
  us_trade_csl           US Commerce Dept. Combined Sanctions List
  interpol_red_notices   Interpol Red Notices
  ca_dfatd_sema_sanctions Canada SEMA
  au_dfat_sanctions      Australia DFAT
  jp_mof_sanctions       Japan MOF
  sg_mas_sanctions       Singapore MAS

Run from the project root:
    python scripts/build_focused_sanctions_index.py
"""
from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FTM_FILE = ROOT / "data" / "sanctions" / "sanctions.json"
DB_FILE  = ROOT / "data" / "sanctions" / "focused.db"
GZ_FILE  = ROOT / "data" / "sanctions" / "focused.db.gz"
BATCH_SIZE = 5_000

FOCUSED_DATASETS: frozenset[str] = frozenset({
    "us_ofac_sdn",
    "us_ofac_cons",
    "eu_fsf",
    "un_sc_sanctions",
    "gb_hmt_sanctions",
    "ch_seco_sanctions",
    "fr_tresor_gels_avoir",
    "ua_nsdc_sanctions",
    "us_trade_csl",
    "interpol_red_notices",
    "ca_dfatd_sema_sanctions",
    "au_dfat_sanctions",
    "jp_mof_sanctions",
    "sg_mas_sanctions",
})

# Only store these property keys — keeps the DB small
_KEEP_PROPS = {
    "name", "alias", "weakAlias",
    "country", "nationality", "jurisdiction",
    "topics",
    "birthDate", "birthPlace",
    "position", "description",
    "programId", "program",
    "sourceUrl",
}


def _trim_props(props: dict) -> dict:
    return {k: v for k, v in props.items() if k in _KEEP_PROPS}


def _create_schema(con: sqlite3.Connection) -> None:
    # Use external-content FTS5: stores only the inverted index, not a copy of name strings.
    # This cuts FTS table size roughly in half vs. a normal (content-storing) FTS5 table.
    con.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous  = NORMAL;
        PRAGMA temp_store   = MEMORY;
        PRAGMA cache_size   = -65536;

        DROP TABLE IF EXISTS entities;
        DROP TABLE IF EXISTS entity_names;
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

        -- Content table for external-content FTS5 (no content duplication in FTS)
        CREATE TABLE entity_names (
            entity_id TEXT NOT NULL,
            name      TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE names_fts USING fts5(
            entity_id,
            name,
            content="entity_names",
            content_rowid="rowid",
            tokenize = 'unicode61 remove_diacritics 1'
        );
    """)
    con.commit()


def _flush(con: sqlite3.Connection, entity_rows: list, name_rows: list) -> None:
    con.executemany("INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?,?)", entity_rows)
    con.executemany("INSERT INTO entity_names(entity_id, name) VALUES (?,?)", name_rows)
    con.commit()


def build_index() -> None:
    if not FTM_FILE.exists():
        sys.exit(
            f"FTM file not found: {FTM_FILE}\nDownload it first:\n"
            "  mkdir -p data/sanctions\n"
            "  curl -o data/sanctions/sanctions.json "
            "https://data.opensanctions.org/datasets/latest/default/entities.ftm.json"
        )

    print(f"Building focused index from {FTM_FILE} → {DB_FILE}")
    print(f"Included datasets: {', '.join(sorted(FOCUSED_DATASETS))}\n")
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DB_FILE.exists():
        DB_FILE.unlink()

    con = sqlite3.connect(DB_FILE)
    _create_schema(con)

    entity_rows: list[tuple] = []
    name_rows:   list[tuple] = []
    count         = 0
    total_lines   = 0
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

            datasets: list[str] = rec.get("datasets", [])
            if not FOCUSED_DATASETS.intersection(datasets):
                continue

            eid     = rec["id"]
            caption = rec.get("caption", "")
            schema  = rec.get("schema", "")
            props   = rec.get("properties", {})
            topics  = json.dumps(props.get("topics", []))
            country = json.dumps(props.get("country", []))
            trimmed = json.dumps(_trim_props(props))

            entity_rows.append((eid, caption, schema, json.dumps(datasets), topics, country, trimmed))

            # Index caption + primary names only (skip alias/weakAlias to keep FTS small)
            names: set[str] = {caption}
            for n in props.get("name", []):
                if n:
                    names.add(n)
            for n in names:
                name_rows.append((eid, n))

            count += 1
            if count % BATCH_SIZE == 0:
                _flush(con, entity_rows, name_rows)
                entity_rows.clear()
                name_rows.clear()
                elapsed = time.monotonic() - t0
                rate = count / max(elapsed, 0.001)
                print(
                    f"\r  {count:>8,} entities | {total_lines:>10,} lines | "
                    f"{elapsed:5.0f}s | {rate:,.0f} ent/s",
                    end="", flush=True,
                )

    if entity_rows:
        _flush(con, entity_rows, name_rows)

    print(f"\n\nBuilding FTS index from entity_names...")
    con.execute(
        "INSERT INTO names_fts(rowid, entity_id, name) "
        "SELECT rowid, entity_id, name FROM entity_names"
    )
    con.commit()

    print("Optimising FTS index...")
    con.execute("INSERT INTO names_fts(names_fts) VALUES('optimize')")
    con.execute("PRAGMA journal_mode=DELETE")
    con.commit()
    con.execute("VACUUM")
    con.commit()
    con.close()

    size_mb = DB_FILE.stat().st_size / 1_048_576
    elapsed = time.monotonic() - t0
    print(f"Done: {count:,} entities in {elapsed:.0f}s → {DB_FILE} ({size_mb:.1f} MB)")

    print(f"Compressing to {GZ_FILE} ...")
    t1 = time.monotonic()
    with open(DB_FILE, "rb") as f_in, gzip.open(GZ_FILE, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    gz_mb = GZ_FILE.stat().st_size / 1_048_576
    print(f"Compressed: {gz_mb:.1f} MB in {time.monotonic()-t1:.0f}s  ← commit this file")


if __name__ == "__main__":
    build_index()
