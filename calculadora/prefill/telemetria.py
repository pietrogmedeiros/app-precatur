"""Telemetria da pré-análise → Elasticsearch: o que o sistema SUGERIU, o que o
advogado CONFIRMOU e o que a extração entregou. É o gabarito que se acumula
sozinho, a cada uso, para medir e melhorar os marcadores (`marcadores`).

Dois índices (aliases; o mapping está em `scripts/elastic/`):

  precatur-pre-analises          um documento por análise (id = sessão). Nasce
                                 no `analisar` (sugestão) e é completado no
                                 `extrair-cortes` (confirmação + avaliação +
                                 campos) e no envio ao CRM (valor final).
  precatur-pre-analises-paginas  um documento por página relevante, com os
                                 marcadores que dispararam, o tipo sugerido e
                                 o tipo que o advogado confirmou. É dele que
                                 sai a precisão real de cada marcador.

⚠ PII: o repositório é "sem banco, por desenho" para não deixar o processo
parado em disco. Por isso aqui NÃO vai texto, nome, CPF nem valor: só tipo,
página, ids de marcador, contagens e booleanos. O número CNJ e o PDF entram
como hash (junta análises do mesmo processo sem guardar o número). A única
exceção é opcional e desligada por padrão: `ELASTIC_GUARDAR_CABECALHO=1` grava
as 3 primeiras linhas das páginas confirmadas, para minerar termo novo.

Nunca derruba nem atrasa a análise: sem `ELASTIC_URL` é no-op; com ela, os
documentos vão por uma fila e uma thread de fundo, e erro de rede só vira log.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import sys
import threading
from collections import Counter
from datetime import datetime, timezone

from . import marcadores as M

IDX_ANALISES = "precatur-pre-analises"
IDX_PAGINAS = "precatur-pre-analises-paginas"
VERSAO = "2026-10-28b"   # muda quando a lógica de sugestão muda: separa as medições
MAX_PAGINAS_DOCS = 400
_FILA_MAX = 2000

_TIPOS = {"Conta homologada": M.CONTA, "Ofício requisitório": M.OFICIO,
          "Sentença / acórdão": M.SENTENCA}

# CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO — J.TR identifica o tribunal
_RE_CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.(\d)\.(\d{2})\.\d{4}\b")
_UF_TJ = ["AC", "AL", "AP", "AM", "BA", "CE", "DFT", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
          "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SE", "SP", "TO"]
_JUSTICA = {"8": "estadual", "4": "federal", "5": "trabalho"}


def habilitada() -> bool:
    return bool(os.environ.get("ELASTIC_URL")) and \
        (os.environ.get("ELASTIC_TELEMETRIA") or "1").lower() not in ("0", "false", "off", "nao")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(b: bytes | str | None) -> str | None:
    if not b:
        return None
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


# ── envio em segundo plano ───────────────────────────────────────────────
_fila: queue.Queue = queue.Queue(maxsize=_FILA_MAX)
_trava = threading.Lock()
_thread: threading.Thread | None = None


def _cliente():
    import httpx
    auth = None
    headers = {"Content-Type": "application/x-ndjson"}
    if os.environ.get("ELASTIC_API_KEY"):
        headers["Authorization"] = f"ApiKey {os.environ['ELASTIC_API_KEY']}"
    elif os.environ.get("ELASTIC_USER"):
        auth = (os.environ["ELASTIC_USER"], os.environ.get("ELASTIC_PASSWORD") or "")
    verificar = (os.environ.get("ELASTIC_VERIFY_TLS") or "1").lower() not in ("0", "false", "off")
    return httpx.Client(base_url=os.environ["ELASTIC_URL"].rstrip("/"), auth=auth,
                        headers=headers, verify=verificar, timeout=10.0)


def _trabalhar() -> None:
    cli = None
    while True:
        linhas = [_fila.get()]
        while len(linhas) < 500:  # junta o que já está na fila num _bulk só
            try:
                linhas.append(_fila.get_nowait())
            except queue.Empty:
                break
        corpo = "".join(json.dumps(x, ensure_ascii=False, default=str) + "\n"
                        for par in linhas for x in par)
        try:
            cli = cli or _cliente()
            r = cli.post("/_bulk", content=corpo.encode())
            if r.status_code >= 300 or r.json().get("errors"):
                print(f"[telemetria] bulk {r.status_code}: {r.text[:300]}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — telemetria nunca derruba nada
            print(f"[telemetria] {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            cli = None


def _enviar(pares: list[tuple[dict, dict]]) -> None:
    """pares = [(ação do _bulk, corpo)]. Fila cheia: descarta (e avisa)."""
    global _thread
    if not habilitada() or not pares:
        return
    with _trava:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_trabalhar, name="telemetria-es", daemon=True)
            _thread.start()
    for p in pares:
        try:
            _fila.put_nowait(p)
        except queue.Full:
            print("[telemetria] fila cheia: documento descartado", file=sys.stderr)
            return


def _indexar(indice: str, doc_id: str, doc: dict) -> tuple[dict, dict]:
    return ({"index": {"_index": indice, "_id": doc_id}}, doc)


def _upsert(indice: str, doc_id: str, doc: dict) -> tuple[dict, dict]:
    return ({"update": {"_index": indice, "_id": doc_id, "retry_on_conflict": 3}},
            {"doc": doc, "doc_as_upsert": True})


# ── sinais do processo (sem PII) ─────────────────────────────────────────
def sinais_processo(paginas: list[dict]) -> dict:
    """Tribunal (pelo CNJ mais citado), justiça e sistema processual."""
    cnjs: Counter = Counter()
    sistemas: Counter = Counter()
    for p in paginas:
        t = p.get("texto") or ""
        for m in _RE_CNJ.finditer(t):
            cnjs[(m.group(0), m.group(1), m.group(2))] += 1
        n = M.normalizar(t[-600:] + "\n" + t[:400])
        sis = M.rotulo_sistema(n)
        if sis:
            sistemas["eproc" if sis["sistema"] == "eproc" else "pje"] += 1
        elif re.search(r"num\. ?\d{9,11} ?- ?pag\. ?\d", n) or "pje" in n:
            sistemas["pje"] += 1
        elif "esaj" in n or "e-saj" in n:
            sistemas["esaj"] += 1
        elif "projudi" in n:
            sistemas["projudi"] += 1
    out = {"tribunal": None, "justica": None,
           "sistema_processual": sistemas.most_common(1)[0][0] if sistemas else "indeterminado",
           "cnj_hash": None}
    if cnjs:
        (num, j, tr), _ = cnjs.most_common(1)[0]
        out["cnj_hash"] = _hash(num)
        out["justica"] = _JUSTICA.get(j)
        if j == "8" and 1 <= int(tr) <= len(_UF_TJ):
            out["tribunal"] = "TJ" + _UF_TJ[int(tr) - 1]
        elif j == "4":
            out["tribunal"] = f"TRF{int(tr)}"
        elif j == "5":
            out["tribunal"] = f"TRT{int(tr)}"
    return out


def _corte(c: dict) -> dict:
    return {"tipo": _TIPOS.get(c.get("tipo"), "outro"), "pagina_inicio": c.get("pagina_inicio"),
            "pagina_fim": c.get("pagina_fim"), "origem": c.get("origem") or "radar",
            "n_paginas": (int(c.get("pagina_fim") or 0) - int(c.get("pagina_inicio") or 0) + 1)
            if c.get("pagina_inicio") else None}


def _campos(res: dict) -> list[dict]:
    """Só o que diz da QUALIDADE: de onde veio e se tinha citação; nunca o valor."""
    out = []
    for nome, d in (res.get("campos") or {}).items():
        d = d or {}
        cit = d.get("citacao") or {}
        out.append({"campo": nome, "fonte": d.get("fonte") or "llm",
                    "com_citacao": bool(cit.get("trecho")), "pagina": cit.get("pagina")
                    if isinstance(cit.get("pagina"), int) else None})
    return out


def _extracao(res: dict) -> dict:
    prova = res.get("prova") or {}
    return {
        "ok": bool(res.get("ok")), "erro": (res.get("erro") or "")[:300] or None,
        "campos": _campos(res),
        "n_campos": len(res.get("campos") or {}),
        "rejeitados": [r.get("campo") for r in res.get("rejeitados") or []],
        "conflitos": [c.get("campo") for c in res.get("conflitos") or []],
        "alertas": [a.get("tipo") for a in res.get("alertas_pje") or []],
        "prova_ok": prova.get("ok"), "prova_dif_pct": prova.get("dif_pct"),
        "multi_conta": res.get("multi_conta"), "multi_oficio": res.get("multi_oficio"),
        "custo_usd": res.get("custo"),
    }


# ── pontos de registro ───────────────────────────────────────────────────
def registrar_analise(sessao: str, pdf: bytes | None, res: dict) -> None:
    """Passo 1 (`/documentos/analisar`): o que o sistema sugeriu, sem LLM."""
    if not habilitada():
        return
    try:
        paginas = res.get("paginas") or []
        pj = res.get("pje") or {}
        homol = res.get("homologacao") or {}
        sug = [_corte(c) for c in res.get("cortes_sugeridos") or []]
        doc = {
            "@timestamp": _agora(), "analise_id": sessao, "modo": "assistido",
            "versao": VERSAO, "pdf_hash": _hash(pdf),
            "processo": {**sinais_processo(paginas), "n_paginas": res.get("n_paginas"),
                         "escaneadas": res.get("escaneadas")},
            "sugestao": {
                "cortes": sug,
                "tem_conta": any(c["tipo"] == M.CONTA for c in sug),
                "tem_oficio": any(c["tipo"] == M.OFICIO for c in sug),
                "n_faixas_radar": len((res.get("radar") or {}).get("runs") or []),
            },
            "pje": {"ativo": bool(pj), "paginas_mapeadas": pj.get("paginas_mapeadas"),
                    "achou_conta": bool(pj.get("conta")),
                    "conta_votos": (pj.get("conta") or {}).get("votos"),
                    "conta_ancora": bool((pj.get("conta") or {}).get("ancora")),
                    "n_oficios": len(pj.get("oficios") or []),
                    "alertas": [a.get("tipo") for a in pj.get("alertas") or []]},
            "homologacao": {"achou": bool(homol), "pagina": homol.get("pagina"),
                            "tem_evento": bool(homol.get("evento"))},
        }
        _enviar([_indexar(IDX_ANALISES, sessao, doc)])
    except Exception as e:  # noqa: BLE001
        print(f"[telemetria] analise: {type(e).__name__}: {e}", file=sys.stderr)


def _tipo_na_pagina(cortes: list[dict], pg: int) -> tuple[str | None, str | None]:
    for c in cortes:
        try:
            if int(c["pagina_inicio"]) <= pg <= int(c["pagina_fim"]):
                return _TIPOS.get(c.get("tipo"), "outro"), c.get("origem") or "radar"
        except (KeyError, TypeError, ValueError):
            continue
    return None, None


def avaliar(sugeridos: list[dict], confirmados: list[dict]) -> dict:
    """Por tipo: o 1º corte sugerido × o 1º confirmado (é o que a extração usa)."""
    out = {}
    for tipo in (M.CONTA, M.OFICIO):
        s = next((c for c in sugeridos if _TIPOS.get(c.get("tipo")) == tipo), None)
        c = next((c for c in confirmados if _TIPOS.get(c.get("tipo")) == tipo), None)
        if not s and not c:
            out[tipo] = {"status": "ausente"}
            continue
        if not c:
            out[tipo] = {"status": "falso_positivo", "origem": s.get("origem") or "radar"}
            continue
        if not s:
            out[tipo] = {"status": "nao_sugerido"}
            continue
        sa, sb = int(s["pagina_inicio"]), int(s["pagina_fim"])
        ca, cb = int(c["pagina_inicio"]), int(c["pagina_fim"])
        inter = max(0, min(sb, cb) - max(sa, ca) + 1)
        uniao = max(sb, cb) - min(sa, ca) + 1
        iou = round(inter / uniao, 3) if uniao else 0.0
        status = "exato" if (sa, sb) == (ca, cb) else "parcial" if inter else "errado"
        out[tipo] = {"status": status, "iou": iou, "origem": s.get("origem") or "radar",
                     "acertou": status == "exato" or iou >= 0.5,
                     "desvio_inicio": ca - sa, "desvio_fim": cb - sb}
    return out


def registrar_confirmacao(sessao: str, paginas: list[dict], sugeridos: list[dict],
                          confirmados: list[dict], res: dict) -> None:
    """Passo 2 (`/documentos/extrair-cortes`): o gabarito do advogado."""
    if not habilitada():
        return
    try:
        aval = avaliar(sugeridos or [], confirmados or [])
        pares = [_upsert(IDX_ANALISES, sessao, {
            "confirmado_em": _agora(),
            "confirmacao": {"cortes": [_corte(c) for c in confirmados or []]},
            "avaliacao": aval,
            "extracao": _extracao(res),
        })]
        proc = sinais_processo(paginas)
        cabecalho = (os.environ.get("ELASTIC_GUARDAR_CABECALHO") or "").lower() in ("1", "true", "sim")
        docs = []
        for p in paginas:
            pg = p.get("pagina")
            texto = p.get("texto") or ""
            cls = M.classificar(texto)
            t_sug, origem = _tipo_na_pagina(sugeridos or [], pg)
            t_conf, _ = _tipo_na_pagina(confirmados or [], pg)
            if not (cls["tipo"] or (t_sug and t_sug != "outro") or t_conf):
                continue
            doc = {
                "@timestamp": _agora(), "analise_id": sessao, "versao": VERSAO, "pagina": pg,
                "tribunal": proc["tribunal"], "justica": proc["justica"],
                "sistema_processual": proc["sistema_processual"],
                "nativa": bool(p.get("nativa")), "n_caracteres": len(texto),
                "n_valores": len(M._VALOR.findall(texto)),
                "oraculo_razao": (p.get("oraculo") or {}).get("razao"),
                "tipo_classificador": cls["tipo"] or "indefinido", "nivel": cls["nivel"],
                "marcadores": cls["marcadores"], "provisorio": cls["provisorio"],
                "rotulo_sistema": (cls["sistema"] or {}).get("rotulo"),
                "tipo_sugerido": t_sug or "nenhum", "origem_sugestao": origem,
                "tipo_confirmado": t_conf or "outro",
                "classificador_acertou": (cls["tipo"] or "outro") == (t_conf or "outro"),
            }
            if cabecalho and t_conf:
                doc["cabecalho"] = [ln.strip() for ln in texto.splitlines() if ln.strip()][:3]
            docs.append(_indexar(IDX_PAGINAS, f"{sessao}:{pg}", doc))
            if len(docs) >= MAX_PAGINAS_DOCS:
                break
        _enviar(pares + docs)
    except Exception as e:  # noqa: BLE001
        print(f"[telemetria] confirmacao: {type(e).__name__}: {e}", file=sys.stderr)


def registrar_extracao_direta(sessao: str, modo: str, paginas: list[dict], pdf: bytes | None,
                              res: dict, pecas: list[str] | None = None) -> None:
    """`extrair-pecas` (peças já cortadas) e `preencher` (autônomo)."""
    if not habilitada():
        return
    try:
        if not paginas:  # a rota não tem o substrato: lê o texto nativo das pontas do PDF
            paginas = _paginas_das_pontas(pdf)
            num = ((res.get("campos") or {}).get("numero_precatorio") or {}).get("valor")
            if num:
                paginas.append({"texto": str(num)})
        doc = {"@timestamp": _agora(), "analise_id": sessao, "modo": modo, "versao": VERSAO,
               "pdf_hash": _hash(pdf), "pecas": pecas or [],
               "processo": {**sinais_processo(paginas), "n_paginas": res.get("paginas"),
                            "escaneadas": res.get("escaneadas")},
               "extracao": _extracao(res)}
        _enviar([_indexar(IDX_ANALISES, sessao, doc)])
    except Exception as e:  # noqa: BLE001
        print(f"[telemetria] extracao: {type(e).__name__}: {e}", file=sys.stderr)


def _paginas_das_pontas(pdf: bytes | None, n: int = 12) -> list[dict]:
    """Texto nativo das primeiras e últimas páginas: é onde estão o número CNJ
    (capa, índice) e o carimbo do sistema. Sem OCR, sem guardar nada — só para
    `sinais_processo` achar o tribunal no modo autônomo e no de peças."""
    if not pdf:
        return []
    try:
        import fitz
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            idx = sorted(set(range(min(n, doc.page_count))) |
                         set(range(max(0, doc.page_count - n // 2), doc.page_count)))
            return [{"texto": doc[i].get_text()} for i in idx]
    except Exception:  # noqa: BLE001
        return []


def _igual(a, b) -> bool:
    return re.sub(r"\W", "", str(a or "")).lower() == re.sub(r"\W", "", str(b or "")).lower()


def registrar_envio(sessao: str, extraido: dict, final: dict) -> None:
    """Envio ao CRM: o que o advogado MANDOU × o que a pré-análise tinha
    extraído. Grava só se bateu (bool) — nunca o valor."""
    if not habilitada() or not sessao:
        return
    try:
        comparados = {}
        for campo, v in final.items():
            if v in (None, ""):
                continue
            e = (extraido or {}).get(campo)
            comparados[campo] = {"extraido": e is not None, "igual": e is not None and _igual(e, v)}
        _enviar([_upsert(IDX_ANALISES, sessao, {"enviado_em": _agora(),
                                                 "envio": {"campos": comparados}})])
    except Exception as e:  # noqa: BLE001
        print(f"[telemetria] envio: {type(e).__name__}: {e}", file=sys.stderr)
