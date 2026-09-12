# Projeto real da demonstração

`calmon_jit_machine2pipe-ai.kml` é o arquivo original exportado por Caio Zanetti do
projeto público do Google Earth. Ele contém o eixo `tubo_concreto_40` e os pontos
`posto_gasolina`, `canteiro`, `jazida_solo` e `bueiro_triplo`.

O KML é preservado sem alterações. `segments.csv` acrescenta os atributos estruturados
que o Google Earth Web não incluiu no export: DN400, concreto, execução em 28/06/2022 e
comprimento geométrico de 255,06 m calculado em EPSG:31982.

Para usar este projeto no Railway:

```text
PROJECT_KML_PATH=data/project/calmon_jit_machine2pipe-ai.kml
SEGMENTS_CSV_PATH=data/project/segments.csv
```

O arquivo provisório em `data/sample/` não é fonte válida para a demonstração real.
