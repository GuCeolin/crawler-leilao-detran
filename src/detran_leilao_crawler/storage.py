from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from .models import Auction, Lot, LotImage


def _to_jsonable(obj):
    if is_dataclass(obj):
        obj = asdict(obj)
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def write_json(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [_to_jsonable(r) for r in rows]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_list = [_to_jsonable(r) for r in rows]
    if not rows_list:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(rows_list[0].keys()))
        writer.writeheader()
        for r in rows_list:
            writer.writerow(r)


def write_parquet_optional(path: Path, rows: Iterable[object]) -> None:
    # Not required; kept as a convenient internal function if desired later.
    df = pd.DataFrame([_to_jsonable(r) for r in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def init_sqlite(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auctions (
              auction_id TEXT PRIMARY KEY,
              url TEXT,
              number TEXT,
              city TEXT,
              yard TEXT,
              organizer TEXT,
              status TEXT,
              ends_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lots (
              auction_id TEXT,
              lot_id TEXT,
              description_short TEXT,
              brand_model TEXT,
              year INTEGER,
              situation TEXT,
              start_bid REAL,
              ends_at TEXT,
              lot_url TEXT,
              requires_login INTEGER,
              raw_text TEXT,
              PRIMARY KEY (auction_id, lot_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
              auction_id TEXT,
              lot_id TEXT,
              url TEXT,
              PRIMARY KEY (auction_id, lot_id, url)
            )
            """
        )
        con.commit()
    finally:
        con.close()


def upsert_sqlite(
    db_path: Path,
    auctions: Iterable[Auction],
    lots: Iterable[Lot],
    images: Iterable[LotImage],
) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO auctions
            (auction_id, url, number, city, yard, organizer, status, ends_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    a.auction_id,
                    a.url,
                    a.number,
                    a.city,
                    a.yard,
                    a.organizer,
                    a.status,
                    a.ends_at.isoformat() if a.ends_at else None,
                )
                for a in auctions
            ],
        )
        cur.executemany(
            """
            INSERT OR REPLACE INTO lots
            (auction_id, lot_id, description_short, brand_model, year, situation, start_bid, ends_at, lot_url, requires_login, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    l.auction_id,
                    l.lot_id,
                    l.description_short,
                    l.brand_model,
                    l.year,
                    l.situation,
                    l.start_bid,
                    l.ends_at.isoformat() if l.ends_at else None,
                    l.lot_url,
                    1 if l.requires_login else 0,
                    l.raw_text,
                )
                for l in lots
            ],
        )
        cur.executemany(
            """
            INSERT OR REPLACE INTO images
            (auction_id, lot_id, url)
            VALUES (?, ?, ?)
            """,
            [(i.auction_id, i.lot_id, i.url) for i in images],
        )
        con.commit()
    finally:
        con.close()
