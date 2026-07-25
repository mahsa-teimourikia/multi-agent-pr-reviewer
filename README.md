# ReviewForge

ReviewForge is an open-source, LangGraph-powered multi-agent pull request reviewer. It is designed to inspect incoming GitHub PRs, combine focused security and code-quality findings, and request maintainer approval before publishing a review.

## Project roadmap

This repository is built in independently reviewable steps:

1. **Foundation** — `uv` packaging, quality tooling, configuration contract, and project documentation.
2. **Review graph** — typed state, supervisor routing, security agent, and style/logic agent.
3. **GitHub integration** — PR webhook/event input, diff retrieval, and review publishing.
4. **Human-in-the-loop** — durable pause/resume approval before any GitHub write.
5. **Production hardening** — tests, CI, deployment guidance, and contributor documentation.

## Architecture

```mermaid
flowchart TD
    T[PR Trigger] --> S[Supervisor / Router]
    S --> Q[Code Quality Agent]
    S --> SEC[Security Agent]
    Q --> M[Merge Findings]
    SEC --> M
    M --> H{Maintainer Approval}
    H -- Changes requested --> S
    H -- Approved --> P[Post Review to PR]
```

The graph will carry a typed review state containing the PR metadata, diff, findings, approval decision, and final review body. The approval boundary is intentionally placed before the GitHub write node.

## Human approval

`build_review_workflow()` uses a durable LangGraph interrupt. Store the returned `thread_id` with the pending review, show the interrupt payload to a repository maintainer, and resume the same thread with an explicit decision:

```python
from langgraph.types import Command

pending = workflow.invoke(initial_state, {"configurable": {"thread_id": "pr-42"}})
workflow.invoke(Command(resume={"approved": True}), {"configurable": {"thread_id": "pr-42"}})
```

The GitHub publisher is never called until the approval value is `True`.

## Quick start

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
make install-dev
cp .env.example .env
make check
uv run repopilot
```

The environment variables in `.env.example` define the integration contract. Tokens must be supplied at runtime and should never be committed.

## Development

```bash
make install-dev  # create/sync the uv environment
make check        # lint and test
make format       # format source and tests
```

## License

MIT. See [LICENSE](LICENSE).
