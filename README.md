# ReviewForge

[![CI](https://github.com/mahsa-teimourikia/multi-agent-pr-reviewer/actions/workflows/ci.yml/badge.svg)](https://github.com/mahsa-teimourikia/multi-agent-pr-reviewer/actions/workflows/ci.yml)

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

## Connecting GitHub

For a `pull_request` webhook, pass the JSON payload and a configured `GitHubClient` to `start_review_from_event`. ReviewForge fetches the diff, runs the specialist graph, and returns an approval interrupt. Persist the thread ID and resume it only after your maintainer UI records an approval decision. A GitHub App or fine-grained token with pull request read/write permission can be used by the adapter.

## Setup and local run

There are three supported ways to run ReviewForge:

1. **Local `uv`** — best for development and testing.
2. **Docker Compose** — easiest single-host deployment with persistent storage.
3. **Docker/OCI image** — for an existing VM, container platform, or Kubernetes deployment.

All methods run the same webhook server and require the same environment variables.

### Prerequisites

- Python 3.11–3.13 (Python 3.11 is the default verified runtime)
- [uv](https://docs.astral.sh/uv/)
- A GitHub token or GitHub App installation token with pull request read/write access
- An OpenAI API key

### Install

```bash
git clone https://github.com/mahsa-teimourikia/multi-agent-pr-reviewer.git
cd multi-agent-pr-reviewer
cp .env.example .env
make install-dev
```

Edit `.env` and set every value below. Do not use shell command substitutions inside `.env`;
generate the values first, then paste the results. Never commit `.env`:

```dotenv
OPENAI_API_KEY=your-openai-api-key
GITHUB_TOKEN=your-github-token
# Or use a GitHub App installation instead:
# GITHUB_APP_ID=123456
# GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
# GITHUB_APP_INSTALLATION_ID=12345678
GITHUB_REPOSITORY=owner/repository
GITHUB_WEBHOOK_SECRET=paste-a-random-64-character-value
APPROVAL_TOKEN=paste-a-different-random-64-character-value
CHECKPOINT_DB=reviewforge-checkpoints.sqlite
RATE_LIMIT_PER_MINUTE=60
```

Generate secrets with:

```bash
openssl rand -hex 32
```

Use either `GITHUB_TOKEN` or all three `GITHUB_APP_*` values, not both. GitHub App
configuration is recommended for production; see [docs/account-setup.md](docs/account-setup.md).

### Verify the installation

```bash
make check
uv run reviewforge
uv run python scripts/verify_config.py
```

`make check` runs Ruff, strict mypy, pip-audit, and the test suite. The `reviewforge` command is a smoke-test CLI; the webhook server is started separately.

### Start the server

```bash
uv run reviewforge-server
```

The server listens on `http://localhost:8000`. Confirm it is running:

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

The server persists paused review state, webhook delivery IDs, and queued jobs in the SQLite file
configured by `CHECKPOINT_DB`. Keep this file on persistent storage.

### Configure the GitHub webhook

In the repository’s **Settings → Webhooks → Add webhook**:

1. Set **Payload URL** to `https://your-host.example.com/webhooks/github`.
2. Set **Content type** to `application/json`.
3. Set **Secret** to the exact value of `GITHUB_WEBHOOK_SECRET`.
4. Select **Let me select individual events**, enable **Pull requests**, and save.

ReviewForge processes `opened`, `synchronize`, and `reopened` pull request actions. Other events are acknowledged and ignored.

When a reviewer finding includes a valid file and line location, the approved GitHub review
uses the webhook head commit SHA to add a right-side inline comment. Findings without safe
patch locations remain in the summary review only.

### Review and approve a pending PR

After a webhook arrives, inspect the generated review:

```bash
curl http://localhost:8000/reviews/owner/project/42 \
  -H "Authorization: Bearer $APPROVAL_TOKEN"
```

Approve it to publish the GitHub review, or set `approved` to `false` to reject it:

```bash
curl -X POST http://localhost:8000/reviews/owner/project/42/approval \
  -H "Authorization: Bearer $APPROVAL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"approved":true}'
```

For a browser-based maintainer flow, open
`/reviews/owner/project/42/approval-ui`. Enter `APPROVAL_TOKEN` to load the review,
then choose **Approve and publish** or **Reject**. The page uses the same approval
boundary as the API and does not expose the token in the URL.

Webhook requests are acknowledged after the payload is written to a durable SQLite review queue.
A worker drains pending jobs, retries transient failures up to two times, and resumes queued work
after a process restart. SQLite mode is for one server instance; multiple instances require a
shared database/checkpointer and a queue service with distributed job leases.

The approval endpoint requires `APPROVAL_TOKEN`. For production, a GitHub App is recommended: ReviewForge exchanges the App private key and installation ID for a short-lived installation token at startup. The server stores LangGraph checkpoints, webhook delivery IDs, and queued jobs in SQLite at `CHECKPOINT_DB` (default: `reviewforge-checkpoints.sqlite`) with WAL mode and a persistent volume. Back up this file and mount it at the same path after restarts. SQLite is intended for one server instance; multiple instances require a shared database/checkpointer and a queue service with distributed job leases.

Requests are rate limited to 60 per source IP per minute by default; override the limit when constructing the app for tests or controlled deployments. Authenticated Prometheus-style counters are available at `/metrics` using `Authorization: Bearer $APPROVAL_TOKEN`.

Use `/healthz` for a liveness probe and `/readyz` for a readiness probe. Readiness verifies both the SQLite connection and review queue worker.

## Container deployment

For a reproducible local or single-host deployment, use the included Compose file:

```bash
cp .env.example .env
# edit .env, then validate without printing secrets
make config-check
docker compose up --build -d
```

See [docs/account-setup.md](docs/account-setup.md) for GitHub App, OpenAI, webhook, and deployment setup.

```bash
docker build -t reviewforge:local .
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY \
  -e GITHUB_TOKEN \
  -e GITHUB_WEBHOOK_SECRET \
  -e APPROVAL_TOKEN \
  -v "$PWD/data:/data" \
  reviewforge:local
```

The image runs as a non-root user, persists checkpoints under `/data`, and exposes a Docker readiness health check through `/readyz`.

### Docker Compose

Compose reads `.env`, persists state in the named `reviewforge-data` volume, and restarts the
service automatically:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f reviewforge
curl http://localhost:8000/readyz
docker compose down             # keeps the named volume
docker compose down -v          # deletes review state; use with care
```

### Plain Docker

Use a host directory when you do not use Compose. The directory must be writable by the container:

```bash
mkdir -p data
docker build -t reviewforge:local .
docker run --rm -p 8000:8000 --env-file .env \
  -v "$PWD/data:/data" reviewforge:local
```

### Existing container platform

Build and publish the image, configure the variables from `.env.example` in the platform’s secret
store, expose port `8000`, and set the health check path to `/readyz`. Attach persistent storage at
`/data`. Configure the GitHub webhook only after the public HTTPS URL is available.

Pushing a tag such as `v0.1.0` publishes versioned and `latest` images to GitHub Container Registry through the release workflow.

## Development

```bash
make install-dev  # create/sync the uv environment
make check        # lint and test
make format       # format source and tests
uv run reviewforge # print the CLI status message
```

## License

MIT. See [LICENSE](LICENSE).
