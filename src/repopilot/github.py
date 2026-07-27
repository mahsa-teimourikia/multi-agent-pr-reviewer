"""Small GitHub adapter used by ReviewForge's workflow boundary."""

import os
from dataclasses import dataclass
from typing import Any

import requests
from github import Github, GithubIntegration


@dataclass(frozen=True)
class PullRequestEvent:
    """The minimum PR event data needed to start a review."""

    repository: str
    pull_request_number: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PullRequestEvent":
        try:
            repository = payload["repository"]["full_name"]
            number = payload["pull_request"]["number"]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "Payload is missing repository.full_name or pull_request.number"
            ) from exc
        if not isinstance(repository, str) or not isinstance(number, int):
            raise ValueError(
                "repository.full_name must be a string and pull_request.number an integer"
            )
        return cls(repository=repository, pull_request_number=number)


class GitHubClient:
    """GitHub API operations kept separate from graph and webhook code."""

    def __init__(self, token: str):
        self._token = token
        self._github = Github(token)

    @classmethod
    def from_app(cls, app_id: str, private_key: str, installation_id: str) -> "GitHubClient":
        """Create a client from a GitHub App installation token."""
        integration = GithubIntegration(app_id, private_key)
        token = integration.get_access_token(int(installation_id)).token
        return cls(token)

    @classmethod
    def from_environment(cls) -> "GitHubClient":
        """Prefer GitHub App credentials, falling back to a static token."""
        app_id = os.environ.get("GITHUB_APP_ID")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")
        if app_id and private_key and installation_id:
            return cls.from_app(app_id, private_key, installation_id)
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            return cls(token)
        raise RuntimeError(
            "Configure GITHUB_TOKEN or GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, "
            "and GITHUB_APP_INSTALLATION_ID"
        )

    def get_pull_request_diff(self, repository: str, pull_request_number: int) -> str:
        """Fetch the unified diff for a pull request."""
        repo = self._github.get_repo(repository)
        pull_request: Any = repo.get_pull(pull_request_number)
        response = requests.get(
            pull_request.diff_url,
            headers={
                "Accept": "application/vnd.github.v3.diff",
                "Authorization": f"Bearer {self._token}",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.text

    def post_review(self, repository: str, pull_request_number: int, body: str) -> Any:
        """Publish a pull request review; callers must enforce HITL first."""
        repo = self._github.get_repo(repository)
        pull_request: Any = repo.get_pull(pull_request_number)
        return pull_request.create_review(body=body, event="COMMENT")

    def post_review_with_comments(
        self,
        repository: str,
        pull_request_number: int,
        body: str,
        findings: list[Any],
        commit_sha: str,
    ) -> Any:
        """Publish a summary plus safe right-side inline comments."""
        repo = self._github.get_repo(repository)
        pull_request: Any = repo.get_pull(pull_request_number)
        comments = [
            {"body": f"**{finding.title}** — {finding.body}", "path": finding.path,
             "line": finding.line, "side": "RIGHT"}
            for finding in findings
            if finding.path and finding.line
        ]
        return pull_request.create_review(
            body=body, event="COMMENT", commit=commit_sha, comments=comments
        )
