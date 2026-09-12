import zipfile

import pytest

from machine2pipe.config import config
from machine2pipe.geo import project_loader
from machine2pipe.geo.matching import SegmentMatcher
from machine2pipe.geo.stationing import chainage, offset, project_line, project_point

CRS = "EPSG:31982"

KML_SEM_EXTENDED_DATA = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark>
    <name>TR-09</name>
    <description>diameter_mm: 600&lt;br&gt;material: PVC&lt;br&gt;planned_length_m: 250</description>
    <LineString><coordinates>-51.1,-26.6,0 -51.099,-26.6,0</coordinates></LineString>
  </Placemark>
</Document></kml>
"""


@pytest.fixture(scope="module")
def projeto():
    return project_loader.load(config.project_kml_path, config.segments_csv_path)


def test_le_trechos_estruturas_e_atributos(projeto):
    assert len(projeto.segments) == 7
    assert len(projeto.structures) == 8
    trecho = projeto.segment("TR-04")
    assert trecho.attributes["material"] == "concrete"
    assert trecho.attributes["diameter_mm"] == 400.0  # convertido, nao string


def test_atributos_saem_da_descricao_quando_nao_ha_extended_data(tmp_path):
    caminho = tmp_path / "earth_web.kml"
    caminho.write_text(KML_SEM_EXTENDED_DATA, encoding="utf-8")
    projeto = project_loader.load(caminho)
    trecho = projeto.segment("TR-09")
    assert trecho.attributes["material"] == "PVC"
    assert trecho.attributes["diameter_mm"] == 600.0


def test_le_kmz(tmp_path):
    caminho = tmp_path / "projeto.kmz"
    with zipfile.ZipFile(caminho, "w") as arquivo:
        arquivo.writestr("doc.kml", KML_SEM_EXTENDED_DATA)
    assert project_loader.load(caminho).segment("TR-09") is not None


def test_arquivo_sem_linha_falha_visivelmente(tmp_path):
    caminho = tmp_path / "vazio.kml"
    caminho.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')
    with pytest.raises(project_loader.ProjectError, match="LineString"):
        project_loader.load(caminho)


def test_estaca_e_distancia_ao_eixo_em_metros():
    # Um grau de longitude em -26,6 de latitude vale cerca de 99,5 km.
    linha = project_line([(-51.100, -26.600), (-51.000, -26.600)], CRS)
    assert linha.length == pytest.approx(9_950, rel=0.01)

    meio = project_point(-26.600, -51.050, CRS)
    assert offset(linha, meio) == pytest.approx(0, abs=1.0)
    assert chainage(linha, meio) == pytest.approx(linha.length / 2, rel=0.01)


def test_ponto_fora_do_corredor_nao_e_atribuido_ao_projeto(projeto):
    matcher = SegmentMatcher(projeto, CRS, corridor_m=25)
    trecho = projeto.segments[0]
    sobre_o_eixo = matcher.match(trecho.coordinates[0][1], trecho.coordinates[0][0])
    assert sobre_o_eixo.inside_corridor
    assert sobre_o_eixo.distance_to_axis_m < 1

    longe = matcher.match(-26.0, -51.0)
    assert longe.outside_project
    assert longe.distance_to_axis_m > 25


def test_corredor_e_configuravel(projeto):
    trecho = projeto.segments[0]
    latitude, longitude = trecho.coordinates[0][1], trecho.coordinates[0][0]
    apertado = SegmentMatcher(projeto, CRS, corridor_m=0.1).match(latitude, longitude)
    largo = SegmentMatcher(projeto, CRS, corridor_m=5000).match(latitude, longitude)
    assert largo.inside_corridor
    assert apertado.distance_to_axis_m == largo.distance_to_axis_m  # a medida nao muda
