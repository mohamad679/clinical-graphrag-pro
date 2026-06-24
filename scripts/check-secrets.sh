#!/usr/bin/env bash
set -euo pipefail

staged_files="$(git diff --cached --name-only --diff-filter=ACMR)"

if printf '%s\n' "$staged_files" | grep -Eq '(^|/)\.env($|(\.[^/]+)?$)'; then
  echo "Commit blocked: staged .env files detected." >&2
  echo "Remove .env from the index and use .env.example for safe placeholders." >&2
  exit 1
fi

exit 0
