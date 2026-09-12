"""Processo sempre ligado: replay da telemetria, long polling do Telegram e chamadas ao agente.

Nesta etapa ele apenas mantem o servico vivo e registra um heartbeat, para que o deploy
tenha um alvo verde antes de o motor deterministico entrar.
"""
from __future__ import annotations

import logging
import signal
import time

from machine2pipe.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
log = logging.getLogger(__name__)

_running = True


def _stop(signum, _frame):
    global _running
    log.info("sinal %s recebido, encerrando", signum)
    _running = False


def main() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)

    log.info(
        "worker iniciado | maquina=%s | dia de replay=%s | velocidade=%sx | corredor=%sm",
        config.machine_id,
        config.replay_date,
        config.replay_speed,
        config.corridor_m,
    )
    if not config.telegram_bot_token:
        log.warning("TELEGRAM_BOT_TOKEN ausente: long polling desativado nesta execucao")

    while _running:
        time.sleep(15)
    log.info("worker encerrado")


if __name__ == "__main__":
    main()
