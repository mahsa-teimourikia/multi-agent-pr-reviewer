"""Typed state and finding models shared by the review graph."""

from typing import Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class Finding(BaseModel):
    """A reviewer finding that can be rendered into a GitHub review later."""

    category: Literal["security", "style", "logic"]
    severity: Literal["info", "warning", "error"]
    title: str
    body: str
    path: str | None = None
    line: int | None = Field(default=None, ge=1)


class ReviewState(TypedDict, total=False):
    """State carried between LangGraph nodes."""

    repository: str
    pull_request_number: int
    diff: str
    requested_agents: list[str]
    security_findings: list[Finding]
    quality_findings: list[Finding]
    final_review: str
    approval: bool
    review_posted: bool
