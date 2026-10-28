"""Dashboard "Pré-análise · Inteligência" no Kibana (gerado, idempotente).

    calculadora/.venv/bin/python scripts/elastic/dashboard_kibana.py

Painéis em Vega-Lite: cada um consulta o Elasticsearch direto e respeita o
período e os filtros do dashboard (`%dashboard_context-*%`, `%timefilter%`).
Vega em vez de Lens porque o JSON do Lens muda entre versões do Kibana e o do
Vega é a própria consulta, legível e estável. Reimportar sobrescreve.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import precatur_es as ES  # noqa: E402

AVAL = "precatur-avaliacao-paginas"
USO = "precatur-pre-analises"
USO_PAG = "precatur-pre-analises-paginas"
PALAVRAS = "precatur-palavras-chave"

CORES_TIPO = {"domain": ["conta", "oficio", "sentenca", "outro", "indefinido", "nenhum"],
              "range": ["#2f6fdf", "#e0a100", "#7a5af8", "#9aa4b2", "#c9ced6", "#e5e7eb"]}
CORES_SN = {"domain": ["true", "false"], "range": ["#2e9e5b", "#d64545"]}


def _consulta(tempo: bool, filtros: list[str]) -> dict:
    must = ["%dashboard_context-must_clause%"]
    if tempo:
        must.append({"range": {"@timestamp": {"%timefilter%": True}}})
    must += [{"query_string": {"query": f}} for f in filtros]
    return {"bool": {"must": must, "filter": ["%dashboard_context-filter_clause%"],
                     "must_not": ["%dashboard_context-must_not_clause%"]}}


def _spec(titulo: str, dados: dict, transform: list, mark, encoding: dict, extra=None) -> dict:
    s = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json",
         "title": {"text": titulo, "anchor": "start", "fontSize": 13},
         "data": dados, "transform": transform, "mark": mark, "encoding": encoding,
         "config": {"axis": {"labelLimit": 260}, "legend": {"orient": "bottom"}}}
    if extra:
        s.update(extra)
    return s


def barras(titulo, indice, x, cor=None, filtros=(), tempo=True, n=15, horizontal=False,
           normalizar=False, escala=None, rotulo_x=None, faltando=None):
    """Contagem por `x` (terms), opcionalmente quebrada por `cor` (terms)."""
    aggs = {"x": {"terms": {"field": x, "size": n}}}
    if cor:
        aggs["x"]["aggs"] = {"c": {"terms": {"field": cor, "size": 12}}}
        if faltando:  # só em keyword: campo booleano recusa um "missing" de texto
            aggs["x"]["aggs"]["c"]["terms"]["missing"] = faltando
    dados = {"url": {"index": indice, "body": {"size": 0, "query": _consulta(tempo, list(filtros)),
                                                "aggs": aggs}},
             "format": {"property": "aggregations.x.buckets"}}
    tr = [{"calculate": "datum.key_as_string || datum.key", "as": "x"}]
    if cor:
        tr = [{"flatten": ["c.buckets"], "as": ["s"]},
              {"calculate": "datum.key_as_string || datum.key", "as": "x"},
              {"calculate": "datum.s.key_as_string || datum.s.key", "as": "cor"},
              {"calculate": "datum.s.doc_count", "as": "n"}]
    else:
        tr.append({"calculate": "datum.doc_count", "as": "n"})
    eixo_n = {"field": "n", "type": "quantitative", "title": "% das páginas" if normalizar else "páginas",
              "stack": "normalize" if normalizar else "zero"}
    if normalizar:
        eixo_n["axis"] = {"format": "%"}
    eixo_x = {"field": "x", "type": "nominal", "title": rotulo_x or x, "sort": "-n" if not cor else None}
    enc = {"x": eixo_n, "y": eixo_x} if horizontal else {"x": eixo_x, "y": eixo_n}
    enc["tooltip"] = [{"field": "x", "title": rotulo_x or x}, {"field": "n", "title": "páginas"}]
    if cor:
        enc["color"] = {"field": "cor", "type": "nominal", "title": cor, "scale": escala or CORES_TIPO}
        enc["tooltip"].insert(1, {"field": "cor", "title": cor})
    return _spec(titulo, dados, tr, {"type": "bar", "tooltip": True}, enc)


def numero(titulo, indice, filtro_ok=None, tempo=True, sufixo="", base=()):
    """Um número grande: total do recorte, ou % que atende `filtro_ok`."""
    aggs = {}
    if filtro_ok:
        aggs["ok"] = {"filter": {"query_string": {"query": filtro_ok}}}
    dados = {"url": {"index": indice, "body": {"size": 0, "track_total_hits": True,
                                                "query": _consulta(tempo, list(base)), "aggs": aggs or {
                                                    "t": {"filter": {"match_all": {}}}}}},
             "format": {"property": "aggregations"}}
    if filtro_ok:
        texto = "datum.total > 0 ? format(datum.ok / datum.total, '.0%') : '—'"
        dados["url"]["body"]["aggs"]["total"] = {"filter": {"match_all": {}}}
        tr = [{"calculate": "datum.ok.doc_count", "as": "ok"},
              {"calculate": "datum.total.doc_count", "as": "total"},
              {"calculate": texto, "as": "rotulo"}]
    else:
        tr = [{"calculate": f"replace(format(datum.t.doc_count, ','), /,/g, '.') + '{sufixo}'", "as": "rotulo"}]
    return _spec(titulo, dados, tr,
                 {"type": "text", "fontSize": 44, "fontWeight": "bold", "color": "#2f6fdf"},
                 {"text": {"field": "rotulo", "type": "nominal"}})


def calor_cobertura() -> dict:
    """Levantamento: taxa de reconhecimento por tribunal × peça (cortes do advogado)."""
    aggs = {"x": {"terms": {"field": "tribunal", "size": 40},
                  "aggs": {"c": {"terms": {"field": "tipo_documento", "size": 6},
                                 "aggs": {"t": {"avg": {"field": "taxa"}}}}}}}
    dados = {"url": {"index": PALAVRAS, "body": {"size": 0, "query": _consulta(False, [
        "tipo_registro:cobertura AND evidencia.nivel:tribunal"]), "aggs": aggs}},
             "format": {"property": "aggregations.x.buckets"}}
    tr = [{"flatten": ["c.buckets"], "as": ["s"]},
          {"calculate": "datum.key", "as": "tribunal"},
          {"calculate": "datum.s.key", "as": "peca"},
          {"calculate": "datum.s.t.value", "as": "taxa"}]
    enc = {"x": {"field": "peca", "type": "nominal", "title": "peça"},
           "y": {"field": "tribunal", "type": "nominal", "title": None},
           "color": {"field": "taxa", "type": "quantitative", "title": "reconhecida",
                     "scale": {"domain": [0, 1], "range": ["#d64545", "#f2c94c", "#2e9e5b"]},
                     "legend": {"format": "%"}},
           "tooltip": [{"field": "tribunal"}, {"field": "peca"}, {"field": "taxa", "format": ".0%"}]}
    return _spec("Levantamento (232 casos): peça reconhecida por tribunal", dados, tr,
                 {"type": "rect", "tooltip": True}, enc)


MARKDOWN = """### Pré-análise · Inteligência

**Como ler.** *Avaliação Bitrix* = peças que o advogado anexou nos cards (conta, ofício, sentença) passadas pela regra nova, página a página: `tipo_confirmado` é o gabarito, `tipo_classificador` é o que a regra decidiu. *Uso real* = cada pré-análise feita no app (cresce sozinho). *Levantamento* = a medição de 28/10/2026 nos 232 casos.

**Onde agir.** Barra de outra cor no gráfico de uma peça = confusão. O painel *marcadores em página errada* diz qual palavra-chave causou. Sentença deveria ficar toda em "indefinido".

Fonte: `scripts/elastic/` · regras: `calculadora/prefill/marcadores.py`"""


def paineis() -> list[tuple[str, dict, tuple[int, int, int, int]]]:
    """(id, visualização, (x, y, w, h)) — grade de 48 colunas."""
    p = []
    md = {"title": "Como ler", "type": "markdown",
          "params": {"markdown": MARKDOWN, "fontSize": 11, "openLinksInNewTab": False}, "aggs": []}
    p.append(("precatur-md", md, (0, 0, 48, 7)))

    def vega(id_, spec, pos):
        p.append((id_, {"title": spec["title"]["text"], "type": "vega",
                        "params": {"spec": json.dumps(spec, ensure_ascii=False, indent=1)}, "aggs": []}, pos))

    # ── KPIs ──
    # "sem confusão" e não "acertou": numa peça de 10 páginas só a do formulário ou
    # da conta deve ganhar rótulo; as demais ficarem "indefinido" é o correto
    vega("precatur-kpi-acerto", numero("Avaliação: páginas sem confusão de tipo", AVAL,
                                       filtro_ok="NOT (classificador_acertou:false AND NOT tipo_classificador:indefinido)"),
         (0, 7, 12, 6))
    vega("precatur-kpi-paginas", numero("Avaliação: páginas lidas", AVAL), (12, 7, 12, 6))
    vega("precatur-kpi-uso", numero("Pré-análises reais no período", USO), (24, 7, 12, 6))
    vega("precatur-kpi-marcadores", numero("Marcadores ativos no app", PALAVRAS, tempo=False,
                                           base=["status:ativo_no_app"]), (36, 7, 12, 6))
    # ── avaliação Bitrix ──
    vega("precatur-aval-matriz", barras("Avaliação: o que a regra decide em cada peça", AVAL,
                                        "tipo_confirmado", "tipo_classificador", normalizar=True,
                                        rotulo_x="peça (gabarito)"), (0, 13, 16, 14))
    vega("precatur-aval-nivel", barras("Avaliação: acerto por nível de decisão", AVAL, "nivel",
                                       "classificador_acertou", normalizar=True, escala=CORES_SN,
                                       rotulo_x="nível"), (16, 13, 16, 14))
    vega("precatur-aval-erros", barras("Marcadores em página errada (top 20)", AVAL, "marcadores",
                                       filtros=["classificador_acertou:false AND NOT tipo_classificador:indefinido"],
                                       n=20, horizontal=True, rotulo_x="marcador"), (32, 13, 16, 14))
    for i, (peca, nome) in enumerate((("oficio", "Ofício"), ("conta", "Cálculo homologado"),
                                      ("sentenca", "Sentença (deveria ser indefinido)"))):
        vega(f"precatur-aval-{peca}", barras(f"{nome}: decisão da regra por tribunal", AVAL, "tribunal",
                                             "tipo_classificador", filtros=[f"tipo_confirmado:{peca}"],
                                             normalizar=True, rotulo_x="tribunal"), (16 * i, 27, 16, 14))
    vega("precatur-aval-precisao", barras("Precisão por marcador: em que peça ele dispara", AVAL,
                                          "marcadores", "tipo_confirmado", n=35, horizontal=True,
                                          normalizar=True, rotulo_x="marcador"), (0, 41, 48, 20))
    # ── uso real ──
    vega("precatur-uso-modo", barras("Uso real: pré-análises por modo", USO, "modo", "processo.tribunal",
                                     rotulo_x="modo"), (0, 61, 16, 12))
    vega("precatur-uso-conta", barras("Uso real: corte da CONTA sugerido × confirmado", USO,
                                      "processo.tribunal", "avaliacao.conta.status", normalizar=True,
                                      rotulo_x="tribunal", faltando="(vazio)",
                                      escala={"domain": ["exato", "parcial", "errado", "nao_sugerido",
                                                         "falso_positivo", "ausente", "(vazio)"],
                                              "range": ["#2e9e5b", "#9bd3a8", "#d64545", "#e0a100",
                                                        "#f28b82", "#c9ced6", "#e5e7eb"]}), (16, 61, 16, 12))
    vega("precatur-uso-oficio", barras("Uso real: corte do OFÍCIO sugerido × confirmado", USO,
                                       "processo.tribunal", "avaliacao.oficio.status", normalizar=True,
                                       rotulo_x="tribunal", faltando="(vazio)",
                                       escala={"domain": ["exato", "parcial", "errado", "nao_sugerido",
                                                          "falso_positivo", "ausente", "(vazio)"],
                                               "range": ["#2e9e5b", "#9bd3a8", "#d64545", "#e0a100",
                                                         "#f28b82", "#c9ced6", "#e5e7eb"]}), (32, 61, 16, 12))
    vega("precatur-uso-campos", barras("Uso real: campos extraídos e de onde vieram", USO,
                                       "extracao.campos.campo", "extracao.campos.fonte", n=20,
                                       horizontal=True, rotulo_x="campo"), (0, 73, 24, 14))
    vega("precatur-uso-pag", barras("Uso real: páginas, classificador × confirmado", USO_PAG,
                                    "tipo_confirmado", "tipo_classificador", normalizar=True,
                                    rotulo_x="confirmado pelo advogado"), (24, 73, 24, 14))
    # ── levantamento ──
    vega("precatur-lev-calor", calor_cobertura(), (0, 87, 24, 26))
    vega("precatur-lev-candidatos", barras("Termos candidatos aguardando curadoria", PALAVRAS,
                                           "tipo_documento", "tribunal", tempo=False,
                                           filtros=["tipo_registro:termo_minerado AND status:candidato"],
                                           rotulo_x="peça"), (24, 87, 24, 13))
    vega("precatur-lev-papel", barras("Catálogo do app: marcadores por papel", PALAVRAS, "papel",
                                      "tipo_documento", tempo=False, filtros=["status:ativo_no_app"],
                                      rotulo_x="papel"), (24, 100, 24, 13))
    return p


def objetos() -> list[dict]:
    vazio = json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
    objs, painel, refs = [], [], []
    for i, (id_, vis, (x, y, w, h)) in enumerate(paineis(), 1):
        objs.append({"type": "visualization", "id": id_, "attributes": {
            "title": vis["title"], "visState": json.dumps(vis, ensure_ascii=False), "uiStateJSON": "{}",
            "description": "", "version": 1, "kibanaSavedObjectMeta": {"searchSourceJSON": vazio}},
            "references": []})
        painel.append({"type": "visualization", "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i)},
                       "panelIndex": str(i), "embeddableConfig": {}, "panelRefName": f"panel_{i}"})
        refs.append({"name": f"panel_{i}", "type": "visualization", "id": id_})
    objs.append({"type": "dashboard", "id": "precatur-pre-analise-inteligencia", "attributes": {
        "title": "Pré-análise · Inteligência", "description": "Avaliação nos anexos do Bitrix, uso real e levantamento de palavras-chave.",
        "panelsJSON": json.dumps(painel), "optionsJSON": json.dumps({"useMargins": True, "syncColors": True, "hidePanelTitles": False}),
        "timeRestore": True, "timeFrom": "now-30d", "timeTo": "now", "version": 1,
        "kibanaSavedObjectMeta": {"searchSourceJSON": vazio}}, "references": refs})
    return objs


def importar() -> None:
    import base64
    import urllib.request
    import uuid
    kib = ES.ENV.get("KIBANA_URL")
    if not kib:
        sys.exit("Defina KIBANA_URL.")
    nd = "\n".join(json.dumps(o, ensure_ascii=False) for o in objetos()) + "\n"
    limite = uuid.uuid4().hex
    corpo = (f"--{limite}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"d.ndjson\"\r\n"
             f"Content-Type: application/ndjson\r\n\r\n{nd}\r\n--{limite}--\r\n").encode()
    tok = base64.b64encode(f"{ES.ENV.get('ELASTIC_USER') or 'elastic'}:{ES.ENV['ELASTIC_PASSWORD']}".encode()).decode()
    req = urllib.request.Request(kib.rstrip("/") + "/api/saved_objects/_import?overwrite=true",
                                 data=corpo, method="POST", headers={
                                     "kbn-xsrf": "true", "Authorization": f"Basic {tok}",
                                     "Content-Type": f"multipart/form-data; boundary={limite}"})
    ctx = None
    try:
        import certifi
        import ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        res = json.loads(r.read().decode())
    print(f"importados: {res.get('successCount')} · sucesso: {res.get('success')}")
    for e in res.get("errors") or []:
        print("  !", e.get("id"), e.get("error"))
    print(f"{kib.rstrip('/')}/app/dashboards#/view/precatur-pre-analise-inteligencia")


if __name__ == "__main__":
    if "--specs" in sys.argv:  # só imprime os specs (para validar fora do Kibana)
        for id_, vis, _ in paineis():
            if vis["type"] == "vega":
                print(json.dumps({"id": id_, "spec": json.loads(vis["params"]["spec"])}, ensure_ascii=False))
    else:
        importar()
