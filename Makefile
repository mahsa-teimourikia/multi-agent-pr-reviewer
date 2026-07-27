.PHONY: install install-dev test lint typecheck audit format check config-check docker-build clean

install:
	uv sync --no-editable

install-dev:
	uv sync --no-editable --extra dev --reinstall-package reviewforge

test: install-dev
	uv run --no-sync pytest

lint:
	uv run --no-sync ruff check .

typecheck:
	uv run --no-sync mypy src

audit: install-dev
	uv run --no-sync pip-audit

format:
	uv run ruff format .

check: install-dev lint typecheck audit test

config-check:
	uv run python scripts/verify_config.py

docker-build:
	docker build -t reviewforge:local .

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build
