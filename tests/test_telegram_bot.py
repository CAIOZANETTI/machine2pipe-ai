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
