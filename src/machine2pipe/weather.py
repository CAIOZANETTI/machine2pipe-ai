"""Chuva historica do dia, pela Open-Meteo Archive.

Contexto, nao medicao. Um reanalise de grade nao e um pluviometro na obra, e o agente
precisa dizer isso quando usar o dado: a chuva explica uma parada, nunca a comprova.

A resposta e cacheada em disco porque o dia e historico e nunca muda.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SECONDS = 20


@dataclass
class DayWeather:
    day: str
    latitude: float
    longitude: float
    timezone: str
    precipitation_mm: float = 0.0
    rain_hours: list[str] = field(default_factory=list)
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    available: bool = True
    note: str = "reanálise de grade, não pluviômetro na obra"

    def rained(self, threshold_mm: float = 0.2) -> bool:
        return self.precipitation_mm >= threshold_mm

    def overlaps(self, hour: int) -> bool:
        """Houve chuva na hora indicada? Usado para dar contexto a uma parada."""
        return any(int(moment[11:13]) == hour for moment in self.rain_hours)

    def to_dict(self) -> dict:
        return {
            "rain_mm": round(self.precipitation_mm, 1),
            "rain_hours": self.rain_hours,
            "temperature_min_c": self.temperature_min_c,
            "temperature_max_c": self.temperature_max_c,
            "source": "open-meteo archive",
            "note": self.note,
        }


def _cache_path(cache_dir: Path, day: str, latitude: float, longitude: float) -> Path:
    return cache_dir / f"weather_{day}_{latitude:.2f}_{longitude:.2f}.json"


def fetch(
    day: str | date,
    latitude: float,
    longitude: float,
    timezone: str = "America/Sao_Paulo",
    cache_dir: Path | None = None,
) -> DayWeather:
    day = str(day)
    cache_dir = Path(cache_dir) if cache_dir else Path("data/output")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(cache_dir, day, latitude, longitude)

    if cached.exists():
        payload = json.loads(cached.read_text())
    else:
        try:
            response = requests.get(
                ARCHIVE_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "start_date": day,
                    "end_date": day,
                    "hourly": "precipitation",
                    "daily": "temperature_2m_min,temperature_2m_max",
                    "timezone": timezone,
                },
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            cached.write_text(json.dumps(payload))
        except (requests.RequestException, ValueError) as error:
            # Contexto ausente nao pode derrubar o replay; ele so deixa de ser mencionado.
            return DayWeather(
                day=day, latitude=latitude, longitude=longitude, timezone=timezone,
                available=False, note=f"contexto meteorológico indisponível: {error}",
            )

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get("precipitation") or []
    daily = payload.get("daily") or {}

    return DayWeather(
        day=day,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        precipitation_mm=float(sum(v or 0 for v in values)),
        rain_hours=[t for t, v in zip(times, values) if (v or 0) > 0],
        temperature_min_c=(daily.get("temperature_2m_min") or [None])[0],
        temperature_max_c=(daily.get("temperature_2m_max") or [None])[0],
    )
