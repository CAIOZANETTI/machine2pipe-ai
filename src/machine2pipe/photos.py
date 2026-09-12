"""Photo ingestion and EXIF extraction for Telegram field evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image


@dataclass(frozen=True)
class PhotoMetadata:
    captured_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass(frozen=True)
class StoredPhoto:
    path: Path
    source: str
    telegram_file_id: str
    metadata: PhotoMetadata


def _number(value: Any) -> float:
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / float(value.denominator)
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]) / float(value[1])
    return float(value)


def _degrees(value: Any, ref: str | bytes | None) -> float | None:
    if not value or len(value) != 3:
        return None
    degrees = _number(value[0]) + _number(value[1]) / 60 + _number(value[2]) / 3600
    ref_text = ref.decode(errors="ignore") if isinstance(ref, bytes) else str(ref or "")
    return -degrees if ref_text.upper() in {"S", "W"} else degrees


def _gps_ifd(exif: Any) -> dict[int, Any]:
    try:
        return dict(exif.get_ifd(ExifTags.IFD.GPSInfo))
    except (AttributeError, KeyError, TypeError, ValueError):
        raw = exif.get(34853, {})
        return dict(raw) if isinstance(raw, dict) else {}


def _captured_at(exif: Any) -> datetime | None:
    candidates: list[Any] = [exif.get(36867), exif.get(306)]
    try:
        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
        candidates.insert(0, exif_ifd.get(36867))
    except (AttributeError, KeyError, TypeError, ValueError):
        pass

    for value in candidates:
        if isinstance(value, bytes):
            value = value.decode(errors="ignore")
        if value:
            try:
                return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return None


def extract_metadata(path: Path) -> PhotoMetadata:
    """Read original EXIF without guessing missing coordinates or timestamps."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
    except (OSError, ValueError):
        return PhotoMetadata()

    gps = _gps_ifd(exif)
    latitude = _degrees(gps.get(2), gps.get(1))
    longitude = _degrees(gps.get(4), gps.get(3))
    altitude = None
    if gps.get(6) is not None:
        altitude = _number(gps[6])
        if gps.get(5) == 1:
            altitude = -altitude

    return PhotoMetadata(
        captured_at=_captured_at(exif),
        latitude=latitude,
        longitude=longitude,
        altitude_m=altitude,
    )


class PhotoStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def save(
        self,
        content: bytes,
        *,
        telegram_file_id: str,
        source: str,
        filename: str | None = None,
    ) -> StoredPhoto:
        self.root.mkdir(parents=True, exist_ok=True)
        candidate = filename or f"{telegram_file_id}.jpg"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(candidate).name)
        if not safe_name or safe_name in {".", ".."}:
            safe_name = f"{telegram_file_id}.jpg"
        path = self.root / safe_name
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(content)
        temporary.replace(path)
        return StoredPhoto(
            path=path,
            source=source,
            telegram_file_id=telegram_file_id,
            metadata=extract_metadata(path),
        )
