from pathlib import Path

from PIL import Image

from machine2pipe.photos import PhotoStore, extract_metadata


def test_extract_metadata_does_not_invent_gps(tmp_path: Path) -> None:
    image_path = tmp_path / "plain.jpg"
    Image.new("RGB", (10, 10), "white").save(image_path)

    metadata = extract_metadata(image_path)

    assert metadata.has_gps is False
    assert metadata.latitude is None
    assert metadata.longitude is None


def test_photo_store_sanitizes_filename(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (10, 10), "white").save(source)
    store = PhotoStore(tmp_path / "photos")

    saved = store.save(
        source.read_bytes(),
        telegram_file_id="file-1",
        source="telegram_document",
        filename="../../field photo.jpg",
    )

    assert saved.path.parent == tmp_path / "photos"
    assert saved.path.name == "field_photo.jpg"
    assert saved.path.exists()
