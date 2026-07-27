# Account and deployment setup

This guide configures ReviewForge without placing secrets in Git.

## 1. Create the OpenAI credential

Create an API key in the OpenAI Platform and set it only in your deployment secret store as
`OPENAI_API_KEY`. Do not paste it into README files, issues, or `.env` committed to Git.

## 2. Create a GitHub App

In GitHub, open **Settings → Developer settings → GitHub Apps → New GitHub App**.

Use these settings:

- **Webhook URL**: your deployed URL plus `/webhooks/github`.
- **Webhook secret**: generate a random value and save the same value as `GITHUB_WEBHOOK_SECRET`.
- **Repository permissions**: Pull requests **Read and write**; Contents **Read-only**.
- **Subscribe to events**: Pull request.

Install the App on the repository `mahsa-teimourikia/multi-agent-pr-reviewer` (or the repository
you want to review). Record the App ID and installation ID, download the private key, and configure:

```dotenv
GITHUB_APP_ID=...
GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----...
GITHUB_APP_INSTALLATION_ID=...
```

Leave `GITHUB_TOKEN` empty when using the App. ReviewForge exchanges these values for an
installation token at startup.

## 3. Configure ReviewForge

```bash
cp .env.example .env
# edit .env with your secret values
uv run python scripts/verify_config.py
```

Generate the approval token locally with:

```bash
openssl rand -hex 32
```

## 4. Run locally

```bash
make install-dev
uv run reviewforge-server
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

For webhook delivery to a local server, expose port 8000 through a HTTPS tunnel and use the
tunnel URL plus `/webhooks/github` as the GitHub App webhook URL.

## 5. Run with Docker Compose

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f reviewforge
```

The named `reviewforge-data` volume persists checkpoints, queued jobs, and webhook delivery IDs.
Use one application instance with SQLite. For horizontal scaling, replace SQLite and the queue
with shared production services before running multiple replicas.
