import pytest

from repopilot.github import GitHubClient, PullRequestEvent


def test_pull_request_event_from_payload() -> None:
    event = PullRequestEvent.from_payload(
        {"repository": {"full_name": "owner/project"}, "pull_request": {"number": 42}}
    )
    assert event.repository == "owner/project"
    assert event.pull_request_number == 42


def test_pull_request_event_rejects_incomplete_payload() -> None:
    with pytest.raises(ValueError, match="missing"):
        PullRequestEvent.from_payload({})


def test_github_client_requires_token_or_app_credentials(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        GitHubClient.from_environment()


def test_github_client_uses_app_installation_token(monkeypatch) -> None:
    class FakeAccessToken:
        token = "installation-token"

    class FakeIntegration:
        def __init__(self, app_id, private_key):
            assert app_id == "42"
            assert private_key == "private-key"

        def get_access_token(self, installation_id):
            assert installation_id == 7
            return FakeAccessToken()

    monkeypatch.setattr("repopilot.github.GithubIntegration", FakeIntegration)
    monkeypatch.setenv("GITHUB_APP_ID", "42")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "private-key")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "7")
    client = GitHubClient.from_environment()
    assert client._token == "installation-token"


def test_inline_review_uses_head_commit_and_locations() -> None:
    class FakePullRequest:
        def create_review(self, **kwargs):
            self.review = kwargs
            return kwargs

    class FakeRepo:
        def __init__(self):
            self.pull_request = FakePullRequest()

        def get_pull(self, _number):
            return self.pull_request

    class FakeGithub:
        def __init__(self):
            self.repo = FakeRepo()

        def get_repo(self, _name):
            return self.repo

    client = GitHubClient("token")
    client._github = FakeGithub()
    finding = type("Finding", (), {
        "title": "Bug", "body": "Fix this", "path": "src/app.py", "line": 8
    })()
    client.post_review_with_comments("owner/project", 1, "summary", [finding], "sha123")
    review = client._github.repo.pull_request.review
    assert review["commit"] == "sha123"
    assert review["comments"][0]["path"] == "src/app.py"
    assert review["comments"][0]["line"] == 8
