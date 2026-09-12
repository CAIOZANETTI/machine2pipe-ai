import pytest

from machine2pipe import events, storage
from machine2pipe.config import config
from machine2pipe.geo import project_loader
from machine2pipe.geo.matching import SegmentMatcher
from machine2pipe.telemetry import loader

LIMIARES = dict(
    machine_id="JCB-3CX",
    long_dwell_minutes=config.long_dwell_minutes,
    dwell_movement_m=config.dwell_movement_m,
    gps_gap_minutes=config.gps_gap_minutes,
    outside_project_minutes=config.outside_project_minutes,
)


@pytest.fixture(scope="module")
def casado():
    projeto = project_loader.load(config.project_kml_path, config.segments_csv_path)
    matcher = SegmentMatcher(projeto, config.target_crs, config.corridor_m)
    return matcher.match_frame(loader.load_day("2022-06-28")), projeto


@pytest.fixture
def banco(tmp_path):
    caminho = tmp_path / "teste.db"
    storage.initialize(caminho)
    return caminho


def test_eventos_sao_reproduziveis(casado):
    frame, projeto = casado
    primeira = events.detect(frame, project=projeto, **LIMIARES)
    segunda = events.detect(frame, project=projeto, **LIMIARES)
    assert [e.to_dict() for e in primeira] == [e.to_dict() for e in segunda]
    assert primeira, "o dia da demonstracao precisa gerar eventos"


def test_identificadores_sao_unicos_e_datados(casado):
    frame, projeto = casado
    lista = events.detect(frame, project=projeto, **LIMIARES)
    ids = [e.event_id for e in lista]
    assert len(ids) == len(set(ids))
    assert all(e.event_id.startswith("evt_2022-06-28_") for e in lista)


def test_evento_carrega_o_contexto_do_projeto(casado):
    frame, projeto = casado
    entrada = next(e for e in events.detect(frame, project=projeto, **LIMIARES)
                   if e.event_type == events.ENTERED_SEGMENT)
    assert entrada.segment_id is not None
    assert entrada.context["planned_diameter_mm"] == 400.0
    assert entrada.chainage_m is not None


def test_trecho_ja_confirmado_nao_gera_nova_cobranca(casado):
    frame, projeto = casado
    todos = events.detect(frame, project=projeto, **LIMIARES)
    pendentes = {e.segment_id for e in todos if e.event_type == events.PROGRESS_UNCONFIRMED}
    assert pendentes
    alvo = next(iter(pendentes))
    depois = events.detect(frame, project=projeto, confirmed_segments={alvo}, **LIMIARES)
    assert alvo not in {e.segment_id for e in depois if e.event_type == events.PROGRESS_UNCONFIRMED}


def test_gravacao_de_eventos_e_idempotente(casado, banco):
    frame, projeto = casado
    lista = events.detect(frame, project=projeto, **LIMIARES)
    assert storage.record_events(lista, banco) == len(lista)
    assert storage.record_events(lista, banco) == 0
    assert len(storage.events_frame(banco)) == len(lista)


def test_quantidade_sem_fonte_humana_nao_entra(banco):
    with pytest.raises(storage.StorageError, match="confirmed_by"):
        storage.record_confirmation(
            segment_id="TR-04", status="completed", confirmed_by="", database_path=banco
        )
    assert storage.confirmations_frame(banco).empty


def test_status_invalido_e_recusado(banco):
    with pytest.raises(storage.StorageError, match="status"):
        storage.record_confirmation(
            segment_id="TR-04", status="quase_pronto", confirmed_by="telegram:1", database_path=banco
        )


def test_progresso_confirmado_soma_por_trecho(banco):
    for metros in (18, 14):
        storage.record_confirmation(
            segment_id="TR-04", status="partially_completed", confirmed_length_m=metros,
            confirmed_by="telegram:123456789", event_id="evt_2022-06-28_003",
            interruption_reason="rain", raw_message="instalamos 18 metros",
            database_path=banco,
        )
    total = storage.confirmed_progress(banco)
    assert total.loc[0, "confirmed_length_m"] == 32
    assert total.loc[0, "confirmations"] == 2
    assert storage.confirmed_segment_ids(banco) == {"TR-04"}


def test_fila_de_pendentes_exclui_o_que_o_agente_ja_tratou(casado, banco):
    frame, projeto = casado
    lista = events.detect(frame, project=projeto, **LIMIARES)
    storage.record_events(lista, banco)
    assert len(storage.pending_events(database_path=banco)) == len(lista)

    storage.record_agent_action(
        event_id=lista[0].event_id, decision="ask", confidence=0.8,
        message="Quantos metros foram assentados?", database_path=banco,
    )
    pendentes = storage.pending_events(database_path=banco)
    assert len(pendentes) == len(lista) - 1
    assert lista[0].event_id not in set(pendentes.event_id)
    assert storage.handled_event_ids(banco) == {lista[0].event_id}


def test_fila_respeita_o_tempo_simulado(casado, banco):
    frame, projeto = casado
    lista = events.detect(frame, project=projeto, **LIMIARES)
    storage.record_events(lista, banco)
    corte = lista[2].timestamp.isoformat()
    ate_ali = storage.pending_events(until=corte, database_path=banco)
    assert all(t <= corte for t in ate_ali.timestamp)
