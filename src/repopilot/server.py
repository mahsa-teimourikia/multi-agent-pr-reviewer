"""Secure HTTP entry point for GitHub pull request webhooks."""

import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from .github import GitHubClient
from .service import start_review_from_event


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
) -> FastAPI:
    """Create the webhook app with injectable dependencies for tests."""
    app = FastAPI(title="ReviewForge", version="0.1.0")
    client = github or GitHubClient(os.environ["GITHUB_TOKEN"])
    secret = webhook_secret or os.environ["GITHUB_WEBHOOK_SECRET"]

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
        result = start_review_from_event(payload, client)
        return {"status": "review_started", "interrupted": "__interrupt__" in result}

    return app


def main() -> None:
    """Run the webhook server locally."""
    import uvicorn

    uvicorn.run("repopilot.server:create_app", factory=True, host="0.0.0.0", port=8000)
