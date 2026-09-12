"""Le a telemetria bruta de um arquivo local ou de uma URL publica e entrega o contrato canonico."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from machine2pipe.config import config
from machine2pipe.telemetry.adapter_jcb_2022 import adapt


def load_raw(path: Path | None = None, url: str | None = None) -> pd.DataFrame:
    path = path or config.telemetry_path
    url = url if url is not None else config.telemetry_url
    if path.exists():
        return pd.read_parquet(path)
    if url:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.read_parquet(url)
        frame.to_parquet(path)
        return frame
    raise FileNotFoundError(
        f"telemetria nao encontrada em {path} e TELEMETRY_URL nao definida"
    )


def load(path: Path | None = None, url: str | None = None) -> pd.DataFrame:
    return adapt(load_raw(path, url), config.machine_id, config.timezone)


def load_day(date: str | None = None, **kwargs) -> pd.DataFrame:
    """Telemetria canonica de um unico dia, no fuso do projeto."""
    day = pd.Timestamp(date or config.replay_date).date()
    df = load(**kwargs)
    return df[df.timestamp.dt.date == day].reset_index(drop=True)
