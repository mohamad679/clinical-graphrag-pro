#!/usr/bin/env python3
"""Configure Hugging Face Space vision-provider secrets from local env files."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError


DEFAULT_REPO_ID = "mohi679/clinical-graphrag-pro"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set vision API secrets on a Hugging Face Space.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--env-file", default="backend/.env")
    return parser.parse_args()


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_hf_token() -> str:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token and token.strip():
        return token.strip()
    return getpass.getpass("HF token: ").strip()


def main() -> int:
    args = parse_args()
    env_values = parse_env_file(Path(args.env_file))
    google_key = env_values.get("GOOGLE_API_KEY") or env_values.get("GEMINI_API_KEY") or ""
    if not google_key or google_key.startswith("CHANGE_ME"):
        print(f"ERROR: No usable GOOGLE_API_KEY/GEMINI_API_KEY found in {args.env_file}.", file=sys.stderr)
        return 2

    hf_token = resolve_hf_token()
    if not hf_token:
        print("ERROR: No Hugging Face token provided.", file=sys.stderr)
        return 2

    api = HfApi(token=hf_token)
    try:
        api.add_space_secret(args.repo_id, "GOOGLE_API_KEY", google_key)
        api.add_space_secret(args.repo_id, "GEMINI_API_KEY", google_key)
        api.restart_space(args.repo_id)
        runtime = api.get_space_runtime(args.repo_id)
    except HfHubHTTPError as exc:
        status = getattr(exc.response, "status_code", "unknown")
        print(f"ERROR: Hugging Face API request failed with status {status}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Failed to configure Space secrets: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Vision secrets configured for {args.repo_id}.")
    print(f"Space restart requested. Current runtime stage: {runtime.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
