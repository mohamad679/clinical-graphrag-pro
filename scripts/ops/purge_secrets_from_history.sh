#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/ops/purge_secrets_from_history.sh [--dry-run]

Removes known secret-bearing files from all git history using git filter-repo.
EOF
}

require_filter_repo() {
  if ! git filter-repo --version >/dev/null 2>&1; then
    echo "ERROR: git filter-repo is not installed." >&2
    echo "Install it first, for example:" >&2
    echo "  pip install git-filter-repo" >&2
    exit 1
  fi
}

print_warning_banner() {
  cat <<'EOF'
========================================================================
WARNING: This operation rewrites git history for the entire repository.
It will permanently remove selected files from every commit.

All collaborators must stop work, discard old clones, or re-clone after
the rewritten history is force-pushed.
========================================================================
EOF
}

confirm_rewrite() {
  local confirmation
  printf 'Type PURGE to continue: '
  read -r confirmation
  if [[ "${confirmation}" != "PURGE" ]]; then
    echo "Aborted."
    exit 1
  fi
}

main() {
  local dry_run=false
  if [[ $# -gt 1 ]]; then
    usage >&2
    exit 1
  fi
  if [[ $# -eq 1 ]]; then
    case "$1" in
      --dry-run)
        dry_run=true
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        usage >&2
        exit 1
        ;;
    esac
  fi

  require_filter_repo

  if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "ERROR: This script must be run inside the git repository." >&2
    exit 1
  fi

  local repo_root
  repo_root="$(git rev-parse --show-toplevel)"
  cd "${repo_root}"

  local paths=(
    "backend/phase1_migration_test.db"
    "backend/phase4_migration_test.db"
    "backend/test_auth_suite.db"
    "backend/tmp_phase4_debug.sqlite3"
    "backend/.env"
    ".env"
  )

  local cmd=(git filter-repo --force --invert-paths)
  local path
  for path in "${paths[@]}"; do
    cmd+=(--path "${path}")
  done

  print_warning_banner

  if [[ "${dry_run}" == "true" ]]; then
    echo "DRY RUN: no history has been modified."
    printf 'Would run:'
    printf ' %q' "${cmd[@]}"
    printf '\n'
  else
    confirm_rewrite
    "${cmd[@]}"
  fi

  cat <<'EOF'

Next steps:
  1. Review the rewritten history locally.
  2. Force-push all branches:
       git push --force --all origin
  3. Force-push all tags:
       git push --force --tags origin
  4. Ask collaborators to re-clone or hard-reset to the new history.
EOF
}

main "$@"
