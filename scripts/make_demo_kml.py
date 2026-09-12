"""Gera um projeto de drenagem provisorio sobre a rota real da maquina no dia do replay.

Serve para o pipeline geometrico rodar antes de o KML real do Google Earth chegar. O eixo
sai da direcao principal da nuvem de pontos do dia, que na obra de Calmon e alongada
(834 m no eixo principal contra 66 m de dispersao lateral): a forma de uma vala de rua.

Substituir por `PROJECT_KML_PATH` assim que o projeto real for exportado.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from machine2pipe.config import config  # noqa: E402
from machine2pipe.geo.stationing import transformer  # noqa: E402
from machine2pipe.telemetry import loader  # noqa: E402

SEGMENT_LENGTH_M = 120.0
DIAMETER_MM = 400
MATERIAL = "concrete"
SERVICE_TYPE = "drainage_pipe"

KML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Projeto provisorio — drenagem Calmon/SC</name>
    <description>Alinhamento provisorio derivado da rota real de {date}. Substituir pelo KML do Google Earth.</description>
{placemarks}  </Document>
</kml>
"""

SEGMENT_TEMPLATE = """    <Placemark>
      <name>{segment_id}</name>
      <ExtendedData>
        <Data name="segment_id"><value>{segment_id}</value></Data>
        <Data name="service_type"><value>{service_type}</value></Data>
        <Data name="diameter_mm"><value>{diameter_mm}</value></Data>
        <Data name="material"><value>{material}</value></Data>
        <Data name="planned_length_m"><value>{planned_length_m:.1f}</value></Data>
        <Data name="planned_start"><value>{date}</value></Data>
        <Data name="planned_end"><value>{date}</value></Data>
      </ExtendedData>
      <LineString><coordinates>{coordinates}</coordinates></LineString>
    </Placemark>
"""

STRUCTURE_TEMPLATE = """    <Placemark>
      <name>{structure_id}</name>
      <ExtendedData>
        <Data name="structure_id"><value>{structure_id}</value></Data>
        <Data name="service_type"><value>manhole</value></Data>
      </ExtendedData>
      <Point><coordinates>{coordinates}</coordinates></Point>
    </Placemark>
"""


def principal_axis(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    centred = points - points.mean(axis=0)
    _, _, components = np.linalg.svd(centred, full_matrices=False)
    return points.mean(axis=0), components[0]


def build() -> None:
    day = loader.load_day(config.replay_date)
    if day.empty:
        raise SystemExit(f"sem telemetria para {config.replay_date}")

    forward = transformer(config.target_crs)
    x, y = forward.transform(day.longitude.values, day.latitude.values)
    points = np.column_stack([x, y])

    centre, axis = principal_axis(points)
    along = (points - centre) @ axis
    # p5-p95 descarta deslocamentos de chegada e saida da obra.
    start = centre + axis * np.percentile(along, 5)
    end = centre + axis * np.percentile(along, 95)

    total = float(np.hypot(*(end - start)))
    count = max(1, round(total / SEGMENT_LENGTH_M))
    direction = (end - start) / total

    from pyproj import Transformer

    to_wgs84 = Transformer.from_crs(config.target_crs, "EPSG:4326", always_xy=True)

    placemarks: list[str] = []
    rows: list[dict[str, object]] = []
    nodes: list[np.ndarray] = []

    for index in range(count):
        a = start + direction * (total * index / count)
        b = start + direction * (total * (index + 1) / count)
        nodes.append(a)
        segment_id = f"TR-{index + 1:02d}"
        length = float(np.hypot(*(b - a)))
        coordinates = " ".join(
            f"{lon:.7f},{lat:.7f},0" for lon, lat in (to_wgs84.transform(*p) for p in (a, b))
        )
        placemarks.append(
            SEGMENT_TEMPLATE.format(
                segment_id=segment_id,
                service_type=SERVICE_TYPE,
                diameter_mm=DIAMETER_MM,
                material=MATERIAL,
                planned_length_m=length,
                date=config.replay_date,
                coordinates=coordinates,
            )
        )
        rows.append(
            {
                "segment_id": segment_id,
                "name": f"Trecho {index + 1}",
                "service_type": SERVICE_TYPE,
                "diameter_mm": DIAMETER_MM,
                "material": MATERIAL,
                "planned_length_m": round(length, 1),
            }
        )
    nodes.append(end)

    for index, node in enumerate(nodes):
        lon, lat = to_wgs84.transform(*node)
        placemarks.append(
            STRUCTURE_TEMPLATE.format(
                structure_id=f"PV-{index + 1:02d}", coordinates=f"{lon:.7f},{lat:.7f},0"
            )
        )

    kml_path = config.project_kml_path
    kml_path.parent.mkdir(parents=True, exist_ok=True)
    kml_path.write_text(
        KML_TEMPLATE.format(placemarks="".join(placemarks), date=config.replay_date),
        encoding="utf-8",
    )

    with config.segments_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{kml_path}: {count} trechos, {total:.0f} m de eixo, {len(nodes)} estruturas")
    print(f"{config.segments_csv_path}: atributos de apoio")


if __name__ == "__main__":
    build()
