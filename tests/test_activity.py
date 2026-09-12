"""A leitura de comportamento e regra de engenharia: mesma telemetria, mesma leitura."""
import pandas as pd
import pytest

from machine2pipe import activity
from machine2pipe.config import config
from machine2pipe.geo import project_loader
from machine2pipe.geo.matching import SegmentMatcher
from machine2pipe.telemetry import loader


@pytest.fixture(scope="module")
def dia():
    projeto = project_loader.load(config.project_kml_path, config.segments_csv_path)
    matcher = SegmentMatcher(projeto, config.target_crs, config.corridor_m)
    return matcher.match_frame(loader.load_day("2022-06-28")), projeto


def test_leitura_e_reproduzivel(dia):
    casado, projeto = dia
    primeira = [e.to_dict() for e in activity.episodes(casado, project=projeto)]
    segunda = [e.to_dict() for e in activity.episodes(casado, project=projeto)]
    assert primeira == segunda


def test_o_dia_real_tem_frente_canteiro_e_jazida(dia):
    casado, projeto = dia
    horas = activity.summary(activity.episodes(casado, project=projeto))["hours"]
    assert horas[activity.FRENTE] > 4, "a jornada de 11,9 h e majoritariamente frente de servico"
    assert horas[activity.DESLIGADA] > 1, "almoco e fim de turno nao sao frente"
    assert horas[activity.CANTEIRO] > 2
    assert horas[activity.JAZIDA] > 0.5
    assert activity.ABASTECENDO not in horas, "o posto ficou a mais de 200 m o dia inteiro"


def test_a_frente_da_tarde_cobre_as_fotos(dia):
    """As fotos das 12:59 e 13:01 na estaca 114 caem dentro de uma frente de servico."""
    casado, projeto = dia
    episodios = activity.episodes(casado, project=projeto)
    fotos = pd.DataFrame({
        "photo_id": ["album_a", "album_b"],
        "captured_at": ["2022-06-28T12:59:00-03:00", "2022-06-28T13:01:32-03:00"],
    })
    activity.attach_photos(episodios, fotos)
    frente = next(e for e in episodios if e.photo_ids)
    assert frente.state == activity.FRENTE
    assert frente.photo_ids == ["album_a", "album_b"]
    assert frente.chainage_min_m <= 114.4 <= frente.chainage_max_m
    assert "2 foto(s)" in frente.describe()


def casado_sintetico(linhas):
    """Pontos de 10 em 10 minutos. Cada linha: (motor, movimento_m, no_corredor, estaca)."""
    inicio = pd.Timestamp("2022-06-28 08:00", tz="America/Sao_Paulo")
    return pd.DataFrame({
        "timestamp": [inicio + pd.Timedelta(minutes=10 * i) for i in range(len(linhas))],
        "engine_on": [l[0] for l in linhas],
        "movement_m": [l[1] for l in linhas],
        "inside_corridor": [l[2] for l in linhas],
        "chainage_m": [l[3] for l in linhas],
        "x_m": [0.0] * len(linhas),
        "y_m": [0.0] * len(linhas),
    })


def test_motor_desligado_curto_nao_encerra_a_frente():
    """Desliga por 10 min para posicionar o tubo e religa: continua a mesma frente."""
    casado = casado_sintetico([
        (True, 0, True, 100), (False, 0, True, 100), (True, 2, True, 102), (True, 1, True, 103),
    ])
    episodios = activity.episodes(casado, short_stop_minutes=15)
    assert [e.state for e in episodios] == [activity.FRENTE]
    assert episodios[0].chainage_min_m == 100 and episodios[0].chainage_max_m == 103


def test_motor_desligado_longo_encerra_a_frente():
    casado = casado_sintetico([
        (True, 0, True, 100), (False, 0, True, 100), (False, 0, True, 100),
        (False, 0, True, 100), (True, 0, True, 100),
    ])
    episodios = activity.episodes(casado, short_stop_minutes=15)
    assert [e.state for e in episodios] == [activity.FRENTE, activity.DESLIGADA, activity.FRENTE]


def test_transito_pertence_ao_intervalo_em_que_aconteceu():
    """O salto de 400 m registrado as 08:20 aconteceu entre 08:10 e 08:20."""
    casado = casado_sintetico([
        (True, 0, True, 100), (True, 0, True, 100), (True, 400, False, 0), (True, 0, False, 0),
    ])
    episodios = activity.episodes(casado)
    assert [(e.state, f"{e.start:%H:%M}") for e in episodios] == [
        (activity.FRENTE, "08:00"), (activity.DESLOCANDO, "08:10"), (activity.PARADA, "08:20"),
    ]


def test_eventos_no_mesmo_segundo_viram_um_instante():
    casado = casado_sintetico([(True, 0, True, 100), (True, 0, True, 100)])
    casado.loc[1, "timestamp"] = casado.loc[0, "timestamp"]
    casado.loc[1, "movement_m"] = 5
    pontos = activity.classify_points(casado)
    assert len(pontos) == 1
    assert pontos.movement_m.iloc[0] == 5


def test_recorte_ate_o_instante_simulado(dia):
    casado, projeto = dia
    episodios = activity.episodes(casado, project=projeto)
    meio_dia = pd.Timestamp("2022-06-28 12:00", tz="America/Sao_Paulo")
    recorte = activity.until(episodios, meio_dia)
    assert recorte and recorte[-1].end == meio_dia
    assert all(e.start <= meio_dia for e in recorte)
    assert len(episodios) > len(recorte), "o original nao e alterado"


def test_narrativa_resume_as_frentes(dia):
    casado, projeto = dia
    texto = activity.narrative(activity.episodes(casado, project=projeto))
    assert texto.startswith("5h")
    assert "estacas 114 e 153" in texto


def test_narrativa_curta_cabe_no_telegram(dia):
    casado, projeto = dia
    curta = activity.narrative(activity.episodes(casado, project=projeto), brief=True)
    assert curta.startswith("5h")
    assert "entre as estacas 68 e 164 m" in curta
    assert "a última frente de serviço" in curta
    assert len(curta) < 300, curta
