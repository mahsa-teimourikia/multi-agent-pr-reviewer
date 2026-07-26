import hashlib
import hmac

from fastapi.testclient import TestClient

from repopilot.models import Finding
from repopilot.server import create_app


class FakeModel:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _prompt: str):
        return [Finding(category="logic", severity="info", title="Test", body="Test")]


class FakeGitHub:
    def get_pull_request_diff(self, _repository: str, _number: int) -> str:
        return "diff"

    def post_review(self, _repository: str, _number: int, _body: str) -> None:
        self.published = True


def test_health_endpoint(tmp_path) -> None:
    assert TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "a.db"),
        )
    ).get("/healthz").json() == {"status": "ok"}


def test_webhook_rejects_invalid_signature(tmp_path) -> None:
    client = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "b.db"),
        )
    )
    response = client.post("/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "ping"})
    assert response.status_code == 401


def test_webhook_ignores_non_pull_request_events(tmp_path) -> None:
    body = b"{}"
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    client = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "c.db"),
        )
    )
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": signature},
    )
    assert response.json() == {"status": "ignored", "event": "ping"}


def test_approval_endpoint_resumes_and_publishes_review(tmp_path) -> None:
    body = b'{"repository":{"full_name":"owner/project"},"pull_request":{"number":5}}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    github = FakeGitHub()
    client = TestClient(
        create_app(
            github=github,
            webhook_secret="secret",
            model=FakeModel(),
            approval_token="token",
            checkpoint_db=str(tmp_path / "d.db"),
        )
    )
    started = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature},
    )
    assert started.json() == {"status": "review_started", "interrupted": True}
    unauthorized = client.post("/reviews/owner/project/5/approval", json={"approved": True})
    assert unauthorized.status_code == 401
    approved = client.post(
        "/reviews/owner/project/5/approval",
        json={"approved": True},
        headers={"Authorization": "Bearer token"},
    )
    assert approved.json() == {"status": "published", "review_posted": True}
    assert github.published is True
