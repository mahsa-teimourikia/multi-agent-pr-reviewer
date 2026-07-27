"""ReviewForge workflow with a durable maintainer approval boundary."""

from collections.abc import Callable
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .graph import (
    QUALITY_PROMPT as quality_prompt,
)
from .graph import (
    SECURITY_PROMPT as security_prompt,
)
from .graph import (
    _review_node,
    merge_findings,
    supervisor,
)
from .models import ReviewState


def approval_gate(state: ReviewState) -> dict[str, bool]:
    """Pause execution until a maintainer explicitly approves the final review."""
    decision = interrupt(
        {
            "type": "review_approval",
            "message": "Approve this ReviewForge comment for publishing?",
            "review": state["final_review"],
        }
    )
    return {"approval": bool(decision.get("approved", False))}


def publish_review(
    state: ReviewState,
    publisher: Callable[[str, int, str], Any],
    inline_publisher: Callable[[str, int, str, list[Any], str], Any] | None = None,
) -> dict[str, bool]:
    """Publish only after approval; the publisher is injected for testing."""
    if not state.get("approval", False):
        return {"review_posted": False}
    if inline_publisher and state.get("commit_sha"):
        findings = state.get("security_findings", []) + state.get("quality_findings", [])
        located = [finding for finding in findings if finding.path and finding.line]
        if located:
            inline_publisher(
                state["repository"], state["pull_request_number"], state["final_review"],
                located, state["commit_sha"],
            )
    else:
        publisher(state["repository"], state["pull_request_number"], state["final_review"])
    return {"review_posted": True}


def build_review_workflow(
    model: Any | None = None,
    publisher: Callable[[str, int, str], Any] | None = None,
    inline_publisher: Callable[[str, int, str, list[Any], str], Any] | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Build a review workflow that can pause and resume by thread ID."""
    llm = model or ChatOpenAI(model="gpt-4o-mini", temperature=0)
    post = publisher or (lambda _repo, _number, _body: None)
    builder = StateGraph(ReviewState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("security_agent", _review_node(llm, security_prompt))  # type: ignore[arg-type]
    builder.add_node("quality_agent", _review_node(llm, quality_prompt))  # type: ignore[arg-type]
    builder.add_node("merge_findings", merge_findings)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node(
        "publish_review", lambda state: publish_review(state, post, inline_publisher)
    )
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["requested_agents"],
        {"security": "security_agent", "quality": "quality_agent"},
    )
    builder.add_edge("security_agent", "merge_findings")
    builder.add_edge("quality_agent", "merge_findings")
    builder.add_edge("merge_findings", "approval_gate")
    builder.add_conditional_edges(
        "approval_gate",
        lambda state: "publish_review" if state.get("approval") else END,
        {"publish_review": "publish_review", END: END},
    )
    builder.add_edge("publish_review", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())
