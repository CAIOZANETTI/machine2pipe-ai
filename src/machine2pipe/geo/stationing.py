"""Estaqueamento: posicao ao longo do eixo de um trecho, em metros."""
from __future__ import annotations

from functools import lru_cache

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import transform


@lru_cache(maxsize=8)
def transformer(target_crs: str) -> Transformer:
    return Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)


def project_line(coordinates: list[tuple[float, float]], target_crs: str) -> LineString:
    """Converte (lon, lat) em uma linha no CRS metrico, onde distancia significa metro."""
    return transform(transformer(target_crs).transform, LineString(coordinates))


def project_point(latitude: float, longitude: float, target_crs: str) -> Point:
    x, y = transformer(target_crs).transform(longitude, latitude)
    return Point(x, y)


def chainage(line: LineString, point: Point) -> float:
    """Distancia percorrida ao longo do eixo ate a projecao do ponto."""
    return float(line.project(point))


def offset(line: LineString, point: Point) -> float:
    """Distancia perpendicular do ponto ao eixo."""
    return float(line.distance(point))
