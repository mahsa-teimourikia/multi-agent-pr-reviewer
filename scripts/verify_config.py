"""Validate ReviewForge environment configuration without printing secrets."""

from __future__ import annotations

import os
import sys


def main() -> int:
    required = ["OPENAI_API_KEY", "GITHUB_WEBHOOK_SECRET", "APPROVAL_TOKEN"]
    missing = [name for name in required if not os.environ.get(name)]
    app_values = [
        os.environ.get("GITHUB_APP_ID"),
        os.environ.get("GITHUB_APP_PRIVATE_KEY"),
        os.environ.get("GITHUB_APP_INSTALLATION_ID"),
    ]
    if not os.environ.get("GITHUB_TOKEN") and not all(app_values):
        missing.append("GITHUB_TOKEN or complete GitHub App credentials")
    if missing:
        print("Missing configuration:")
        for name in missing:
            print(f"- {name}")
        return 1
    print("ReviewForge configuration is complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
