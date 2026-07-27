"""A small durable SQLite-backed job queue for webhook-triggered reviews."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, cast

from .storage import connect_sqlite

logger = logging.getLogger("reviewforge")


class ReviewQueue:
    """Persist review jobs and process them with a restart-safe worker."""

    def __init__(self, database: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self.database = database
        self.handler = handler
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="review-queue", daemon=True)
        self._initialize()
        self._thread.start()

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS review_jobs (
                    job_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    last_error TEXT
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS review_jobs_ready_idx "
                "ON review_jobs (status, available_at)"
            )
            # A process may die after claiming a job but before completing it.
            # Requeue those claims so a restart never loses review work.
            connection.execute(
                "UPDATE review_jobs SET status = 'pending', available_at = ? "
                "WHERE status = 'running'",
                (time.time(),),
            )

    def enqueue(self, payload: dict[str, Any]) -> str:
        """Add a review job and return its stable identifier."""
        job_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO review_jobs (job_id, payload, available_at) VALUES (?, ?, ?)",
                (job_id, json.dumps(payload), time.time()),
            )
        self._wake.set()
        return job_id

    def close(self) -> None:
        """Stop the worker and allow an in-flight job to finish."""
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)

    @property
    def is_alive(self) -> bool:
        """Whether the queue worker is available to accept jobs."""
        return self._thread.is_alive() and not self._stop.is_set()

    def _claim(self) -> sqlite3.Row | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM review_jobs WHERE status = 'pending' AND available_at <= ? "
                "ORDER BY available_at LIMIT 1",
                (time.time(),),
            ).fetchone()
            if job is None:
                return None
            connection.execute(
                "UPDATE review_jobs SET status = 'running', attempts = attempts + 1 "
                "WHERE job_id = ?",
                (job["job_id"],),
            )
            return cast(sqlite3.Row, job)

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._claim()
            if job is None:
                self._wake.wait(timeout=1)
                self._wake.clear()
                continue
            try:
                self.handler(json.loads(job["payload"]))
            except Exception as exc:  # pragma: no cover - exercised through retry integration
                logger.exception("review_job_failed job_id=%s", job["job_id"])
                with self._connect() as connection:
                    attempts = int(job["attempts"]) + 1
                    if attempts < 3:
                        connection.execute(
                            "UPDATE review_jobs SET status = 'pending', available_at = ?, "
                            "last_error = ? WHERE job_id = ?",
                            (time.time() + (2**attempts), str(exc), job["job_id"]),
                        )
                    else:
                        connection.execute(
                            "UPDATE review_jobs SET status = 'failed', last_error = ? "
                            "WHERE job_id = ?",
                            (str(exc), job["job_id"]),
                        )
            else:
                with self._connect() as connection:
                    connection.execute(
                        "UPDATE review_jobs SET status = 'completed' WHERE job_id = ?",
                        (job["job_id"],),
                    )
