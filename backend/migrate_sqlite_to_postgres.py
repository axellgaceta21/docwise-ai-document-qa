"""One-time, non-destructive SQLite to PostgreSQL transfer.

Run only against a new, empty PostgreSQL database. The SQLite source is read-only.
"""
import argparse
import sqlite3
from pathlib import Path

from psycopg import sql

from app.db import database, init_db


TABLES = (
    "sessions", "documents", "requirements", "findings", "requirement_reviews",
    "corrections", "revisions", "audit_events", "ai_cache", "api_usage",
)


def transfer(source_path: Path) -> dict[str, int]:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    init_db()
    counts: dict[str, int] = {}
    with sqlite3.connect(f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        with database() as target:
            # Never merge blindly into visitor data already present in the target.
            for table in TABLES:
                existing = target.execute(sql.SQL("SELECT COUNT(*) AS count FROM {}").format(
                    sql.Identifier(table))).fetchone()["count"]
                if existing:
                    raise RuntimeError(f"PostgreSQL table {table} is not empty; transfer aborted")
            for table in TABLES:
                if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    counts[table] = 0
                    continue
                source_columns = [row["name"] for row in source.execute(f"PRAGMA table_info({table})")]
                target_columns = {row["column_name"] for row in target.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=%s", (table,))}
                columns = [name for name in source_columns if name in target_columns]
                if set(source_columns) - target_columns:
                    raise RuntimeError(f"Source table {table} has unknown columns; transfer aborted")
                rows = source.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                for row in rows:
                    target.execute(statement, tuple(row[name] for name in columns))
                counts[table] = len(rows)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_file", type=Path)
    args = parser.parse_args()
    for table_name, count in transfer(args.sqlite_file).items():
        print(f"{table_name}: {count}")
