from pathlib import Path

from machine2pipe.photos import PhotoMetadata, PhotoStore, StoredPhoto
from machine2pipe.telegram_bot import TelegramBot, parse_chat_allowlist, select_largest_photo


class FakeSession:
    pass


def make_bot(tmp_path: Path) -> TelegramBot:
    return TelegramBot(
        "test-token",
        photo_store=PhotoStore(tmp_path),
        session=FakeSession(),  # type: ignore[arg-type]
    )


def test_parse_chat_allowlist() -> None:
    assert parse_chat_allowlist("123, 456") == {123, 456}
    assert parse_chat_allowlist("") == set()


def test_select_largest_photo() -> None:
    message = {"photo": [{"file_id": "small", "file_size": 10}, {"file_id": "big", "file_size": 20}]}
    assert select_largest_photo(message)["file_id"] == "big"


def test_photo_ack_requires_confirmation_without_gps(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    photo = StoredPhoto(tmp_path / "photo.jpg", "telegram_photo", "id", PhotoMetadata())

    reply = bot.photo_ack(photo)

    assert "sem GPS confiável" in reply
    assert "arquivo/documento" in reply


def test_photo_ack_reports_existing_gps(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    metadata = PhotoMetadata(latitude=-26.59, longitude=-51.09)
    photo = StoredPhoto(tmp_path / "photo.jpg", "telegram_document", "id", metadata)

    reply = bot.photo_ack(photo)

    assert "-26.590000, -51.090000" in reply
    assert "correlação" in reply


def test_chat_id_nao_numerico_nao_derruba_o_worker() -> None:
    """Gravar o nome do bot em TELEGRAM_CHAT_ID e um engano previsivel; nao pode ser fatal."""
    assert parse_chat_allowlist("machine2pipe_ai_bot") == set()
    assert parse_chat_allowlist("7161087185, @bot") == {7161087185}


class BotEspiao(TelegramBot):
    """Captura o que seria enviado, sem tocar na API do Telegram."""

    def __init__(self, tmp_path: Path, allowed: set[int] | None = None) -> None:
        super().__init__("test-token", photo_store=PhotoStore(tmp_path), allowed_chat_ids=allowed)
        self.enviadas: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.enviadas.append((chat_id, text))


def mensagem(chat_id: int, texto: str) -> dict:
    return {"message": {"chat": {"id": chat_id}, "from": {"id": chat_id}, "text": texto}}


def test_allowlist_vazia_nao_autoriza_ninguem(tmp_path: Path) -> None:
    """Sem TELEGRAM_CHAT_ID, um estranho nao grava evidencia no banco do projeto."""
    bot = BotEspiao(tmp_path)
    recebidas = []
    bot.dispatch(mensagem(999, "assentamos 40 m"), on_text=lambda m, t: recebidas.append(t))

    assert recebidas == [], "a evidencia de um chat nao autorizado nao chega ao agente"
    assert "TELEGRAM_CHAT_ID=999" in bot.enviadas[0][1], "a recusa diz o que configurar"


def test_chat_autorizado_chega_ao_agente(tmp_path: Path) -> None:
    bot = BotEspiao(tmp_path, allowed={7161087185})
    recebidas = []
    bot.dispatch(
        mensagem(7161087185, "assentamos 40 m"),
        on_text=lambda m, t: recebidas.append(t) or "ok",
    )
    assert recebidas == ["assentamos 40 m"]


def test_estranho_com_allowlist_configurada_e_ignorado_em_silencio(tmp_path: Path) -> None:
    bot = BotEspiao(tmp_path, allowed={7161087185})
    bot.dispatch(mensagem(999, "assentamos 40 m"), on_text=lambda m, t: None)
    assert bot.enviadas == [], "com allowlist valida, um estranho nao recebe resposta nenhuma"


def test_whoami_responde_antes_da_allowlist(tmp_path: Path) -> None:
    """Sem isso ninguem descobriria o proprio chat id para configurar a allowlist."""
    bot = BotEspiao(tmp_path, allowed={7161087185})
    bot.dispatch(mensagem(999, "/whoami"))
    assert bot.enviadas == [(999, "Chat ID: 999")]
