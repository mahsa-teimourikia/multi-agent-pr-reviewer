"""SQLite storage configuration shared by the queue and webhook ledger."""

import sqlite3


def connect_sqlite(database: str) -> sqlite3.Connection:
    """Open a durable SQLite connection with production-safe concurrency settings."""
    connection = sqlite3.connect(database, timeout=30, check_same_thread=False)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
