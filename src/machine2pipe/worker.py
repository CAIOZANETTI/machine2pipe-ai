"""Processo sempre ligado: replay da telemetria, long polling do Telegram e chamadas ao agente.

Nesta etapa ele apenas mantem o servico vivo e registra um heartbeat, para que o deploy
tenha um alvo verde antes de o motor deterministico entrar.
"""
from __future__ import annotations

import logging
import signal
import threading

from machine2pipe.config import config
from machine2pipe.photos import PhotoStore
from machine2pipe.telegram_bot import TelegramBot, parse_chat_allowlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
log = logging.getLogger(__name__)

_stop_event = threading.Event()


def _stop(signum, _frame):
    log.info("sinal %s recebido, encerrando", signum)
    _stop_event.set()


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
    if config.telegram_bot_token:
        bot = TelegramBot(
            config.telegram_bot_token,
            photo_store=PhotoStore(config.photo_storage_path),
            allowed_chat_ids=parse_chat_allowlist(config.telegram_chat_id),
        )
        bot.run(_stop_event)
    else:
        log.warning("TELEGRAM_BOT_TOKEN ausente: long polling desativado nesta execucao")
        while not _stop_event.wait(15):
            log.debug("heartbeat")
    log.info("worker encerrado")


if __name__ == "__main__":
    main()
