"""Configuracao unica do sistema. Todos os limiares vivem aqui, nunca no prompt."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]


def _path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else ROOT / value


@dataclass(frozen=True)
class Config:
    telemetry_path: Path = _path("TELEMETRY_PATH", "data/silver_jcb_relatorio_2022.parquet")
    telemetry_url: str = os.getenv(
        "TELEMETRY_URL",
        "https://raw.githubusercontent.com/CAIOZANETTI/gps_maquina/main/data/silver_jcb_relatorio_2022.parquet",
    )
    # O projeto real exportado do Google Earth e o padrao. O KML provisorio de
    # `data/sample/` continua no repositorio, mas so entra se apontado explicitamente.
    project_kml_path: Path = _path(
        "PROJECT_KML_PATH", "data/project/calmon_jit_machine2pipe-ai.kml"
    )
    segments_csv_path: Path = _path("SEGMENTS_CSV_PATH", "data/project/segments.csv")
    database_path: Path = _path("DATABASE_PATH", "data/machine2pipe.db")
    photo_storage_path: Path = _path("PHOTO_STORAGE_PATH", "data/photos")

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "openrouter")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    # Visao, saida estruturada e barato o bastante para o credito do hackathon.
    llm_model: str = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")
    # Um evento silencioso nao existe para o engenheiro; um evento repetido cansa.
    # O loop do agente acorda neste intervalo de tempo real, nao simulado.
    agent_tick_seconds: float = float(os.getenv("AGENT_TICK_SECONDS", "20"))
    exa_api_key: str = os.getenv("EXA_API_KEY", "")

    replay_date: str = os.getenv("REPLAY_DATE", "2022-06-28")
    replay_speed: float = float(os.getenv("REPLAY_SPEED", "60"))
    timezone: str = os.getenv("TIMEZONE", "America/Sao_Paulo")
    machine_id: str = os.getenv("MACHINE_ID", "JCB-3CX")
    target_crs: str = os.getenv("TARGET_CRS", "EPSG:31982")

    corridor_m: float = float(os.getenv("PROJECT_CORRIDOR_M", "25"))
    long_dwell_minutes: float = float(os.getenv("LONG_DWELL_MINUTES", "45"))
    dwell_movement_m: float = float(os.getenv("DWELL_MOVEMENT_M", "20"))
    gps_gap_minutes: float = float(os.getenv("GPS_GAP_MINUTES", "30"))
    outside_project_minutes: float = float(os.getenv("OUTSIDE_PROJECT_MINUTES", "20"))


config = Config()
