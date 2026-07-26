"""Application service that connects GitHub events to the review workflow."""

from typing import Any

from .github import GitHubClient, PullRequestEvent
from .workflow import build_review_workflow


def start_review_from_event(
    payload: dict[str, Any],
    github: GitHubClient,
    *,
    model: Any | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Start a review from a GitHub pull_request webhook payload.

    The returned graph result may contain an interrupt. Persist the thread ID and
    resume it with ``Command(resume={"approved": True})`` after maintainer approval.
    """
    event = PullRequestEvent.from_payload(payload)
    diff = github.get_pull_request_diff(event.repository, event.pull_request_number)
    workflow = build_review_workflow(
        model=model,
        publisher=github.post_review,
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": f"{event.repository}#{event.pull_request_number}"}}
    return workflow.invoke(
        {
            "repository": event.repository,
            "pull_request_number": event.pull_request_number,
            "diff": diff,
        },
        config,
    )
