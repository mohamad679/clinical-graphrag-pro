#!/usr/bin/env python3
"""Deploy the combined backend and static frontend to a Hugging Face Docker Space.

The script reads authentication from HF_TOKEN, HF_TOKEN_FILE, or a cached
Hugging Face login. It never accepts tokens as CLI arguments so secrets are not
stored in shell history.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, get_token


REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
FRONTEND_PUBLIC = REPO_ROOT / "frontend" / "public"

IGNORE_DIRS = {
    "__pycache__",
    ".coverage",
    ".hypothesis",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
    "bm25_store",
    "local_ui_vector_store_hash",
    "node_modules",
    "tests",
    "uploads",
    "venv",
    "vector_store",
}

IGNORE_SUFFIXES = {
    ".coverage",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".sqlite-shm",
    ".sqlite-wal",
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite3-shm",
    ".sqlite3-wal",
}


def ignore_backend_files(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(name)
        if name in IGNORE_DIRS:
            ignored.add(name)
        elif name.startswith(".env"):
            ignored.add(name)
        elif path.suffix in IGNORE_SUFFIXES:
            ignored.add(name)
        elif name in {"coverage.xml", "requirements-dev.txt", "results"}:
            ignored.add(name)
    return ignored


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore_backend_files)


def write_space_readme(stage_dir: Path, title: str) -> None:
    (stage_dir / "README.md").write_text(
        f"""---
title: {title}
emoji: 🏥
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# {title}

Clinical GraphRAG Pro backend and static frontend UI packaged as a single
Docker Space. This is a portfolio/demo deployment, not a clinical device.

## Runtime Secrets

Add provider keys in the Hugging Face Space settings under **Settings -> Secrets**.
Do not commit API keys to this repository.

- `GEMINI_API_KEY` or `GOOGLE_API_KEY`: enables Gemini text and image analysis.
- `GROQ_API_KEY`: optional text-generation provider key.

The container reads those values from environment variables at runtime.
""",
        encoding="utf-8",
    )


def stage_space(stage_dir: Path, title: str) -> None:
    copy_tree(BACKEND_ROOT, stage_dir)
    shutil.copy2(BACKEND_ROOT / "Dockerfile.hf", stage_dir / "Dockerfile")
    copy_tree(FRONTEND_PUBLIC, stage_dir / "frontend_public")
    write_space_readme(stage_dir, title)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy Clinical GraphRAG Pro to a Hugging Face Docker Space.")
    parser.add_argument(
        "--repo-id",
        default="mohi679/clinical-graphrag-pro",
        help="Space repo id as namespace/name. Default: mohi679/clinical-graphrag-pro",
    )
    parser.add_argument("--title", default="Clinical GraphRAG Pro", help="Space title.")
    parser.add_argument("--private", action="store_true", help="Create/update the Space as private.")
    parser.add_argument(
        "--skip-create",
        action="store_true",
        help="Upload to an existing Space without calling the repo-create API.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Prepare the staged Space directory without uploading.")
    return parser.parse_args()


def resolve_hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN")
    if token:
        return token.strip()

    token_file = os.environ.get("HF_TOKEN_FILE")
    if token_file:
        path = Path(token_file).expanduser()
        if not path.is_file():
            raise SystemExit(f"HF_TOKEN_FILE does not exist: {path}")
        return path.read_text(encoding="utf-8").strip()

    cached_token = get_token()
    return cached_token.strip() if cached_token else None


def main() -> int:
    args = parse_args()
    token = resolve_hf_token()
    if not token and not args.dry_run:
        raise SystemExit(
            "No Hugging Face token found. Export a rotated write token as HF_TOKEN, "
            "set HF_TOKEN_FILE to a local file containing the token, or log in with "
            "huggingface-cli first."
        )

    with tempfile.TemporaryDirectory(prefix="clinical-graphrag-hf-space-") as tmp:
        stage_dir = Path(tmp) / "space"
        stage_space(stage_dir, args.title)

        if args.dry_run:
            print(f"Prepared Hugging Face Space staging directory: {stage_dir}")
            print("Dry run only; no upload performed.")
            return 0

        api = HfApi(token=token)
        if not args.skip_create:
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
            commit_message="Automated project deployment from workspace",
            ignore_patterns=[
                ".env",
                ".env.*",
                ".venv/**",
                "venv/**",
                "**/__pycache__/**",
                "**/.pytest_cache/**",
                "**/.ruff_cache/**",
                "**/.mypy_cache/**",
                "**/*.pyc",
                "**/*.sqlite*",
                "**/*.db",
                "coverage.xml",
                "requirements-dev.txt",
                "tests/**",
                "uploads/**",
                "data/vector_store/**",
                "data/bm25_store/**",
            ],
        )
        print(f"Deployment uploaded to https://huggingface.co/spaces/{args.repo_id}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
