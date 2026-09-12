"""Adapta o relatorio bruto do rastreador JCB 3CX (2022-2023) para o contrato canonico.

Schema de origem verificado em CAIOZANETTI/gps_maquina, silver_jcb_relatorio_2022.parquet
(78.365 linhas, 2022-01-01 a 2023-08-31).

`raio_m` foi validado como o deslocamento desde o ponto anterior: correlacao 1,0 com a
haversine entre (lat, lon) e (lat_ant, lon_ant), erro medio absoluto de 0,13 m.
"""
from __future__ import annotations

import pandas as pd

CANONICAL = [
    "timestamp",
    "machine_id",
    "latitude",
    "longitude",
    "engine_on",
    "gps_valid",
    "movement_m",
    "event_type",
]

SOURCE_COLUMNS = {"data_hora", "lat", "lon", "motor_ligado", "gps_ativo", "raio_m", "atividade"}

# Atividades que o rastreador declara diretamente; nao precisam ser inferidas.
ENGINE_START = "arranque_do_motor"
ENGINE_STOP = "paragem_do_motor"
TOWED = "a_ser_rebocado_(ou_o_sinal_da_ignição_não_funciona)"


class SchemaError(ValueError):
    """O arquivo de origem nao tem as colunas esperadas."""


def adapt(raw: pd.DataFrame, machine_id: str, timezone: str) -> pd.DataFrame:
    missing = SOURCE_COLUMNS - set(raw.columns)
    if missing:
        raise SchemaError(f"colunas ausentes no relatorio de origem: {sorted(missing)}")

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(raw["data_hora"]).dt.tz_localize(timezone),
            "machine_id": machine_id,
            "latitude": pd.to_numeric(raw["lat"], errors="coerce"),
            "longitude": pd.to_numeric(raw["lon"], errors="coerce"),
            "engine_on": raw["motor_ligado"].astype(bool),
            "gps_valid": raw["gps_ativo"].astype(bool),
            "movement_m": pd.to_numeric(raw["raio_m"], errors="coerce").fillna(0.0),
            "event_type": raw["atividade"].astype("string"),
        }
    )

    df = df.dropna(subset=["latitude", "longitude"])
    plausible = df.latitude.between(-90, 90) & df.longitude.between(-180, 180)
    return df[plausible].sort_values("timestamp").reset_index(drop=True)[CANONICAL]
