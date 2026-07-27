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


def test_workflow_publishes_located_findings_as_inline_comments() -> None:
    inline: list[tuple[str, str]] = []

    class LocatedModel(FakeModel):
        def invoke(self, prompt: str):
            return [
                Finding(
                    category="security" if "security vulnerabilities" in prompt else "logic",
                    severity="warning", title="Finding", body="Review me.",
                    path="src/app.py", line=12,
                )
            ]

    def publish_inline(_repo, _number, _body, findings, commit_sha):
        inline.append((findings[0].path, commit_sha))

    workflow = build_review_workflow(
        LocatedModel(), lambda *_args: None, inline_publisher=publish_inline
    )
    config = {"configurable": {"thread_id": "approval-3"}}
    workflow.invoke(
        {
            "repository": "owner/project", "pull_request_number": 7,
            "commit_sha": "abc123", "diff": "diff",
        }, config
    )
    workflow.invoke(__import__("langgraph.types", fromlist=["Command"]).Command(
        resume={"approved": True}
    ), config)
    assert inline == [("src/app.py", "abc123")]
