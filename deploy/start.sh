#!/bin/sh
# Container entrypoint: apply database migrations (when a database is configured), start nginx, run the API.
set -e
mkdir -p "${UC042_APP_STATE_DIR:-/data/app_state}" "${UC042_DOCUMENT_STORE:-/data/document_store}"
cd /app/src/uc042
if [ -n "$UC042_DATABASE_URL" ]; then
  i=0
  until python -m uc042app.admin db-upgrade; do
    i=$((i+1)); [ $i -ge 30 ] && { echo "database not reachable"; exit 1; }
    echo "waiting for database..."; sleep 2
  done
fi
nginx
exec uvicorn --factory uc042app.api.main:create_app --host 127.0.0.1 --port 8000 --workers 1
