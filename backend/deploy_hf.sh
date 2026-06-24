#!/usr/bin/env sh
set -eu

repo_id="${1:-mohi679/clinical-graphrag-pro}"

cd "$(dirname "$0")/.."
exec backend/.venv/bin/python scripts/deploy_hf_space.py --repo-id "${repo_id}"
