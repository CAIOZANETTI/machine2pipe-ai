#!/usr/bin/env bash
# Um unico servico Railway roda o painel e o worker: o volume /data monta em um servico so.
set -euo pipefail

mkdir -p "$(dirname "${DATABASE_PATH:-/data/machine2pipe.db}")" "${PHOTO_STORAGE_PATH:-/data/photos}"

python -m machine2pipe.worker &
WORKER_PID=$!
trap 'kill "$WORKER_PID" 2>/dev/null || true' EXIT

exec streamlit run app/streamlit_app.py \
    --server.port="${PORT:-8080}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
