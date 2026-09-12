import json

import pytest

from machine2pipe import weather

RESPOSTA = {
    "hourly": {
        "time": [f"2022-06-28T{h:02d}:00" for h in range(24)],
        "precipitation": [0] * 13 + [0.4, 1.9, 0.8] + [0] * 8,
    },
    "daily": {"temperature_2m_min": [9.4], "temperature_2m_max": [17.1]},
}


@pytest.fixture
def cache(tmp_path):
    (tmp_path / "weather_2022-06-28_-26.60_-51.10.json").write_text(json.dumps(RESPOSTA))
    return tmp_path


def test_soma_a_chuva_e_marca_as_horas(cache):
    dia = weather.fetch("2022-06-28", -26.60, -51.10, cache_dir=cache)
    assert dia.available
    assert dia.precipitation_mm == pytest.approx(3.1)
    assert dia.rained()
    assert [h[11:16] for h in dia.rain_hours] == ["13:00", "14:00", "15:00"]
    assert dia.temperature_min_c == 9.4


def test_sobreposicao_por_hora_da_contexto_a_parada(cache):
    dia = weather.fetch("2022-06-28", -26.60, -51.10, cache_dir=cache)
    assert dia.overlaps(14)
    assert not dia.overlaps(9)


def test_dia_seco_nao_e_relatado_como_chuva(cache, tmp_path):
    seco = dict(RESPOSTA, hourly={"time": RESPOSTA["hourly"]["time"], "precipitation": [0] * 24})
    (tmp_path / "weather_2022-06-28_-26.60_-51.10.json").write_text(json.dumps(seco))
    assert not weather.fetch("2022-06-28", -26.60, -51.10, cache_dir=tmp_path).rained()


def test_falha_de_rede_nao_derruba_o_replay(tmp_path, monkeypatch):
    import requests

    def falha(*_args, **_kwargs):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(weather.requests, "get", falha)
    dia = weather.fetch("2022-06-28", -26.60, -51.10, cache_dir=tmp_path)
    assert not dia.available
    assert dia.precipitation_mm == 0.0
    assert "indisponível" in dia.note


def test_contexto_declara_a_origem_e_a_limitacao(cache):
    contexto = weather.fetch("2022-06-28", -26.60, -51.10, cache_dir=cache).to_dict()
    assert contexto["source"] == "open-meteo archive"
    assert "pluviômetro" in contexto["note"]
