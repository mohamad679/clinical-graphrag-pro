#!/usr/bin/env bash
set -euo pipefail

echo "Checking dangerous files before GitHub push..."

if find . -path './.git' -prune -o -path './backend/.venv' -prune -o \
  \( -name '.env' -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '.DS_Store' -o -name '.coverage' -o -name 'coverage.xml' \) -print | grep -q .; then
  echo "Dangerous/generated files still exist:"
  find . -path './.git' -prune -o -path './backend/.venv' -prune -o \
    \( -name '.env' -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '.DS_Store' -o -name '.coverage' -o -name 'coverage.xml' \) -print
  exit 1
fi

echo "OK: no obvious dangerous files found."
