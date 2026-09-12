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
    # O file_id prefixa para que dois IMG_0001.jpg coexistam; o nome do campo sobrevive.
    assert saved.path.name == "file-1_field_photo.jpg"
    assert saved.path.exists()


def test_dois_documentos_com_o_mesmo_nome_nao_se_apagam(tmp_path: Path) -> None:
    """Telefones repetem IMG_0001.jpg, e mandar como documento e o caminho que pedimos."""
    store = PhotoStore(tmp_path)
    primeira = store.save(b"primeira", telegram_file_id="FILE_A", source="telegram_document",
                          filename="IMG_0001.jpg")
    segunda = store.save(b"segunda", telegram_file_id="FILE_B", source="telegram_document",
                         filename="IMG_0001.jpg")
    assert primeira.path != segunda.path
    assert primeira.path.read_bytes() == b"primeira"
    assert "IMG_0001.jpg" in segunda.path.name, "o nome legivel do campo permanece"
