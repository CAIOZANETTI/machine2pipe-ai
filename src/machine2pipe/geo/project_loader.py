"""Le o projeto de tubulacao exportado do Google Earth (KML ou KMZ).

O Google Earth Web nao grava `ExtendedData`: cada feicao sai apenas com `<name>` e
`<description>`. Por isso os atributos sao procurados em tres lugares, nesta ordem:
ExtendedData, linhas `chave: valor` da descricao e, por fim, um CSV de apoio indexado
por `segment_id`.
"""
from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

_COORD = re.compile(r"[\s,]+")
_KEY_VALUE = re.compile(r"^\s*([\w\s/()-]+?)\s*[:=]\s*(.+?)\s*$")
NUMERIC_FIELDS = ("diameter_mm", "planned_length_m")


@dataclass
class Segment:
    segment_id: str
    name: str
    coordinates: list[tuple[float, float]]  # (lon, lat)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class Structure:
    structure_id: str
    name: str
    coordinate: tuple[float, float]
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class Project:
    segments: list[Segment] = field(default_factory=list)
    structures: list[Structure] = field(default_factory=list)

    def segment(self, segment_id: str) -> Segment | None:
        return next((s for s in self.segments if s.segment_id == segment_id), None)


class ProjectError(ValueError):
    """O arquivo de projeto nao pode ser interpretado."""


def _read_kml_bytes(path: Path) -> bytes:
    if path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise ProjectError(f"{path} nao contem nenhum .kml")
            return archive.read(names[0])
    return path.read_bytes()


def _find(element, tag: str):
    """Busca ignorando o namespace, que varia entre Google Earth Web, Pro e outros editores."""
    return element.xpath(f".//*[local-name()='{tag}']")


def _text(element, tag: str) -> str:
    found = _find(element, tag)
    return (found[0].text or "").strip() if found else ""


def _parse_coordinates(raw: str) -> list[tuple[float, float]]:
    points = []
    for chunk in raw.split():
        parts = _COORD.split(chunk.strip())
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return points


def _attributes_from_extended_data(placemark) -> dict[str, str]:
    attributes = {}
    for node in _find(placemark, "Data"):
        key = node.get("name")
        if key:
            attributes[key] = _text(node, "value")
    for node in _find(placemark, "SimpleData"):
        key = node.get("name")
        if key:
            attributes[key] = (node.text or "").strip()
    return attributes


def _attributes_from_description(description: str) -> dict[str, str]:
    attributes = {}
    for line in re.sub(r"<[^>]+>", "\n", description).splitlines():
        match = _KEY_VALUE.match(line)
        if match:
            attributes[match.group(1).strip().lower().replace(" ", "_")] = match.group(2)
    return attributes


def _coerce(attributes: dict[str, object]) -> dict[str, object]:
    for key in NUMERIC_FIELDS:
        value = attributes.get(key)
        if isinstance(value, str):
            try:
                attributes[key] = float(value.replace(",", "."))
            except ValueError:
                pass
    return attributes


def _load_csv_attributes(path: Path | None) -> dict[str, dict[str, str]]:
    if not path or not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {row["segment_id"]: {k: v for k, v in row.items() if k != "segment_id"} for row in rows}


def load(kml_path: Path, segments_csv: Path | None = None) -> Project:
    kml_path = Path(kml_path)
    if not kml_path.exists():
        raise ProjectError(f"projeto nao encontrado: {kml_path}")

    root = etree.fromstring(_read_kml_bytes(kml_path))
    csv_attributes = _load_csv_attributes(segments_csv)
    project = Project()

    for placemark in _find(root, "Placemark"):
        name = _text(placemark, "name")
        attributes: dict[str, object] = _attributes_from_description(
            _text(placemark, "description")
        )
        attributes.update(_attributes_from_extended_data(placemark))

        for line in _find(placemark, "LineString"):
            coordinates = _parse_coordinates(_text(line, "coordinates"))
            if len(coordinates) < 2:
                continue
            segment_id = str(attributes.get("segment_id") or name or f"TR-{len(project.segments) + 1:02d}")
            merged = {**csv_attributes.get(segment_id, {}), **attributes}
            project.segments.append(
                Segment(segment_id, name or segment_id, coordinates, _coerce(merged))
            )

        for point in _find(placemark, "Point"):
            coordinates = _parse_coordinates(_text(point, "coordinates"))
            if not coordinates:
                continue
            structure_id = str(attributes.get("structure_id") or name or f"PV-{len(project.structures) + 1:02d}")
            project.structures.append(
                Structure(structure_id, name or structure_id, coordinates[0], _coerce(dict(attributes)))
            )

    if not project.segments:
        raise ProjectError(f"{kml_path} nao contem nenhuma LineString utilizavel")
    return project
