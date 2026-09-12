"""Carrega as fotos reais da obra no banco, casando cada uma com trecho e telemetria.

O casamento primario e por horario, nao por GPS: a telemetria ja sabe onde a maquina
estava as 13:01, entao a foto se localiza sozinha mesmo sem metadado de posicao. Isso
importa porque o Telegram remove EXIF de imagens enviadas como "foto" — so o envio como
documento preserva —, e o Google Photos tambem descarta o GPS em qualquer redimensionamento.
O GPS da foto, quando existe, entra como conferencia.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from machine2pipe import photos as photo_module, storage  # noqa: E402
from machine2pipe.config import config  # noqa: E402
from machine2pipe.geo import project_loader  # noqa: E402
from machine2pipe.geo.matching import SegmentMatcher  # noqa: E402
from machine2pipe.geo.stationing import project_point  # noqa: E402
from machine2pipe.telemetry import loader  # noqa: E402

ALBUM = Path("data/sample/album_photos.json")
ORIGINAL_SUFFIX = "=d"
MAX_DELTA = pd.Timedelta("45min")


def download(url: str, destination: Path) -> Path | None:
    if destination.exists():
        return destination
    try:
        response = requests.get(url + ORIGINAL_SUFFIX, timeout=60)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"  falhou: {error}")
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def seed() -> None:
    urls = json.loads(ALBUM.read_text())["photos"]
    project = project_loader.load(config.project_kml_path, config.segments_csv_path)
    matcher = SegmentMatcher(project, config.target_crs, config.corridor_m)
    telemetry = loader.load()
    storage.initialize()

    stored = 0
    for index, url in enumerate(urls):
        path = Path(config.photo_storage_path) / f"album_{index:02d}.jpg"
        print(f"[{index + 1}/{len(urls)}] {path.name}")
        if not download(url, path):
            continue

        meta = photo_module.extract_metadata(path)
        if not meta.captured_at:
            print("  sem horario de captura: nao da para casar com a telemetria")
            continue

        moment = pd.Timestamp(meta.captured_at)
        if moment.tzinfo is None:
            moment = moment.tz_localize(config.timezone)

        janela = telemetry[(telemetry.timestamp - moment).abs() <= MAX_DELTA]
        if janela.empty:
            print(f"  {moment:%d/%m %H:%M}: sem telemetria na janela")
            continue

        ponto = janela.loc[(janela.timestamp - moment).abs().idxmin()]
        delta = (ponto.timestamp - moment).total_seconds()
        # A posicao vem da maquina; o GPS da foto, quando existe, so confere.
        casamento = matcher.match(ponto.latitude, ponto.longitude)

        conferencia = None
        if meta.latitude is not None:
            da_foto = project_point(meta.latitude, meta.longitude, config.target_crs)
            da_maquina = project_point(ponto.latitude, ponto.longitude, config.target_crs)
            conferencia = round(da_foto.distance(da_maquina), 1)

        storage.record_photo(
            {
                "photo_id": f"album_{moment:%Y%m%d_%H%M%S}",
                "captured_at": moment.isoformat(),
                "latitude": meta.latitude if meta.latitude is not None else float(ponto.latitude),
                "longitude": meta.longitude if meta.longitude is not None else float(ponto.longitude),
                "segment_id": casamento.segment_id if casamento.inside_corridor else None,
                "chainage_m": casamento.chainage_m if casamento.inside_corridor else None,
                "distance_to_segment_m": casamento.distance_to_axis_m,
                "telemetry_delta_seconds": delta,
                "requires_confirmation": 1,
                "source": "album",
                "file_path": str(path),
            }
        )
        stored += 1
        print(
            f"  {moment:%d/%m %H:%M} -> telemetria {ponto.timestamp:%H:%M} ({delta:+.0f}s)"
            f" | {casamento.segment_id or 'fora do corredor'}"
            + (f" estaca {casamento.chainage_m:.0f} m" if casamento.inside_corridor else "")
            + (f" | GPS da foto confere a {conferencia} m" if conferencia is not None else " | sem GPS")
        )

    print(f"\n{stored} fotos gravadas em {config.database_path}")


if __name__ == "__main__":
    seed()
