#!/usr/bin/env sh
set -eu

echo "Applying Alembic migrations..."

mkdir -p "${UPLOAD_DIR:-./uploads}" "${ADAPTERS_DIR:-./data/adapters}" "${VECTOR_STORE_DIR:-./data/vector_store}"
mkdir -p "$(dirname "${JWT_SECRET_FILE:-./data/jwt_secret.txt}")"

if [ -z "${JWT_SECRET:-}" ]; then
  secret_file="${JWT_SECRET_FILE:-./data/jwt_secret.txt}"
  if [ ! -s "${secret_file}" ]; then
    umask 077
    python -c 'import secrets; print(secrets.token_urlsafe(48))' > "${secret_file}"
  fi
  export JWT_SECRET="$(cat "${secret_file}")"
fi

alembic upgrade head

workers="${UVICORN_WORKERS:-2}"
case "${DATABASE_URL:-}" in
  sqlite*)
    if [ "${workers}" != "1" ]; then
      echo "SQLite database detected; forcing a single uvicorn worker to avoid write-lock failures."
    fi
    workers=1
    ;;
esac

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${workers}"
