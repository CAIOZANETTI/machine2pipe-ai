"""O agente pode errar a decisao; nao pode inventar quantidade nem silenciar o motor."""
from dataclasses import replace

import pytest

from machine2pipe import agent, events as event_rules, llm

EVENTO = {
    "event_id": "evt_2022-06-28_017",
    "event_type": event_rules.PROGRESS_UNCONFIRMED,
    "timestamp": "2022-06-28T17:05:00-03:00",
    "machine_id": "JCB-3CX",
    "segment_id": "tubo_concreto_40",
    "chainage_m": 182.5,
    "distance_to_axis_m": 3.2,
    "engine_on": True,
    "moving": False,
    "movement_m": 4.0,
    "dwell_minutes": 25.0,
    "context": {"planned_diameter_mm": 400, "planned_material": "concrete"},
}


@pytest.fixture
def sem_modelo(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


def responde(monkeypatch, payload):
    """Instala uma resposta do modelo sem tocar na rede."""
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: payload)


def test_sem_modelo_o_evento_ainda_vira_pergunta(sem_modelo):
    decisao = agent.decide(EVENTO)
    assert decisao.decision == agent.ASK
    assert decisao.expects_reply
    assert "tubo_concreto_40" in decisao.message
    assert "182" in decisao.message


def test_o_modelo_nao_pode_silenciar_o_que_a_regra_manda_perguntar(monkeypatch):
    responde(monkeypatch, {"decision": "ignore", "message": "", "confidence": 0.9,
                           "rationale": "irrelevante"})
    decisao = agent.decide(EVENTO)
    assert decisao.decision == agent.ASK, "o piso deterministico prevalece"
    assert decisao.message, "uma pergunta sem texto nao chega a ninguem"


def test_o_modelo_pode_elevar_o_cuidado_um_nivel(monkeypatch):
    evento = {**EVENTO, "event_type": event_rules.GPS_GAP}
    responde(monkeypatch, {"decision": "notify", "message": "Sinal sumiu por 30 min.",
                           "confidence": 0.4, "rationale": "lacuna longa"})
    assert agent.decide(evento).decision == agent.NOTIFY


def test_modelo_indisponivel_cai_na_regra(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)

    def falha(*a, **k):
        raise llm.LLMUnavailable("402 sem credito")

    monkeypatch.setattr(llm, "structured", falha)
    decisao = agent.decide(EVENTO)
    assert decisao.decision == agent.ASK
    assert "402" in decisao.rationale


@pytest.mark.parametrize(
    "texto,comprimento,status",
    [
        ("assentamos 18 m hoje", 18.0, "partially_completed"),
        ("18m", 18.0, "partially_completed"),
        ("22,5 metros", 22.5, "partially_completed"),
        ("terminei o trecho", None, "completed"),
        ("paramos por chuva", None, "interrupted"),
        ("bom dia", None, "unclear"),
    ],
)
def test_leitura_deterministica_da_resposta(sem_modelo, texto, comprimento, status):
    leitura = agent.read_reply(texto)
    assert leitura.confirmed_length_m == comprimento
    assert leitura.status == status


def test_motivo_da_interrupcao_sai_do_texto(sem_modelo):
    leitura = agent.read_reply("parou por chuva forte depois do almoco")
    assert leitura.status == "interrupted"
    assert leitura.interruption_reason == "chuva"


def test_quantidade_ausente_do_texto_e_descartada(monkeypatch):
    """A guarda que importa: 32 m que ninguem escreveu nao entra no banco."""
    responde(monkeypatch, {
        "confirmed_length_m": 32,
        "status": "partially_completed",
        "interruption_reason": None,
        "acknowledgement": "Registrado.",
    })
    leitura = agent.read_reply("avancamos bastante hoje")
    assert leitura.confirmed_length_m is None


def test_quantidade_escrita_pela_pessoa_e_aceita(monkeypatch):
    responde(monkeypatch, {
        "confirmed_length_m": 32,
        "status": "partially_completed",
        "interruption_reason": None,
        "acknowledgement": "Registrado: 32 m.",
    })
    assert agent.read_reply("fechamos 32 m de tubo").confirmed_length_m == 32


def test_status_fora_do_contrato_vira_indefinido(monkeypatch):
    responde(monkeypatch, {
        "confirmed_length_m": None,
        "status": "quase_pronto",
        "interruption_reason": None,
        "acknowledgement": "ok",
    })
    leitura = agent.read_reply("acho que deu")
    assert leitura.status == "unclear"
    assert not leitura.conclusive


def test_nan_nao_vaza_para_a_pergunta(sem_modelo):
    """Estaca ausente chega do SQLite como NaN; "estaca nan m" nao pode ir ao campo."""
    evento = {**EVENTO, "chainage_m": float("nan"), "dwell_minutes": float("nan")}
    mensagem = agent.decide(evento).message
    assert "nan" not in mensagem.lower()
    assert "estaca" not in mensagem, "sem estaca conhecida, a pergunta nao inventa uma"


def test_saida_do_corredor_sem_duracao_nao_diz_zero(sem_modelo):
    evento = {**EVENTO, "event_type": event_rules.OUTSIDE_PROJECT, "dwell_minutes": 0.0}
    mensagem = agent.decide(evento).message
    assert "0 min" not in mensagem
    assert "07:05" in mensagem or "17:05" in mensagem


def test_o_modelo_sobe_um_nivel_nunca_dois(monkeypatch):
    """Falha de GPS as 07:05 nao vira pergunta: em producao virou, e engoliu a que importava."""
    evento = {**EVENTO, "event_type": event_rules.GPS_GAP, "segment_id": None}
    responde(monkeypatch, {"decision": "ask", "message": "Qual o motivo da parada?",
                           "confidence": 1.0, "rationale": "parada longa"})
    decisao = agent.decide(evento)
    assert decisao.decision == agent.NOTIFY
    assert decisao.message, "avisar ainda exige texto"


def test_sem_trecho_nao_ha_pergunta(monkeypatch):
    """A resposta a uma pergunta sem trecho nao teria onde ser gravada."""
    evento = {**EVENTO, "event_type": event_rules.OUTSIDE_PROJECT, "segment_id": None}
    responde(monkeypatch, {"decision": "ask", "message": "O que houve?",
                           "confidence": 0.8, "rationale": "fora do projeto"})
    assert agent.decide(evento).decision == agent.NOTIFY


def test_fora_do_projeto_com_trecho_pode_virar_pergunta(monkeypatch):
    evento = {**EVENTO, "event_type": event_rules.OUTSIDE_PROJECT}
    responde(monkeypatch, {"decision": "ask", "message": "O que houve?",
                           "confidence": 0.8, "rationale": "fora do projeto"})
    assert agent.decide(evento).decision == agent.ASK
