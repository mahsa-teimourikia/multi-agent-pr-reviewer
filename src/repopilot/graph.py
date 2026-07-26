"""LangGraph supervisor workflow for multi-agent PR review."""

from collections.abc import Callable
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from .models import Finding, ReviewState

SECURITY_PROMPT = """Review this pull request diff for security vulnerabilities. Look for injection,
secrets, unsafe deserialization, authorization flaws, and dependency risks. Return only actionable
findings with category='security'. If there are none, return an empty list."""
QUALITY_PROMPT = """Review this pull request diff for bugs, logic errors, regressions, and
maintainability problems. Return only actionable findings with category='logic' or category='style'.
If there are none, return an empty list."""


def _review_node(model: Any, prompt: str) -> Callable[[ReviewState], dict[str, list[Finding]]]:
    def node(state: ReviewState) -> dict[str, list[Finding]]:
        structured = model.with_structured_output(list[Finding])
        findings = structured.invoke(f"{prompt}\n\nDIFF:\n{state['diff']}")
        return {"security_findings" if prompt == SECURITY_PROMPT else "quality_findings": findings}

    return node


def supervisor(state: ReviewState) -> dict[str, list[str]]:
    """Select both specialist reviewers for every PR in this initial graph."""
    return {"requested_agents": ["security", "quality"]}


def merge_findings(state: ReviewState) -> dict[str, str]:
    findings = state.get("security_findings", []) + state.get("quality_findings", [])
    if not findings:
        return {"final_review": "No actionable findings were identified by ReviewForge."}
    lines = ["## ReviewForge review\n"]
    for finding in findings:
        location = f" ({finding.path}:{finding.line})" if finding.path and finding.line else ""
        lines.append(
            f"- **{finding.severity.upper()} — {finding.title}**{location}: {finding.body}"
        )
    return {"final_review": "\n".join(lines)}


def build_review_graph(model: Any | None = None) -> Any:
    """Build and compile the review graph, optionally with an injected test model."""
    llm = model or ChatOpenAI(model="gpt-4o-mini", temperature=0)
    builder = StateGraph(ReviewState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("security_agent", _review_node(llm, SECURITY_PROMPT))  # type: ignore[arg-type]
    builder.add_node("quality_agent", _review_node(llm, QUALITY_PROMPT))  # type: ignore[arg-type]
    builder.add_node("merge_findings", merge_findings)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["requested_agents"],
        {"security": "security_agent", "quality": "quality_agent"},
    )
    builder.add_edge("security_agent", "merge_findings")
    builder.add_edge("quality_agent", "merge_findings")
    builder.add_edge("merge_findings", END)
    return builder.compile()
