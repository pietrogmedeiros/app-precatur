"""Elasticsearch da pré-análise: cria os índices, carrega o levantamento e mede.

    python scripts/elastic/precatur_es.py criar      # índices + aliases + data views do Kibana
    python scripts/elastic/precatur_es.py carregar   # levantamento + catálogo do app → palavras-chave
    python scripts/elastic/precatur_es.py relatorio  # precisão real de cada marcador e acerto dos cortes

Lê ELASTIC_URL, ELASTIC_USER (padrão "elastic"), ELASTIC_PASSWORD ou
ELASTIC_API_KEY, ELASTIC_VERIFY_TLS e KIBANA_URL do ambiente ou do `.env` da
raiz. `LEVANTAMENTO_DIR` aponta para a pasta do levantamento (padrão
`../levantamento_palavras_chave`, ao lado do repo): o `palavras_chave.jsonl` NÃO
é versionado, porque traz nomes de partes e advogados vindos dos índices dos PDFs.

Cada índice é `<alias>-v1` atrás de um alias: para mudar o mapping, crie a v2,
reindexe e troque o alias, sem parar a telemetria. Tudo aqui é idempotente.
Só stdlib: roda em qualquer python 3.10+.
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent

INDICES = {  # alias → arquivo de mapping
    "precatur-palavras-chave": "palavras_chave.mapping.json",
    "precatur-pre-analises": "pre_analises.mapping.json",
    "precatur-pre-analises-paginas": "pre_analises_paginas.mapping.json",
}
DATA_VIEWS = {  # id → (padrão, campo de tempo, nome)
    "precatur-palavras-chave": ("precatur-palavras-chave", None, "Palavras-chave (levantamento + app)"),
    "precatur-pre-analises": ("precatur-pre-analises", "@timestamp", "Pré-análises"),
    "precatur-pre-analises-paginas": ("precatur-pre-analises-paginas", "@timestamp", "Pré-análises · páginas"),
}


def _env() -> dict:
    """Ambiente + `.env` da raiz (aceita `CHAVE=valor` e `CHAVE:valor`)."""
    out = {}
    arq = RAIZ / ".env"
    if arq.exists():
        for linha in arq.read_text().splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            sep = min((i for i in (linha.find("="), linha.find(":")) if i > 0), default=-1)
            if sep > 0:
                out[linha[:sep].strip()] = linha[sep + 1:].strip().strip('"').strip("'")
    out.update({k: v for k, v in os.environ.items() if k.startswith(("ELASTIC_", "KIBANA_", "LEVANTAMENTO_"))})
    return out


ENV = _env()


def _pedir(base: str, metodo: str, caminho: str, corpo=None, ndjson=False, kibana=False):
    url = base.rstrip("/") + caminho
    dados = None
    cab = {"Content-Type": "application/x-ndjson" if ndjson else "application/json"}
    if kibana:
        cab["kbn-xsrf"] = "true"
    if corpo is not None:
        dados = corpo.encode() if isinstance(corpo, str) else json.dumps(corpo).encode()
    if ENV.get("ELASTIC_API_KEY"):
        cab["Authorization"] = f"ApiKey {ENV['ELASTIC_API_KEY']}"
    elif ENV.get("ELASTIC_PASSWORD"):
        tok = f"{ENV.get('ELASTIC_USER') or 'elastic'}:{ENV['ELASTIC_PASSWORD']}"
        cab["Authorization"] = "Basic " + base64.b64encode(tok.encode()).decode()
    ctx = None
    try:  # o python.org no macOS vem sem CA raiz; o certifi resolve quando existe
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if (ENV.get("ELASTIC_VERIFY_TLS") or "1").lower() in ("0", "false", "off"):
        ctx = ssl._create_unverified_context()  # noqa: S323 — só com certificado autoassinado
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except json.JSONDecodeError:
            return e.code, {"erro": txt[:500]}


def es(metodo, caminho, corpo=None, ndjson=False):
    if not ENV.get("ELASTIC_URL"):
        sys.exit("Defina ELASTIC_URL (ambiente ou .env).")
    return _pedir(ENV["ELASTIC_URL"], metodo, caminho, corpo, ndjson)


# ── criar ────────────────────────────────────────────────────────────────
def criar() -> None:
    for alias, arq in INDICES.items():
        st, _ = es("HEAD", f"/_alias/{alias}")
        if st == 200:
            print(f"= {alias}: já existe")
            continue
        indice = f"{alias}-v1"
        mapping = json.loads((AQUI / arq).read_text())
        mapping["aliases"] = {alias: {"is_write_index": True}}
        st, r = es("PUT", f"/{indice}", mapping)
        print(f"{'+' if st == 200 else '!'} {indice} → {alias}: {st} {'' if st == 200 else r}")
    kib = ENV.get("KIBANA_URL")
    if not kib:
        print("(sem KIBANA_URL: data views não criadas)")
        return
    for id_, (padrao, tempo, nome) in DATA_VIEWS.items():
        dv = {"id": id_, "title": padrao, "name": nome}
        if tempo:
            dv["timeFieldName"] = tempo
        st, r = _pedir(kib, "POST", "/api/data_views/data_view", {"data_view": dv, "override": True},
                       kibana=True)
        print(f"{'+' if st == 200 else '!'} data view {nome}: {st} {'' if st == 200 else r}")


# ── carregar ─────────────────────────────────────────────────────────────
def _bulk(alias: str, docs: list[dict]) -> None:
    for i in range(0, len(docs), 500):
        lote = docs[i:i + 500]
        corpo = "".join(json.dumps({"index": {"_index": alias, "_id": d["id"]}}) + "\n"
                        + json.dumps(d, ensure_ascii=False) + "\n" for d in lote)
        st, r = es("POST", "/_bulk?refresh=wait_for", corpo, ndjson=True)
        erros = [it["index"]["error"] for it in r.get("items", []) if it["index"].get("error")]
        print(f"  {len(lote) - len(erros)}/{len(lote)} ok" + (f" · 1º erro: {erros[0]}" if erros else ""))


def carregar() -> None:
    pasta = Path(ENV.get("LEVANTAMENTO_DIR") or RAIZ.parent / "levantamento_palavras_chave")
    arq = pasta / "palavras_chave.jsonl"
    if arq.exists():
        docs = [json.loads(l) for l in arq.read_text().splitlines() if l.strip()]
        print(f"levantamento: {len(docs)} documentos de {arq}")
        _bulk("precatur-palavras-chave", docs)
    else:
        print(f"! {arq} não encontrado (defina LEVANTAMENTO_DIR); seguindo só com o catálogo do app")
    sys.path.insert(0, str(RAIZ / "calculadora"))
    from prefill import marcadores  # noqa: E402 — só regex, sem PyMuPDF

    cat = marcadores.catalogo()
    from datetime import date
    for d in cat:
        d["atualizado_em"] = date.today().isoformat()
    print(f"catálogo do app: {len(cat)} marcadores (status=ativo_no_app)")
    _bulk("precatur-palavras-chave", cat)


# ── relatório: o laço de melhoria ────────────────────────────────────────
def relatorio() -> None:
    """Precisão por marcador = páginas em que disparou e o advogado confirmou o
    mesmo tipo / páginas em que disparou. Sai do índice de páginas, ou seja,
    do uso real — não do corpus de agosto."""
    st, r = es("POST", "/precatur-pre-analises-paginas/_search", {
        "size": 0,
        "aggs": {"m": {"terms": {"field": "marcadores", "size": 200},
                       "aggs": {"conf": {"terms": {"field": "tipo_confirmado", "size": 10}}}},
                 "cls": {"terms": {"field": "nivel", "size": 10, "missing": "indefinido"},
                         "aggs": {"ok": {"terms": {"field": "classificador_acertou"}}}}}})
    if st != 200:
        sys.exit(f"busca falhou: {st} {r}")
    total = r["hits"]["total"]["value"]
    print(f"páginas confirmadas no índice: {total}\n")
    print(f"{'marcador':78} {'disparos':>8} {'conta':>6} {'ofício':>6} {'outro':>6}")
    for b in r["aggregations"]["m"]["buckets"]:
        c = {x["key"]: x["doc_count"] for x in b["conf"]["buckets"]}
        print(f"{b['key'][:78]:78} {b['doc_count']:8} {c.get('conta', 0):6} {c.get('oficio', 0):6} "
              f"{c.get('outro', 0):6}")
    print("\nacerto do classificador por nível de decisão:")
    for b in r["aggregations"]["cls"]["buckets"]:
        ok = {str(x["key_as_string"] if "key_as_string" in x else x["key"]): x["doc_count"]
              for x in b["ok"]["buckets"]}
        acertos = ok.get("true", 0)
        print(f"  {b['key']:16} {acertos}/{b['doc_count']} ({acertos / b['doc_count']:.0%})")

    st, r = es("POST", "/precatur-pre-analises/_search", {
        "size": 0, "query": {"exists": {"field": "avaliacao"}},
        "aggs": {t: {"terms": {"field": f"avaliacao.{t}.status"}} for t in ("conta", "oficio")}})
    if st == 200:
        print(f"\ncortes avaliados: {r['hits']['total']['value']} pré-análises confirmadas")
        for t in ("conta", "oficio"):
            print(f"  {t:7} " + ", ".join(f"{b['key']}={b['doc_count']}"
                                         for b in r["aggregations"][t]["buckets"]))


if __name__ == "__main__":
    acoes = {"criar": criar, "carregar": carregar, "relatorio": relatorio}
    if len(sys.argv) < 2 or sys.argv[1] not in acoes:
        sys.exit(__doc__)
    acoes[sys.argv[1]]()
