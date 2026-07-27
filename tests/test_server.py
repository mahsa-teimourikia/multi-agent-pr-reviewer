import hashlib
import hmac
import time

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
    response = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "a.db"),
        )
    ).get("/healthz", headers={"X-Request-ID": "request-123"})
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "request-123"


def test_storage_uses_wal_mode(tmp_path) -> None:
    database = tmp_path / "wal.db"
    client = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(database),
        )
    )
    client.close()
    import sqlite3

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_metrics_requires_auth_and_reports_requests(tmp_path) -> None:
    client = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "metrics.db"),
        )
    )
    assert client.get("/metrics").status_code == 401
    response = client.get("/metrics", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    assert "reviewforge_requests_total" in response.text


def test_rate_limit_returns_429(tmp_path) -> None:
    client = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "limit.db"),
            rate_limit_per_minute=1,
        )
    )
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").status_code == 429


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


def test_webhook_ignores_irrelevant_pull_request_actions(tmp_path) -> None:
    body = b'{"action":"closed"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    client = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "closed.db"),
        )
    )
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature},
    )
    assert response.json() == {
        "status": "ignored",
        "event": "pull_request",
        "action": "closed",
    }


def test_webhook_rejects_invalid_json(tmp_path) -> None:
    body = b"not-json"
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    client = TestClient(
        create_app(
            github=object(),
            webhook_secret="secret",
            approval_token="token",
            checkpoint_db=str(tmp_path / "invalid.db"),
        )
    )
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature},
    )
    assert response.status_code == 400


def test_approval_endpoint_resumes_and_publishes_review(tmp_path) -> None:
    body = (
        b'{"action":"opened","repository":{"full_name":"owner/project"},'
        b'"pull_request":{"number":5}}'
    )
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
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "delivery-1",
        },
    )
    assert started.json() == {"status": "review_queued", "delivery_id": "delivery-1"}
    for _ in range(20):
        pending = client.get(
            "/reviews/owner/project/5",
            headers={"Authorization": "Bearer token"},
        )
        if pending.status_code == 200:
            break
        time.sleep(0.01)
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert "Test" in pending.json()["review"]
    duplicate = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "delivery-1",
        },
    )
    assert duplicate.json() == {"status": "duplicate", "delivery_id": "delivery-1"}
    unauthorized = client.post("/reviews/owner/project/5/approval", json={"approved": True})
    assert unauthorized.status_code == 401
    approved = client.post(
        "/reviews/owner/project/5/approval",
        json={"approved": True},
        headers={"Authorization": "Bearer token"},
    )
    assert approved.json() == {"status": "published", "review_posted": True}
    assert github.published is True


def test_pending_review_survives_server_restart(tmp_path) -> None:
    body = (
        b'{"action":"opened","repository":{"full_name":"owner/project"},'
        b'"pull_request":{"number":8}}'
    )
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    database = str(tmp_path / "restart.db")
    first_github = FakeGitHub()
    with TestClient(
        create_app(
            github=first_github,
            webhook_secret="secret",
            model=FakeModel(),
            approval_token="token",
            checkpoint_db=database,
        )
    ) as first:
        response = first.post(
            "/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature},
        )
        assert response.status_code == 200

    second_github = FakeGitHub()
    with TestClient(
        create_app(
            github=second_github,
            webhook_secret="secret",
            model=FakeModel(),
            approval_token="token",
            checkpoint_db=database,
        )
    ) as second:
        status = second.get(
            "/reviews/owner/project/8",
            headers={"Authorization": "Bearer token"},
        )
        assert status.json()["status"] == "pending"
        approved = second.post(
            "/reviews/owner/project/8/approval",
            json={"approved": True},
            headers={"Authorization": "Bearer token"},
        )
        assert approved.json()["review_posted"] is True
        assert second_github.published is True


def test_approval_ui_loads_and_publishes_review(tmp_path) -> None:
    body = (
        b'{"action":"opened","repository":{"full_name":"owner/project"},'
        b'"pull_request":{"number":9}}'
    )
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    github = FakeGitHub()
    with TestClient(
        create_app(
            github=github,
            webhook_secret="secret",
            model=FakeModel(),
            approval_token="token",
            checkpoint_db=str(tmp_path / "ui.db"),
        )
    ) as client:
        client.post(
            "/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature},
        )
        time.sleep(0.05)
        page = client.post(
            "/reviews/owner/project/9/approval-ui",
            data={"token": "token"},
        )
        assert page.status_code == 200
        assert "Test" in page.text
        published = client.post(
            "/reviews/owner/project/9/approval-ui",
            data={"token": "token", "approved": "true"},
        )
        assert "Review published" in published.text
        assert github.published is True
