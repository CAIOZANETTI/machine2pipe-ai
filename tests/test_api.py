import pytest
from fastapi.testclient import TestClient

from machine2pipe import replay
from machine2pipe.api import app


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "state_path", lambda: tmp_path / "replay_state.json")
    with TestClient(app) as cliente:
        cliente.post("/api/replay/reset")
        yield cliente


def test_health_responde_para_o_railway(cliente):
    assert cliente.get("/health").json()["status"] == "ok"


def test_pagina_do_painel_e_servida(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert b"Machine2Pipe" in resposta.content


def test_replay_parado_comeca_no_inicio_do_dia(cliente):
    estado = cliente.get("/api/state").json()
    assert estado["replay"]["status"] == "stopped"
    assert estado["replay"]["simulated_time"] == estado["replay"]["day_start"]
    assert estado["events"] == []


def test_projeto_e_servido_com_geometria_e_atributos(cliente):
    trechos = cliente.get("/api/state").json()["segments"]
    assert len(trechos) == 7
    assert all(len(t["coordinates"]) >= 2 for t in trechos)
    assert trechos[0]["diameter_mm"] == 400.0
    assert trechos[0]["confirmed_length_m"] == 0.0


def test_pular_para_um_evento_revela_a_historia_ate_ali(cliente):
    assert cliente.post("/api/replay/jump/evt_2022-06-28_001").status_code == 200
    estado = cliente.get("/api/state").json()
    assert estado["events"], "pular para o primeiro evento deve torna-lo visivel"
    assert estado["machine"]["points"] > 0


def test_evento_inexistente_falha_visivelmente(cliente):
    assert cliente.post("/api/replay/jump/evt_inexistente").status_code == 404


def test_fotos_so_aparecem_depois_de_capturadas(cliente):
    inicio = cliente.get("/api/state").json()
    assert inicio["photos"] == [], "no inicio do dia nenhuma foto foi tirada ainda"


def test_foto_inexistente_falha_visivelmente(cliente):
    assert cliente.get("/api/photo/album_00000000_000000").status_code == 404


@pytest.mark.parametrize(
    "valor, valido",
    [
        ("machine2pipe_ai_bot", False),  # o nome do bot no lugar do numero do chat
        ("123456789", True),
        ("123456789, -100200300", True),  # grupos tem id negativo
        ("", True),  # vazio e legitimo ate o /whoami responder
    ],
)
def test_health_denuncia_chat_id_nao_numerico(cliente, monkeypatch, valor, valido):
    from dataclasses import replace

    from machine2pipe import api

    monkeypatch.setattr(api, "config", replace(api.config, telegram_chat_id=valor))
    assert cliente.get("/health").json()["telegram_allowlist_valid"] is valido


def test_diagnostico_do_telegram_sem_token(cliente, monkeypatch):
    from dataclasses import replace

    from machine2pipe import api

    monkeypatch.setattr(api, "config", replace(api.config, telegram_bot_token=""))
    corpo = cliente.get("/api/telegram/check").json()
    assert corpo["token_present"] is False
    assert "ausente" in corpo["diagnosis"]
