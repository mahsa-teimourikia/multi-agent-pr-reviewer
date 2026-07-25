from langgraph.types import Command

from repopilot.models import Finding
from repopilot.workflow import build_review_workflow


class FakeModel:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, prompt: str):
        category = "security" if "security vulnerabilities" in prompt else "logic"
        return [Finding(category=category, severity="warning", title="Finding", body="Review me.")]


def test_workflow_pauses_then_publishes_after_approval() -> None:
    published: list[str] = []
    workflow = build_review_workflow(FakeModel(), lambda *_args: published.append("posted"))
    config = {"configurable": {"thread_id": "approval-1"}}
    first = workflow.invoke(
        {"repository": "owner/project", "pull_request_number": 7, "diff": "diff"}, config
    )
    assert first["__interrupt__"][0].value["type"] == "review_approval"
    result = workflow.invoke(Command(resume={"approved": True}), config)
    assert result["review_posted"] is True
    assert published == ["posted"]


def test_workflow_does_not_publish_when_rejected() -> None:
    published: list[str] = []
    workflow = build_review_workflow(FakeModel(), lambda *_args: published.append("posted"))
    config = {"configurable": {"thread_id": "approval-2"}}
    workflow.invoke(
        {"repository": "owner/project", "pull_request_number": 7, "diff": "diff"}, config
    )
    result = workflow.invoke(Command(resume={"approved": False}), config)
    assert result.get("review_posted", False) is False
    assert published == []
