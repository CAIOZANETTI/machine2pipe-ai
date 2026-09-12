"""Do evento a quantidade confirmada, sem rede e sem modelo.

E o caminho que o juiz percorre na demonstracao: a maquina trabalha, o agente pergunta,
o engenheiro responde e o painel passa a mostrar metros com dono.
"""
from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

from machine2pipe import agent, ingest, llm, replay, storage, tools, vision, worker
from machine2pipe.photos import PhotoMetadata, StoredPhoto


@pytest.fixture(scope="module")
def index():
    return ingest.ProjectIndex()


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "teste.db"
    for modulo in (storage, replay):
        monkeypatch.setattr(modulo, "config", replace(modulo.config, database_path=caminho))
    storage.initialize(caminho)
    return caminho


class BotFalso:
    def __init__(self):
        self.enviadas: list[str] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.enviadas.append(text)


@pytest.fixture
def campo(index, banco, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(vision, "classify", lambda *a, **k: vision.UNREAD)
    return worker.FieldAgent(index, BotFalso(), chat_id=7161087185)


def evento_de_avanco(index) -> dict:
    worker._record_day(index)
    fila = storage.pending_events()
    avanco = fila[fila.event_type == "progress_unconfirmed"]
    assert not avanco.empty, "o dia da demonstracao precisa de um avanco nao confirmado"
    return worker._event_dict(next(avanco.itertuples()))


def test_o_dia_entra_no_banco_sem_duplicar(index, banco):
    primeira = worker._record_day(index)
    antes = len(storage.events_frame())
    worker._record_day(index)
    assert len(storage.events_frame()) == antes == primeira


def test_evento_de_avanco_vira_pergunta_no_telegram(index, campo):
    decisao = campo.handle_event(evento_de_avanco(index))
    assert decisao.decision == agent.ASK
    assert campo.bot.enviadas, "a pergunta precisa sair do processo"
    assert campo.pending["event_id"].startswith("evt_")


def test_evento_tratado_sai_da_fila(index, campo):
    evento = evento_de_avanco(index)
    campo.handle_event(evento)
    restantes = set(storage.pending_events().event_id)
    assert evento["event_id"] not in restantes, "perguntar duas vezes o mesmo cansa o campo"


def test_resposta_vira_quantidade_confirmada_com_dono(index, campo):
    evento = evento_de_avanco(index)
    campo.handle_event(evento)
    resposta = campo.on_text({"from": {"id": 42}}, "assentamos 18 m hoje")

    confirmacoes = storage.confirmations_frame()
    assert len(confirmacoes) == 1
    linha = confirmacoes.iloc[0]
    assert linha.confirmed_length_m == 18
    assert linha.status == "partially_completed"
    assert linha.confirmed_by == "telegram:42"
    assert linha.event_id == evento["event_id"], "a quantidade aponta para o evento que a pediu"
    assert linha.raw_message == "assentamos 18 m hoje"
    assert "18" in resposta
    assert campo.pending is None


def test_resposta_ambigua_nao_vira_registro(index, campo):
    campo.handle_event(evento_de_avanco(index))
    campo.on_text({"from": {"id": 42}}, "bom dia")
    assert storage.confirmations_frame().empty
    assert campo.pending is not None, "a pergunta continua aberta ate haver resposta util"


def test_texto_sem_pergunta_aberta_nao_inventa_confirmacao(campo):
    resposta = campo.on_text({"from": {"id": 42}}, "assentamos 40 m")
    assert storage.confirmations_frame().empty
    assert "pergunta em aberto" in resposta


def test_uma_pergunta_de_cada_vez(index, campo, banco):
    """Duas perguntas abertas tornariam a proxima resposta impossivel de atribuir."""
    eventos = [
        {**evento_de_avanco(index), "event_id": f"evt_sintetico_{n}", "segment_id": "tubo_concreto_40"}
        for n in (1, 2)
    ]
    primeira = campo.handle_event(eventos[0])
    segunda = campo.handle_event(eventos[1])
    assert primeira.decision == agent.ASK
    assert segunda.decision == agent.LOG
    assert len(campo.bot.enviadas) == 1
    assert campo.pending["event_id"] == "evt_sintetico_1"


def test_pergunta_em_aberto_sobrevive_ao_reinicio(index, campo):
    evento = evento_de_avanco(index)
    campo.handle_event(evento)
    reiniciado = worker.FieldAgent(campo.index, BotFalso(), chat_id=1)
    assert reiniciado.pending["event_id"] == evento["event_id"]


def foto(tmp_path, momento: datetime | None) -> StoredPhoto:
    caminho = tmp_path / "foto.jpg"
    caminho.write_bytes(b"nao e um jpeg de verdade, e o EXIF vem pronto")
    return StoredPhoto(
        path=caminho,
        source="telegram_photo",
        telegram_file_id="AgACAgEAAx",
        metadata=PhotoMetadata(captured_at=momento),
    )


def test_foto_com_horario_do_dia_cai_no_trecho(campo, tmp_path):
    resposta = campo.on_photo({}, foto(tmp_path, datetime(2022, 6, 28, 13, 1, 32)))
    fotos = storage.photos_frame()
    assert len(fotos) == 1
    linha = fotos.iloc[0]
    assert linha.segment_id, "a telemetria das 13:01 sabe onde a maquina estava"
    assert linha.requires_confirmation == 1, "foto e evidencia, nunca quantidade"
    assert linha.file_path == str(tmp_path / "foto.jpg")
    assert "13:01" in resposta


def test_foto_sem_horario_e_ancorada_no_replay(campo, tmp_path):
    campo.on_photo({}, foto(tmp_path, None))
    linha = storage.photos_frame().iloc[0]
    inicio, _ = campo.index.day_bounds
    assert pd.Timestamp(linha.captured_at) == inicio, "replay parado: ancora no inicio do dia"


def test_leitura_visual_indisponivel_nao_impede_o_arquivamento(campo, tmp_path):
    campo.on_photo({}, foto(tmp_path, datetime(2022, 6, 28, 13, 1, 32)))
    linha = storage.photos_frame().iloc[0]
    assert linha.visual_class is None
    assert linha.chainage_m is not None, "sem modelo, a geometria continua respondendo"


def test_ferramentas_registram_o_que_consultaram(index, banco):
    evento = evento_de_avanco(index)
    dados, registro = tools.briefing(evento, project=index.project)
    assert {chamada["tool"] for chamada in registro.calls} >= {
        "segment_status", "confirmation_history", "photo_evidence"
    }
    assert dados["trecho"]["planned_length_m"], "o projetado vem do projeto, nao do modelo"


def test_sem_chat_o_agente_nao_consome_a_fila(index, banco, monkeypatch):
    """Sem TELEGRAM_CHAT_ID a pergunta que carrega a demonstracao nao pode ser queimada."""
    monkeypatch.setattr(llm, "available", lambda: False)
    worker._record_day(index)
    inicio, fim = index.day_bounds
    replay.jump_to(fim, inicio)
    mudo = worker.FieldAgent(index, BotFalso(), chat_id=None)
    assert mudo.tick() == 0
    assert len(storage.pending_events()) == 18, "tudo continua pendente ate a variavel chegar"
    assert storage.agent_actions_frame().empty


def test_zerar_a_demonstracao_preserva_eventos_e_album(index, campo, tmp_path):
    campo.handle_event(evento_de_avanco(index))
    campo.on_text({"from": {"id": 42}}, "18 m")
    campo.on_photo({}, foto(tmp_path, datetime(2022, 6, 28, 13, 1, 32)))
    storage.record_photo({"photo_id": "album_x", "source": "album", "captured_at": "2022-06-28T12:59:00-03:00"})

    apagados = storage.reset_demo()

    assert apagados == {"agent_actions": 2, "confirmations": 1, "telegram_photos": 1}
    assert len(storage.events_frame()) == 18
    assert list(storage.photos_frame().photo_id) == ["album_x"]
    assert len(storage.pending_events()) == 18, "a pergunta volta a ser feita no proximo ensaio"


def test_status_diz_que_dia_e_e_o_que_a_maquina_faz(index, campo):
    inicio, _ = index.day_bounds
    replay.jump_to(inicio + pd.Timedelta(hours=8), inicio)  # 13:21 na obra
    texto = campo.status()
    assert "28/06/2022" in texto
    assert "13:21" in texto
    assert "frente de serviço" in texto
    assert "0 m confirmados de 255 m" in texto
    assert "Nenhuma pergunta em aberto" in texto


def test_status_com_replay_parado_orienta(campo):
    texto = campo.status()
    assert "parado" in texto and "inicie o replay" in texto.lower()
