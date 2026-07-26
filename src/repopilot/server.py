"""Secure HTTP entry point for GitHub pull request webhooks."""

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from .github import GitHubClient
from .service import start_review_from_event
from .workflow import build_review_workflow


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
) -> FastAPI:
    """Create the webhook app with injectable dependencies for tests."""
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        checkpoint_context.__exit__(None, None, None)

    app = FastAPI(title="ReviewForge", version="0.1.0", lifespan=lifespan)
    client = github or GitHubClient(os.environ["GITHUB_TOKEN"])
    secret = webhook_secret or os.environ["GITHUB_WEBHOOK_SECRET"]
    checkpoint_context = SqliteSaver.from_conn_string(
        checkpoint_db or os.environ.get("CHECKPOINT_DB", "reviewforge-checkpoints.sqlite")
    )
    checkpointer = checkpoint_context.__enter__()
    checkpointer.setup()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default=""),
        x_hub_signature_256: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = await request.body()
        if not verify_signature(body, x_hub_signature_256, secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        if x_github_event != "pull_request":
            return {"status": "ignored", "event": x_github_event}
        payload = json.loads(body)
        result = start_review_from_event(payload, client, model=model, checkpointer=checkpointer)
        return {"status": "review_started", "interrupted": "__interrupt__" in result}

    @app.post("/reviews/{repository:path}/{pull_request_number}/approval")
    async def approve_review(
        repository: str,
        pull_request_number: int,
        decision: ApprovalRequest,
    ) -> dict[str, Any]:
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

    return app


def main() -> None:
    """Run the webhook server locally."""
    import uvicorn

    uvicorn.run("repopilot.server:create_app", factory=True, host="0.0.0.0", port=8000)
