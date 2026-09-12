"""Small Telegram Bot API client with long polling and a strict chat allowlist."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import requests

from machine2pipe.photos import PhotoStore, StoredPhoto

log = logging.getLogger(__name__)
PhotoHandler = Callable[[dict[str, Any], StoredPhoto], str | None]
TextHandler = Callable[[dict[str, Any], str], str | None]


def parse_chat_allowlist(value: str) -> set[int]:
    """Le TELEGRAM_CHAT_ID. Um valor invalido vira aviso, nunca queda do worker.

    O erro de operacao que isto convida e especifico e ja foi cometido: gravar o nome do
    bot onde vai o numero do chat. Com o worker supervisionado, deixar o `int()` estourar
    transformava um engano de digitacao em crash-loop de cinco em cinco segundos, e o
    unico sintoma ficava no log. Melhor uma linha clara e a allowlist vazia.
    """
    permitidos: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            permitidos.add(int(item))
        except ValueError:
            log.error(
                "TELEGRAM_CHAT_ID invalido: %r. Esperado o numero do chat (use /whoami), "
                "nao o nome do bot.",
                item,
            )
    return permitidos


def select_largest_photo(message: dict[str, Any]) -> dict[str, Any] | None:
    photos = message.get("photo") or []
    if not photos:
        return None
    return max(photos, key=lambda item: item.get("file_size", 0))


class TelegramBot:
    def __init__(
        self,
        token: str,
        *,
        photo_store: PhotoStore,
        allowed_chat_ids: set[int] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.file_url = f"https://api.telegram.org/file/bot{token}"
        self.photo_store = photo_store
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.session = session or requests.Session()
        self.offset: int | None = None

    def _call(self, method: str, **data: Any) -> Any:
        response = self.session.post(f"{self.api_url}/{method}", data=data, timeout=40)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error in {method}: {payload.get('description')}")
        return payload.get("result")

    def send_message(self, chat_id: int, text: str) -> None:
        self._call("sendMessage", chat_id=chat_id, text=text)

    def _download(self, file_id: str) -> bytes:
        result = self._call("getFile", file_id=file_id)
        response = self.session.get(f"{self.file_url}/{result['file_path']}", timeout=40)
        response.raise_for_status()
        return response.content

    def _authorized(self, chat_id: int) -> bool:
        """Allowlist vazia nao autoriza ninguem.

        Antes, sem TELEGRAM_CHAT_ID a lista ficava vazia e o `not` a transformava em
        "todo mundo pode": qualquer pessoa que achasse o bot gravava foto e quantidade no
        banco do projeto. Fechar e o padrao certo; para nao trocar isso por um bot mudo
        sem explicacao, `dispatch` responde dizendo o que configurar.
        """
        return chat_id in self.allowed_chat_ids

    def _store_photo(self, message: dict[str, Any]) -> StoredPhoto | None:
        photo = select_largest_photo(message)
        if photo:
            file_id = photo["file_id"]
            return self.photo_store.save(
                self._download(file_id),
                telegram_file_id=file_id,
                source="telegram_photo",
            )

        document = message.get("document") or {}
        mime_type = str(document.get("mime_type", ""))
        if mime_type.startswith("image/") and document.get("file_id"):
            file_id = document["file_id"]
            return self.photo_store.save(
                self._download(file_id),
                telegram_file_id=file_id,
                source="telegram_document",
                filename=document.get("file_name"),
            )
        return None

    @staticmethod
    def photo_ack(photo: StoredPhoto) -> str:
        if photo.metadata.has_gps:
            return (
                "Foto recebida com GPS: "
                f"{photo.metadata.latitude:.6f}, {photo.metadata.longitude:.6f}. "
                "Aguardando correlação com o projeto e a telemetria."
            )
        return (
            "Foto recebida, mas sem GPS confiável. Envie a imagem como arquivo/documento "
            "para preservar o EXIF ou compartilhe sua localização."
        )

    def dispatch(
        self,
        update: dict[str, Any],
        *,
        on_photo: PhotoHandler | None = None,
        on_text: TextHandler | None = None,
    ) -> None:
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None:
            return
        chat_id = int(chat_id)

        text = str(message.get("text", "")).strip()
        if text in {"/start", "/help"}:
            self.send_message(
                chat_id,
                "Machine2Pipe AI ativo. Envie fotos, observações ou /status. "
                "Use /whoami para consultar o chat ID.",
            )
            return
        if text == "/whoami":
            self.send_message(chat_id, f"Chat ID: {chat_id}")
            return
        if not self._authorized(chat_id):
            if not self.allowed_chat_ids:
                log.error(
                    "TELEGRAM_CHAT_ID ausente: evidencia do chat %s recusada", chat_id
                )
                self.send_message(
                    chat_id,
                    "Nenhum chat autorizado esta configurado, entao nao posso registrar "
                    f"evidencia. Grave TELEGRAM_CHAT_ID={chat_id} nas variaveis do "
                    "servico e reimplante.",
                )
            else:
                log.warning("mensagem ignorada de chat nao autorizado: %s", chat_id)
            return
        if text == "/status":
            self.send_message(chat_id, "Agente conectado; aguardando evidências de campo.")
            return

        photo = self._store_photo(message)
        if photo:
            reply = on_photo(message, photo) if on_photo else None
            self.send_message(chat_id, reply or self.photo_ack(photo))
            return

        location = message.get("location")
        if location:
            self.send_message(
                chat_id,
                f"Localização recebida: {location['latitude']:.6f}, "
                f"{location['longitude']:.6f}.",
            )
            return

        if text and on_text:
            reply = on_text(message, text)
            if reply:
                self.send_message(chat_id, reply)

    def poll_once(
        self,
        *,
        on_photo: PhotoHandler | None = None,
        on_text: TextHandler | None = None,
        timeout: int = 25,
    ) -> None:
        data: dict[str, Any] = {"timeout": timeout, "allowed_updates": '["message"]'}
        if self.offset is not None:
            data["offset"] = self.offset
        updates = self._call("getUpdates", **data) or []
        for update in updates:
            self.offset = int(update["update_id"]) + 1
            self.dispatch(update, on_photo=on_photo, on_text=on_text)

    def run(
        self,
        stop_event: threading.Event,
        *,
        on_photo: PhotoHandler | None = None,
        on_text: TextHandler | None = None,
    ) -> None:
        log.info("Telegram long polling iniciado")
        while not stop_event.is_set():
            try:
                self.poll_once(on_photo=on_photo, on_text=on_text)
            except requests.RequestException as exc:
                log.warning("falha temporaria no Telegram: %s", exc)
                stop_event.wait(5)
            except Exception:
                log.exception("erro ao processar atualizacao do Telegram")
                stop_event.wait(2)
