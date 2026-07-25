.PHONY: install install-dev test lint format check clean

install:
	uv sync

install-dev:
	uv sync --extra dev --reinstall-package repopilot

test: install-dev
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

check: install-dev lint test

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build
