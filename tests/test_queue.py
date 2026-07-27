import sqlite3
import threading

from repopilot.queue import ReviewQueue


def test_queue_reclaims_interrupted_jobs(tmp_path) -> None:
    database = tmp_path / "queue.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE review_jobs (job_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
            "status TEXT NOT NULL, attempts INTEGER NOT NULL, available_at REAL NOT NULL, "
            "last_error TEXT)"
        )
        connection.execute(
            "INSERT INTO review_jobs VALUES ('job-1', '{\"value\": 1}', 'running', 1, 0, NULL)"
        )
    completed = threading.Event()
    queue = ReviewQueue(str(database), lambda _payload: completed.set())
    assert completed.wait(timeout=2)
    queue.close()
