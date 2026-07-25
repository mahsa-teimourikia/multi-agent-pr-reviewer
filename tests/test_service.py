from repopilot.models import Finding
from repopilot.service import start_review_from_event


class FakeModel:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _prompt: str):
        return [Finding(category="logic", severity="info", title="Test", body="Test finding")]


class FakeGitHub:
    def get_pull_request_diff(self, _repository: str, _number: int) -> str:
        return "diff"

    def post_review(self, _repository: str, _number: int, _body: str) -> None:
        raise AssertionError("publisher must not run before approval")


def test_service_starts_review_from_webhook_payload() -> None:
    result = start_review_from_event(
        {"repository": {"full_name": "owner/project"}, "pull_request": {"number": 5}},
        FakeGitHub(),
        model=FakeModel(),
    )
    assert result["__interrupt__"][0].value["type"] == "review_approval"
