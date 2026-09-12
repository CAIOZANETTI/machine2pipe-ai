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
    assert [t["segment_id"] for t in trechos] == ["tubo_concreto_40"]
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


@pytest.mark.parametrize(
    "token, forma_valida",
    [
        ("8847159810:AAG4g46DXI4u7ZyyAdlLrlPeL0WKjy18FwU", True),
        ("s8847159810:AAG4g46DXI4u7ZyyAdlLrlPeL0WKjy18FwU", False),  # o 's' colado na frente
        ("8847159810", False),  # so o numero, sem a chave
        ("AAG4g46DXI4u7ZyyAdlLrlPeL0WKjy18FwU", False),  # so a chave, sem o numero
    ],
)
def test_diagnostico_descreve_a_forma_do_token(cliente, monkeypatch, token, forma_valida):
    from dataclasses import replace

    from machine2pipe import api

    monkeypatch.setattr(api, "config", replace(api.config, telegram_bot_token=token))
    corpo = cliente.get("/api/telegram/check").json()
    assert corpo["token_shape_valid"] is forma_valida
    assert token not in str(corpo), "o token nunca pode aparecer na resposta"


def test_diagnostico_reconhece_token_entre_aspas(cliente, monkeypatch):
    from dataclasses import replace

    from machine2pipe import api

    monkeypatch.setattr(
        api, "config",
        replace(api.config, telegram_bot_token='"8847159810:AAG4g46DXI4u7ZyyAdlLrlPeL0WKjy18FwU"'),
    )
    corpo = cliente.get("/api/telegram/check").json()
    assert corpo["token_looks_quoted"] is True
    assert corpo["token_length"] == 48
    assert "aspas" in corpo["diagnosis"]


def test_estado_expoe_a_conversa_do_agente(cliente):
    agente = cliente.get("/api/state").json()["agent"]
    assert {"actions", "confirmations", "open_question", "model"} <= set(agente)


def test_zerar_a_demonstracao_volta_o_replay_ao_inicio(cliente):
    cliente.post("/api/replay/start")
    resposta = cliente.post("/api/agent/reset").json()
    assert set(resposta["cleared"]) == {"agent_actions", "confirmations", "telegram_photos"}
    assert resposta["replay"]["status"] == "stopped"


def test_seek_leva_o_relogio_a_qualquer_instante_do_dia(cliente):
    resposta = cliente.post("/api/replay/seek", params={"at": "2022-06-28T12:59:00-03:00"}).json()
    assert resposta["replay"]["status"] == "paused"
    estado = cliente.get("/api/state").json()
    assert estado["replay"]["simulated_time"] == "2022-06-28T12:59:00-03:00"


def test_seek_nao_sai_do_dia(cliente):
    resposta = cliente.post("/api/replay/seek", params={"at": "2022-06-28T23:00:00-03:00"}).json()
    estado = cliente.get("/api/state").json()
    assert resposta["simulated_time"] == estado["replay"]["day_end"]


def test_seek_rejeita_instante_invalido(cliente):
    assert cliente.post("/api/replay/seek", params={"at": "ontem"}).status_code == 400


def test_estado_diz_qual_modelo_esta_por_tras_do_agente(cliente):
    agente = cliente.get("/api/state").json()["agent"]
    assert agente["model"] and agente["provider"]
    assert "model_available" in agente


def test_ler_foto_desconhecida_falha_visivelmente(cliente):
    assert cliente.post("/api/photo/nao_existe/read").status_code == 404


def test_estado_oferece_os_momentos_do_dia_inteiro(cliente):
    estado = cliente.get("/api/state").json()
    assert len(estado["all_events"]) == 18, "atalhos de tempo mostram o dia inteiro, nao so o passado"
    assert estado["events"] == [], "a linha do tempo continua respeitando o relogio"


def test_foto_sem_estaca_nem_leitura_nao_derruba_o_painel(cliente, tmp_path):
    """Foto do Telegram sem EXIF e fora do corredor: chainage e confidence chegam NaN."""
    from machine2pipe import storage
    storage.record_photo({
        "photo_id": "telegram_sem_nada", "captured_at": "2022-06-28T05:21:00-03:00",
        "latitude": -26.6032, "longitude": -51.0977, "segment_id": None, "chainage_m": None,
        "distance_to_segment_m": 32.9, "telemetry_delta_seconds": 0.0, "visual_class": None,
        "confidence": None, "source": "telegram", "file_path": str(tmp_path / "x.jpg"),
    })
    resposta = cliente.get("/api/state")
    assert resposta.status_code == 200, resposta.text[:200]
    fotos = [f for f in resposta.json()["all_photos"] if f["photo_id"] == "telegram_sem_nada"]
    assert fotos, "a foto entra no payload, com os campos vazios como null"
    assert "NaN" not in resposta.text
