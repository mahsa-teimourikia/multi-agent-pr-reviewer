.PHONY: install install-dev test lint typecheck format check docker-build clean

install:
	uv sync

install-dev:
	uv sync --extra dev --reinstall-package repopilot

test: install-dev
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

format:
	uv run ruff format .

check: install-dev lint typecheck test

docker-build:
	docker build -t reviewforge:local .

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build
