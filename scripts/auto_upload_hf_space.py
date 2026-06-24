#!/usr/bin/env python3
"""Upload this workspace to a Hugging Face Space using HfApi."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, get_token
from huggingface_hub.errors import HfHubHTTPError


DEFAULT_REPO_ID = "mohi679/clinical-graphrag-pro"
COMMIT_MESSAGE = "Automated project deployment from workspace"

EXCLUDED_DIR_NAMES = {
    ".agents",
    ".codex",
    ".git",
    ".gemini",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "htmlcov",
    "node_modules",
    "venv",
}

EXCLUDED_FILE_NAMES = {
    ".coverage",
    ".DS_Store",
    ".env",
    "coverage.xml",
}

EXCLUDED_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
}

IGNORE_PATTERNS = [
    ".agents/**",
    ".codex/**",
    ".git/**",
    ".gemini/**",
    ".hypothesis/**",
    ".mypy_cache/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".venv/**",
    "__pycache__/**",
    "htmlcov/**",
    "node_modules/**",
    "venv/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/.mypy_cache/**",
    "**/.DS_Store",
    "**/.env",
    "**/.env.*",
    "**/*.db",
    "**/*.db-shm",
    "**/*.db-wal",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.sqlite",
    "**/*.sqlite-shm",
    "**/*.sqlite-wal",
    "**/*.sqlite3",
    "**/*.sqlite3-shm",
    "**/*.sqlite3-wal",
    "coverage.xml",
    "backend/coverage.xml",
    "backend/uploads/**",
    "backend/data/vector_store/**",
    "backend/data/bm25_store/**",
    "backend/data/local_ui_vector_store_hash/**",
    "data/vector_store/**",
    "reports/release_artifacts/**",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload the current project to a Hugging Face Space.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="Target Space repo id, for example user/space-name.")
    parser.add_argument(
        "--workspace",
        default=str(Path(__file__).resolve().parents[1]),
        help="Project directory to upload.",
    )
    parser.add_argument("--private", action="store_true", help="Create the Space as private if it does not exist.")
    return parser.parse_args()


def resolve_token() -> str | None:
    for env_name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        token = os.environ.get(env_name)
        if token and token.strip():
            return token.strip()

    token_file = os.environ.get("HF_TOKEN_FILE")
    if token_file:
        path = Path(token_file).expanduser()
        if not path.is_file():
            raise RuntimeError(f"HF_TOKEN_FILE does not exist: {path}")
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token

    cached_token = get_token()
    return cached_token.strip() if cached_token else None


def should_include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    parts = rel.parts
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return False
    if path.is_dir():
        return path.name not in EXCLUDED_DIR_NAMES
    if path.name in EXCLUDED_FILE_NAMES:
        return False
    if path.name.startswith(".env"):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return True


def summarize_upload(root: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file() or not should_include(path, root):
            continue
        file_count += 1
        total_bytes += path.stat().st_size
    return file_count, total_bytes


def stage_upload_tree(source: Path, target: Path) -> None:
    """Copy only deployable files into a clean staging directory."""
    for path in source.rglob("*"):
        if not path.is_file() or not should_include(path, source):
            continue
        rel = path.relative_to(source)
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(f"ERROR: Workspace directory does not exist: {workspace}", file=sys.stderr)
        return 2

    try:
        token = resolve_token()
    except Exception as exc:
        print(f"ERROR: Could not resolve Hugging Face token: {exc}", file=sys.stderr)
        return 2

    if not token:
        print(
            "ERROR: No Hugging Face token found. Set HF_TOKEN, HUGGING_FACE_HUB_TOKEN, "
            "HF_TOKEN_FILE, or log in with the Hugging Face CLI.",
            file=sys.stderr,
        )
        return 2

    file_count, total_bytes = summarize_upload(workspace)
    size_mb = total_bytes / (1024 * 1024)
    print(f"Preparing upload: {file_count} files, {size_mb:.2f} MiB from {workspace}")

    api = HfApi(token=token)
    try:
        with tempfile.TemporaryDirectory(prefix="clinical-graphrag-hf-upload-") as tmp:
            stage_dir = Path(tmp) / "workspace"
            stage_dir.mkdir(parents=True, exist_ok=True)
            stage_upload_tree(workspace, stage_dir)

            staged_count, staged_bytes = summarize_upload(stage_dir)
            staged_mb = staged_bytes / (1024 * 1024)
            print(f"Staged upload: {staged_count} files, {staged_mb:.2f} MiB")

            api.create_repo(
                repo_id=args.repo_id,
                repo_type="space",
                space_sdk="docker",
                private=args.private,
                exist_ok=True,
            )
            api.upload_folder(
                repo_id=args.repo_id,
                repo_type="space",
                folder_path=str(stage_dir),
                path_in_repo=".",
                commit_message=COMMIT_MESSAGE,
                ignore_patterns=IGNORE_PATTERNS,
            )
        info = api.repo_info(repo_id=args.repo_id, repo_type="space")
    except HfHubHTTPError as exc:
        status = getattr(exc.response, "status_code", "unknown")
        print(f"ERROR: Hugging Face API request failed with status {status}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: Upload failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    url = f"https://huggingface.co/spaces/{args.repo_id}"
    print(f"Upload verified for {info.id}.")
    print(f"Success: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
