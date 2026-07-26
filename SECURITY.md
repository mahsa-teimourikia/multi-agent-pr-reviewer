# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Report it privately through the repository owner's GitHub security contact, including:

- a description and impact;
- affected versions or commit; and
- a minimal reproduction, if safe to share.

Do not include API keys, GitHub tokens, webhook secrets, or private pull request contents in reports.

ReviewForge maintainers will acknowledge reports as soon as practical and coordinate a fix and disclosure timeline with the reporter.

## Deployment responsibilities

Operators must configure unique secrets for `GITHUB_WEBHOOK_SECRET` and `APPROVAL_TOKEN`, restrict approval endpoint access, and use persistent storage with appropriate filesystem permissions. ReviewForge should not be exposed publicly without TLS and an authenticated maintainer interface.

