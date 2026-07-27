.PHONY: install install-dev test lint typecheck audit format check docker-build clean

install:
	uv sync

install-dev:
	uv sync --no-editable --extra dev --reinstall-package reviewforge

test: install-dev
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

audit: install-dev
	uv run pip-audit

format:
	uv run ruff format .

check: install-dev lint typecheck audit test

docker-build:
	docker build -t reviewforge:local .

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build
