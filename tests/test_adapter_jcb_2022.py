import pandas as pd
import pytest

from machine2pipe.telemetry.adapter_jcb_2022 import CANONICAL, SchemaError, adapt

TZ = "America/Sao_Paulo"


@pytest.fixture
def bruto():
    return pd.read_parquet("data/sample/telemetria_2022-06-28.parquet")


def test_contrato_canonico(bruto):
    df = adapt(bruto, "JCB-3CX", TZ)
    assert list(df.columns) == CANONICAL
    assert df.timestamp.dt.tz is not None
    assert (df.machine_id == "JCB-3CX").all()
    assert df.timestamp.is_monotonic_increasing


def test_movimento_vem_do_raio_sem_alteracao(bruto):
    df = adapt(bruto, "JCB-3CX", TZ)
    esperado = pd.to_numeric(bruto.raio_m, errors="coerce").fillna(0.0).sum()
    assert df.movement_m.sum() == pytest.approx(esperado)


def test_horario_local_preservado(bruto):
    df = adapt(bruto, "JCB-3CX", TZ)
    primeiro = df.timestamp.iloc[0]
    assert primeiro.utcoffset().total_seconds() == -3 * 3600
    assert str(primeiro.date()) == "2022-06-28"


def test_coordenadas_implausiveis_sao_descartadas(bruto):
    sujo = bruto.copy()
    sujo.loc[sujo.index[0], "lat"] = 999.0
    sujo.loc[sujo.index[1], "lon"] = None
    df = adapt(sujo, "JCB-3CX", TZ)
    assert len(df) == len(bruto) - 2


def test_schema_incompleto_falha_visivelmente(bruto):
    with pytest.raises(SchemaError, match="raio_m"):
        adapt(bruto.drop(columns=["raio_m"]), "JCB-3CX", TZ)
