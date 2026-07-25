"""Small GitHub adapter used by ReviewForge's workflow boundary."""

from dataclasses import dataclass
from typing import Any

import requests
from github import Github


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

    def get_pull_request_diff(self, repository: str, pull_request_number: int) -> str:
        """Fetch the unified diff for a pull request."""
        repo = self._github.get_repo(repository)
        pull_request = repo.get_pull(pull_request_number)
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
        pull_request = repo.get_pull(pull_request_number)
        return pull_request.create_review(body=body, event="COMMENT")
