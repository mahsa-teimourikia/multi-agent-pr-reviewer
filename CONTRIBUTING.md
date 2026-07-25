# Contributing to ReviewForge

Thanks for helping make pull request review safer and more useful.

## Local setup

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then run:

```bash
make install-dev
make check
```

Keep credentials in `.env`; never commit tokens or real repository payloads. New graph behavior should include tests using an injected model or publisher so the suite remains offline and deterministic.

## Pull requests

Use a focused branch and describe the behavior change, tests, and any security implications. ReviewForge must preserve the approval boundary: no new GitHub write should happen before an explicit maintainer approval.

