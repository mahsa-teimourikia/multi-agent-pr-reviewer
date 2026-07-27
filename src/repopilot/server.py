"""Secure HTTP entry point for GitHub pull request webhooks."""

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from html import escape
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from .github import GitHubClient
from .queue import ReviewQueue
from .service import start_review_from_event
from .storage import connect_sqlite
from .workflow import build_review_workflow

logger = logging.getLogger("reviewforge")


class ApprovalRequest(BaseModel):
    """Maintainer decision for a paused review."""

    approved: bool


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Verify GitHub's HMAC-SHA256 webhook signature."""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def run_review_job(
    payload: dict[str, Any],
    github: GitHubClient,
    model: Any | None,
    checkpoint_path: str,
) -> None:
    """Run a background review with a worker-owned checkpoint connection."""
    with SqliteSaver.from_conn_string(checkpoint_path) as worker_checkpointer:
        worker_checkpointer.setup()
        start_review_from_event(
            payload,
            github,
            model=model,
            checkpointer=worker_checkpointer,
        )


def create_app(
    *,
    github: GitHubClient | None = None,
    webhook_secret: str | None = None,
    model: Any | None = None,
    checkpoint_db: str | None = None,
    approval_token: str | None = None,
    rate_limit_per_minute: int = 60,
) -> FastAPI:
    """Create the webhook app with injectable dependencies for tests."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        review_queue.close()
        delivery_db.close()
        checkpoint_context.__exit__(None, None, None)

    app = FastAPI(title="ReviewForge", version="0.1.0", lifespan=lifespan)
    request_counts: dict[str, deque[float]] = defaultdict(deque)
    metrics = {"requests": 0, "rate_limited": 0}

    @app.middleware("http")
    async def request_logging(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        started = time.perf_counter()
        now = time.time()
        source = request.client.host if request.client else "unknown"
        timestamps = request_counts[source]
        while timestamps and timestamps[0] <= now - 60:
            timestamps.popleft()
        if len(timestamps) >= rate_limit_per_minute:
            metrics["rate_limited"] += 1
            return Response("Too many requests", status_code=429, headers={"Retry-After": "60"})
        timestamps.append(now)
        metrics["requests"] += 1
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    client = github or GitHubClient.from_environment()
    secret = webhook_secret or os.environ["GITHUB_WEBHOOK_SECRET"]
    maintainer_token = approval_token or os.environ.get("APPROVAL_TOKEN")
    if not maintainer_token:
        raise RuntimeError("APPROVAL_TOKEN must be configured")
    checkpoint_context = SqliteSaver.from_conn_string(
        checkpoint_db or os.environ.get("CHECKPOINT_DB", "reviewforge-checkpoints.sqlite")
    )
    checkpointer = checkpoint_context.__enter__()
    checkpointer.setup()
    checkpoint_path = checkpoint_db or os.environ.get(
        "CHECKPOINT_DB", "reviewforge-checkpoints.sqlite"
    )
    delivery_db = connect_sqlite(
        checkpoint_db or os.environ.get("CHECKPOINT_DB", "reviewforge-checkpoints.sqlite")
    )
    delivery_db.execute(
        "CREATE TABLE IF NOT EXISTS webhook_deliveries "
        "(delivery_id TEXT PRIMARY KEY, received_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    delivery_db.commit()
    review_queue = ReviewQueue(
        checkpoint_path,
        lambda payload: run_review_job(payload, client, model, checkpoint_path),
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint(authorization: str | None = Header(default=None)) -> Response:
        expected = f"Bearer {maintainer_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid metrics credentials")
        body = "\n".join(
            [
                "# TYPE reviewforge_requests_total counter",
                f"reviewforge_requests_total {metrics['requests']}",
                "# TYPE reviewforge_rate_limited_total counter",
                f"reviewforge_rate_limited_total {metrics['rate_limited']}",
            ]
        )
        return Response(body + "\n", media_type="text/plain")

    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default=""),
        x_hub_signature_256: str | None = Header(default=None),
        x_github_delivery: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = await request.body()
        if not verify_signature(body, x_hub_signature_256, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        if x_github_event != "pull_request":
            return {"status": "ignored", "event": x_github_event}
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
        action = payload.get("action")
        if action not in {"opened", "synchronize", "reopened"}:
            return {"status": "ignored", "event": x_github_event, "action": action}
        if x_github_delivery:
            inserted = delivery_db.execute(
                "INSERT OR IGNORE INTO webhook_deliveries (delivery_id) VALUES (?)",
                (x_github_delivery,),
            ).rowcount
            delivery_db.commit()
            if not inserted:
                return {"status": "duplicate", "delivery_id": x_github_delivery}
        review_queue.enqueue(payload)
        return {"status": "review_queued", "delivery_id": x_github_delivery}

    @app.post("/reviews/{repository:path}/{pull_request_number}/approval")
    async def approve_review(
        repository: str,
        pull_request_number: int,
        decision: ApprovalRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        expected = f"Bearer {maintainer_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid approval credentials")
        workflow = build_review_workflow(
            model=model,
            publisher=client.post_review,
            checkpointer=checkpointer,
        )
        thread_id = f"{repository}#{pull_request_number}"
        result = workflow.invoke(
            Command(resume={"approved": decision.approved}),
            {"configurable": {"thread_id": thread_id}},
        )
        return {
            "status": "published" if result.get("review_posted") else "rejected",
            "review_posted": result.get("review_posted", False),
        }

    @app.get(
        "/reviews/{repository:path}/{pull_request_number}/approval-ui",
        response_class=HTMLResponse,
    )
    async def approval_ui(repository: str, pull_request_number: int) -> str:
        """Render a token-protected maintainer approval form."""
        return _approval_page(repository, pull_request_number)

    @app.post(
        "/reviews/{repository:path}/{pull_request_number}/approval-ui",
        response_class=HTMLResponse,
    )
    async def submit_approval_ui(
        repository: str, pull_request_number: int, request: Request
    ) -> str:
        form = parse_qs((await request.body()).decode("utf-8"))
        token = form.get("token", [""])[0]
        expected = f"Bearer {maintainer_token}"
        if not hmac.compare_digest(f"Bearer {token}", expected):
            raise HTTPException(status_code=401, detail="Invalid approval credentials")
        workflow = build_review_workflow(
            model=model,
            publisher=client.post_review,
            checkpointer=checkpointer,
        )
        thread_id = f"{repository}#{pull_request_number}"
        snapshot = workflow.get_state({"configurable": {"thread_id": thread_id}})
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Review not found")
        decision = form.get("approved", [""])[0]
        if decision in {"true", "false"}:
            result = workflow.invoke(
                Command(resume={"approved": decision == "true"}),
                {"configurable": {"thread_id": thread_id}},
            )
            message = "Review published." if result.get("review_posted") else "Review rejected."
            return _approval_page(repository, pull_request_number, message=message)
        return _approval_page(
            repository,
            pull_request_number,
            review=str(snapshot.values.get("final_review", "")),
            token=token,
        )

    @app.get("/reviews/{repository:path}/{pull_request_number}")
    async def review_status(
        repository: str,
        pull_request_number: int,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        expected = f"Bearer {maintainer_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid approval credentials")
        workflow = build_review_workflow(
            model=model,
            publisher=client.post_review,
            checkpointer=checkpointer,
        )
        snapshot = workflow.get_state(
            {"configurable": {"thread_id": f"{repository}#{pull_request_number}"}}
        )
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Review not found")
        values = snapshot.values
        status = (
            "published"
            if values.get("review_posted")
            else "rejected"
            if values.get("approval") is False
            else "pending"
        )
        return {
            "status": status,
            "repository": repository,
            "pull_request_number": pull_request_number,
            "review": values.get("final_review"),
        }

    return app


def _approval_page(
    repository: str,
    pull_request_number: int,
    *,
    review: str = "",
    token: str = "",
    message: str = "",
) -> str:
    """Build the small dependency-free approval page."""
    review_html = f"<pre>{escape(review)}</pre>" if review else ""
    message_html = f"<p role='status'>{escape(message)}</p>" if message else ""
    token_html = escape(token)
    actions = (
        "<button name='approved' value='true'>Approve and publish</button>"
        "<button name='approved' value='false'>Reject</button>"
        if review
        else "<button>Load review</button>"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ReviewForge approval</title>
<style>body{{font:16px system-ui;max-width:900px;margin:3rem auto;padding:0 1rem}}
pre{{white-space:pre-wrap;background:#f4f4f4;padding:1rem}}
button{{margin-right:.5rem;padding:.6rem 1rem}}</style>
</head><body><h1>ReviewForge approval</h1><p>{escape(repository)} #{pull_request_number}</p>
{message_html}{review_html}<form method="post">
<label>Approval token <input type="password" name="token" value="{token_html}"
required></label><br><br>{actions}
</form></body></html>"""


def main() -> None:
    """Run the webhook server locally."""
    import uvicorn

    uvicorn.run("repopilot.server:create_app", factory=True, host="0.0.0.0", port=8000)
