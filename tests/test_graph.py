from repopilot.graph import build_review_graph
from repopilot.models import Finding


class FakeStructuredModel:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, prompt: str):
        if "security vulnerabilities" in prompt:
            return [
                Finding(
                    category="security",
                    severity="warning",
                    title="Demo security finding",
                    body="Review this path.",
                )
            ]
        return [
            Finding(
                category="logic",
                severity="info",
                title="Demo logic finding",
                body="Consider a regression test.",
            )
        ]


def test_review_graph_runs_both_specialists() -> None:
    result = build_review_graph(FakeStructuredModel()).invoke(
        {"diff": "diff --git a/app.py b/app.py"}
    )
    assert len(result["security_findings"]) == 1
    assert len(result["quality_findings"]) == 1
    assert "Demo security finding" in result["final_review"]
