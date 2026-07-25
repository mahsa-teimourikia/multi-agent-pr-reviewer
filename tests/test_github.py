import pytest

from repopilot.github import PullRequestEvent


def test_pull_request_event_from_payload() -> None:
    event = PullRequestEvent.from_payload(
        {"repository": {"full_name": "owner/project"}, "pull_request": {"number": 42}}
    )
    assert event.repository == "owner/project"
    assert event.pull_request_number == 42


def test_pull_request_event_rejects_incomplete_payload() -> None:
    with pytest.raises(ValueError, match="missing"):
        PullRequestEvent.from_payload({})
