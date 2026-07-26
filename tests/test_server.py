import hashlib
import hmac

from fastapi.testclient import TestClient

from repopilot.server import create_app


def test_health_endpoint() -> None:
    assert TestClient(create_app(github=object(), webhook_secret="secret")).get(
        "/healthz"
    ).json() == {"status": "ok"}


def test_webhook_rejects_invalid_signature() -> None:
    client = TestClient(create_app(github=object(), webhook_secret="secret"))
    response = client.post("/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "ping"})
    assert response.status_code == 401


def test_webhook_ignores_non_pull_request_events() -> None:
    body = b"{}"
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    client = TestClient(create_app(github=object(), webhook_secret="secret"))
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": signature},
    )
    assert response.json() == {"status": "ignored", "event": "ping"}
