#!/usr/bin/env python3
"""
Copy all app tables from local SQLite to Supabase/PostgreSQL.

Usage (from backend/ with venv active):

  # 1) Set Supabase URL in .env (see .env.example)
  # 2) Create empty tables on Supabase:
  python -c "from app.database import create_tables; create_tables()"

  # 3) Migrate data:
  python scripts/migrate_sqlite_to_supabase.py

Optional:
  SQLITE_URL=sqlite:///../data/finrl.db \\
  DATABASE_URL=postgresql://... \\
  python scripts/migrate_sqlite_to_supabase.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    Base,
    User,
    Job,
    Run,
    Backtest,
    Signal,
    SentimentScore,
    PaperSession,
    ModelPerformanceScore,
    _normalize_database_url,
    create_tables,
)

TABLE_MODELS = [
    User,
    Job,
    Run,
    Backtest,
    Signal,
    SentimentScore,
    PaperSession,
    ModelPerformanceScore,
]


def _sqlite_url() -> str:
    return os.getenv(
        "SQLITE_URL",
        f"sqlite:///{BACKEND_ROOT.parent / 'data' / 'finrl.db'}",
    )


def _postgres_url() -> str:
    url = os.getenv("DATABASE_URL", settings.database_url)
    url = _normalize_database_url(url)
    if url.startswith("sqlite"):
        raise SystemExit("DATABASE_URL must be a PostgreSQL/Supabase connection string.")
    return url


def migrate() -> None:
    src_engine = create_engine(_sqlite_url(), connect_args={"check_same_thread": False})
    dst_url = _postgres_url()
    connect_args = {}
    if "supabase.co" in dst_url or "supabase.com" in dst_url:
        connect_args["sslmode"] = os.getenv("DATABASE_SSL_MODE", settings.database_ssl_mode)
    dst_engine = create_engine(dst_url, connect_args=connect_args)

    print(f"Source:  {_sqlite_url()}")
    print(f"Target:  {dst_url.split('@')[-1]}")  # hide credentials

    create_tables()

    src_inspector = inspect(src_engine)
    src_tables = set(src_inspector.get_table_names())
    total = 0

    with Session(src_engine) as src, Session(dst_engine) as dst:
        for model in TABLE_MODELS:
            table = model.__tablename__
            if table not in src_tables:
                print(f"  skip {table} (not in SQLite)")
                continue

            rows = src.query(model).all()
            if not rows:
                print(f"  {table}: 0 rows")
                continue

            dst.query(model).delete()
            for row in rows:
                dst.merge(row)
            dst.commit()
            print(f"  {table}: {len(rows)} rows")
            total += len(rows)

    print(f"\nDone — migrated {total} rows to Supabase/PostgreSQL.")


if __name__ == "__main__":
    migrate()
