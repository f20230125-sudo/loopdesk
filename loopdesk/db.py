"""Small DB-API repository. SQL stays parameterized on SQLite and PostgreSQL."""
import sqlite3
import re
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g


class Database:
    def __init__(self, url, schema=None):
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        self.schema = schema
        if schema and not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("Database schema must be a lowercase SQL identifier of at most 63 characters.")
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
        else:
            if not url.startswith("sqlite:///"):
                raise ValueError("DATABASE_URL must use sqlite:///, postgres:// or postgresql://.")
            if schema:
                raise ValueError("A separate database schema is supported only with PostgreSQL.")
            path = url.removeprefix("sqlite:///")
            self.conn = sqlite3.connect(path, timeout=15)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=15000")

    def execute(self, sql, args=()):
        if self.postgres:
            from psycopg.pq import TransactionStatus
            if self.conn.info.transaction_status == TransactionStatus.IDLE:
                # Reapply per transaction: pooled endpoints can switch server sessions at commit.
                self.conn.execute("SET LOCAL statement_timeout TO 15000")
                if self.schema:
                    self.conn.execute("SELECT set_config('search_path', %s, true)", (self.schema,))
        return self.conn.execute(sql.replace("?", "%s") if self.postgres else sql, args)

    def all(self, sql, args=()):
        return [dict(r) for r in self.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        row = self.execute(sql, args).fetchone()
        return dict(row) if row else None

    @contextmanager
    def transaction(self):
        try:
            yield self
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def close(self):
        try:
            self.conn.rollback()
        finally:
            self.conn.close()


def get_db():
    if "db" not in g:
        g.db = Database(current_app.config["DATABASE_URL"], current_app.config.get("DATABASE_SCHEMA"))
    return g.db


def migrate(db):
    """Forward-only migrations. Run explicitly once before serving traffic."""
    folder = Path(__file__).resolve().parents[1] / "migrations"
    with db.transaction():
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)")
        for path in sorted(folder.glob("*.sql")):
            if db.one("SELECT version FROM schema_migrations WHERE version=?", (path.stem,)):
                continue
            for statement in path.read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (path.stem,))
