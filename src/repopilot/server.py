"""Secure HTTP entry point for GitHub pull request webhooks."""

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from .github import GitHubClient
from .service import start_review_from_event
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


def create_app(
    *,
    github: GitHubClient | None = None,
    webhook_secret: str | None = None,
    model: Any | None = None,
    checkpoint_db: str | None = None,
    approval_token: str | None = None,
) -> FastAPI:
    """Create the webhook app with injectable dependencies for tests."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        delivery_db.close()
        checkpoint_context.__exit__(None, None, None)

    app = FastAPI(title="ReviewForge", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        started = time.perf_counter()
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

    client = github or GitHubClient(os.environ["GITHUB_TOKEN"])
    secret = webhook_secret or os.environ["GITHUB_WEBHOOK_SECRET"]
    maintainer_token = approval_token or os.environ.get("APPROVAL_TOKEN")
    if not maintainer_token:
        raise RuntimeError("APPROVAL_TOKEN must be configured")
    checkpoint_context = SqliteSaver.from_conn_string(
        checkpoint_db or os.environ.get("CHECKPOINT_DB", "reviewforge-checkpoints.sqlite")
    )
    checkpointer = checkpoint_context.__enter__()
    checkpointer.setup()
    delivery_db = sqlite3.connect(
        checkpoint_db or os.environ.get("CHECKPOINT_DB", "reviewforge-checkpoints.sqlite"),
        check_same_thread=False,
    )
    delivery_db.execute(
        "CREATE TABLE IF NOT EXISTS webhook_deliveries "
        "(delivery_id TEXT PRIMARY KEY, received_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    delivery_db.commit()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

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
        result = start_review_from_event(payload, client, model=model, checkpointer=checkpointer)
        return {"status": "review_started", "interrupted": "__interrupt__" in result}

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


def main() -> None:
    """Run the webhook server locally."""
    import uvicorn

    uvicorn.run("repopilot.server:create_app", factory=True, host="0.0.0.0", port=8000)
