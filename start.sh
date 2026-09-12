#!/usr/bin/env bash
# Um unico servico Railway roda o painel e o worker: ambos leem e escrevem o mesmo
# SQLite em /data, entao o painel mostra exatamente o que a conversa no Telegram gravou.
set -euo pipefail

mkdir -p "$(dirname "${DATABASE_PATH:-/data/machine2pipe.db}")" "${PHOTO_STORAGE_PATH:-/data/photos}"

python -m machine2pipe.worker &
WORKER_PID=$!
trap 'kill "$WORKER_PID" 2>/dev/null || true' EXIT

exec uvicorn machine2pipe.api:app --host 0.0.0.0 --port "${PORT:-8080}"
