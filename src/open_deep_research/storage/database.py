"""Shared SQLite storage for repository snapshots and research history."""

import sqlite3
from pathlib import Path


def connect_database(database):
    """Initialize both application tables, retaining existing history records."""
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            # Serialize schema upgrades across concurrent first connections.
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''CREATE TABLE IF NOT EXISTS repository_snapshots (
                root TEXT PRIMARY KEY, data TEXT NOT NULL
            )''')
            connection.execute('''CREATE TABLE IF NOT EXISTS research_history (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, question TEXT NOT NULL,
                brief TEXT NOT NULL, report TEXT NOT NULL, created_at TEXT NOT NULL,
                model_identity TEXT NOT NULL, dimension INTEGER NOT NULL, vector TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )''')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(research_history)')}
            if 'metadata' not in columns:
                connection.execute("ALTER TABLE research_history ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            connection.execute('CREATE INDEX IF NOT EXISTS history_scope ON research_history(scope,model_identity)')
        return connection
    except Exception:
        connection.close()
        raise
