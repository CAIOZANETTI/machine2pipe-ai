#!/usr/bin/env bash
# Um unico servico Railway roda o painel e o worker: ambos leem e escrevem o mesmo
# SQLite em /data, entao o painel mostra exatamente o que a conversa no Telegram gravou.
set -uo pipefail

DB_DIR="$(dirname "${DATABASE_PATH:-/data/machine2pipe.db}")"
mkdir -p "$DB_DIR" "${PHOTO_STORAGE_PATH:-/data/photos}" || {
    echo "ERRO: /data nao e gravavel. Falta montar o volume no servico." >&2
    exit 1
}

# Carga das fotos do album: idempotente e o volume persiste, entao so baixa na primeira vez.
python scripts/seed_photos.py || echo "AVISO: carga de fotos falhou; o replay segue sem elas" >&2

# O worker morrendo em silencio deixaria o deploy verde com o Telegram mudo. Supervisiona.
supervise_worker() {
    while true; do
        python -m machine2pipe.worker
        echo "AVISO: worker encerrou com codigo $?; reiniciando em 5s" >&2
        sleep 5
    done
}
supervise_worker &
WORKER_PID=$!
trap 'kill -- -"$WORKER_PID" 2>/dev/null || kill "$WORKER_PID" 2>/dev/null || true' EXIT

exec uvicorn machine2pipe.api:app --host 0.0.0.0 --port "${PORT:-8080}"
