"""Rotas de documentos: pré-análise, assistente de corte e prefill por PDF.

O fluxo do assistente tem DOIS passos (analisar → extrair) e o segundo precisa
do substrato do primeiro. No Streamlit isso morava no `session_state`; aqui mora
numa **sessão em memória, com validade**. Em disco não pode: o repositório é
"sem banco, por desenho" justamente para não deixar PII parada — e o PDF do
processo é o documento mais sensível que passa por aqui.
"""
from __future__ import annotations

import base64
import os
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/documentos", tags=["documentos"])

# Sessões: id → {"paginas", "meta", "pdfs", "citacoes", "mapa", "faixas", "expira"}.
#
# `faixas` = {"conta"|"oficio"|"sentenca": (a, b) ou [(a, b), ...]}: as páginas do processo que
# viraram cada peça. É o que o envio ao CRM recorta para anexar no card.
#
# `pdfs` é o que o VISUALIZADOR precisa: para desenhar a tarja amarela sobre o
# número, `prefill.viewer` abre o PDF de novo — texto extraído não vira imagem.
# Fica na memória com a mesma validade do resto (nunca em disco: é o documento
# mais sensível que passa por aqui), e some junto quando a sessão expira.
_SESSOES: dict[str, dict[str, Any]] = {}
_TRAVA = threading.Lock()
VALIDADE_S = int(os.environ.get("PREFILL_SESSAO_TTL") or 3600)
MAX_SESSOES = 20


def habilitado() -> bool:
    """O prefill é opcional: puxa PyMuPDF e uma chave de LLM. Sem a flag, a
    tela esconde a seção em vez de oferecer um botão que sempre falha."""
    return (os.environ.get("PREFILL_ENABLED") or "").lower() in ("1", "true", "on", "sim")


def _limpar() -> None:
    agora = time.time()
    mortas = [k for k, v in _SESSOES.items() if v["expira"] < agora]
    for k in mortas:
        _SESSOES.pop(k, None)
    # teto duro: a sessão guarda o substrato de um processo inteiro
    while len(_SESSOES) > MAX_SESSOES:
        mais_velha = min(_SESSOES, key=lambda k: _SESSOES[k]["expira"])
        _SESSOES.pop(mais_velha, None)


def _guardar(paginas: list[dict], meta: dict, pdfs: dict[str, bytes] | None = None) -> str:
    with _TRAVA:
        _limpar()
        sid = uuid.uuid4().hex
        _SESSOES[sid] = {"paginas": paginas, "meta": meta, "pdfs": pdfs or {},
                         "citacoes": {}, "mapa": {}, "expira": time.time() + VALIDADE_S}
        return sid


def _anotar_citacoes(sid: str, res: dict) -> None:
    """Guarda na sessão de onde cada valor saiu, para o visualizador depois.

    Silencioso de propósito: a extração já deu certo, e perder o visualizador
    (sessão expirada entre o envio e a leitura) não pode derrubar o resultado
    que o advogado tem na tela.
    """
    with _TRAVA:
        sessao = _SESSOES.get(sid)
        if sessao is None:
            return
        sessao["citacoes"] = res.get("citacoes") or {}
        sessao["mapa"] = res.get("mapa_paginas") or {}
        # o que a pré-análise extraiu, para o envio ao CRM medir se o advogado
        # manteve (telemetria grava só o "bateu?", nunca o valor)
        sessao["extraido"] = {k: (v or {}).get("valor") for k, v in (res.get("campos") or {}).items()}


def _anotar_faixas(sid: str, faixas: dict) -> None:
    with _TRAVA:
        sessao = _SESSOES.get(sid)
        if sessao is not None:
            sessao["faixas"] = {k: v for k, v in faixas.items() if v}


def _telemetria():
    """Import tardio: telemetria é melhoria, e não pode derrubar a rota."""
    try:
        from prefill import telemetria
        return telemetria
    except Exception:  # noqa: BLE001
        return None


def _recuperar(sid: str) -> dict:
    with _TRAVA:
        _limpar()
        sessao = _SESSOES.get(sid)
    if not sessao:
        raise HTTPException(status_code=410, detail=(
            "A análise expirou (ou o serviço reiniciou). Envie o PDF de novo."))
    return sessao


# Rótulo da peça quando o PDF é o processo inteiro (modos "autônomo" e
# "assistente de corte"): lá a página citada é a página do próprio arquivo, não
# há concatenação para desfazer.
PECA_PROCESSO = "Processo"


def _descartar_conflito_de_grafia(res: dict) -> None:
    """Tira da lista o "conflito" em que os dois lados dizem o MESMO número.

    O motor compara IA × regex normalizando com `rstrip("0")`, que em número
    INTEIRO come o zero final: `"30"` vira `"3"` e nunca casa com o `"30,00"`
    que o regex lê do formulário. Enquanto a tela nova não mostrava conflito
    nenhum isso passava despercebido; agora todo honorário de 10, 20 ou 30%
    viraria um alarme falso — e alarme falso é o que faz o advogado parar de
    ler os verdadeiros.

    Fica aqui, e não no motor, pela mesma regra de sempre: `prefill/` é código
    de origem. A correção precisa ser replicada lá para a tela do Victor.
    """
    from decimal import Decimal, InvalidOperation

    def num(v):
        try:
            return Decimal(str(v).strip().replace("%", "").replace(".", "").replace(",", ".")
                           if "," in str(v) else str(v).strip().replace("%", ""))
        except (InvalidOperation, ValueError):
            return None

    restantes = []
    for c in res.get("conflitos") or []:
        a, b = num(c.get("llm")), num(c.get("regex"))
        if a is None or b is None or a != b:
            restantes.append(c)
    res["conflitos"] = restantes


def _exige_prefill() -> None:
    if not habilitado():
        raise HTTPException(status_code=503, detail=(
            "Leitura de PDF desligada neste ambiente (PREFILL_ENABLED)."))


def _pipeline():
    """Importa o prefill só quando usado — PyMuPDF é pesado e opcional."""
    from prefill import pipeline as P
    return P


def _llm():
    from prefill.llm import LLM
    try:
        return LLM()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/estado")
def estado() -> dict:
    """A tela pergunta antes de mostrar os botões."""
    if not habilitado():
        return {"habilitado": False, "ocr": False, "llm": False}
    try:
        from prefill import ocr as _ocr
        tem_ocr = _ocr.disponivel()
    except Exception:  # noqa: BLE001
        tem_ocr = False
    tem_llm = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("DEEPSEEK_API_KEY"))
    return {"habilitado": True, "ocr": tem_ocr, "llm": tem_llm}


@router.post("/analisar")
async def analisar(arquivo: UploadFile = File(...)) -> dict:
    """PASSO 1 do assistente de corte: substrato + radar, SEM LLM (custo zero).

    Devolve as faixas sugeridas para o advogado confirmar e um `sessao` para o
    passo 2 reaproveitar o substrato sem reprocessar o PDF.
    """
    _exige_prefill()
    P = _pipeline()
    conteudo = await arquivo.read()
    try:
        res = P.analisar(pdf_bytes=conteudo)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Não consegui analisar o PDF: {exc}") from exc
    meta = {"homologacao": res.get("homologacao"), "n_paginas": res.get("n_paginas"),
            "escaneadas": res.get("escaneadas"), "pje": res.get("pje"),
            "cortes_sugeridos": res.get("cortes_sugeridos")}
    sid = _guardar(res["paginas"], meta, pdfs={PECA_PROCESSO: conteudo})
    if (T := _telemetria()):
        T.registrar_analise(sid, conteudo, res)
    return {
        "sessao": sid,
        "cortes_sugeridos": res.get("cortes_sugeridos"),
        "homologacao": res.get("homologacao"),
        "n_paginas": res.get("n_paginas"),
        "escaneadas": res.get("escaneadas"),
        "radar": res.get("radar"),
        # nível 0 (índice + carimbo do PJe): conta, ofícios e alertas de
        # reconciliação; None fora do PJe
        "pje": res.get("pje"),
    }


@router.post("/extrair-cortes")
def extrair_cortes(corpo: dict = Body(...)) -> dict:
    """PASSO 2: extrai os campos das faixas que o humano CONFIRMOU (usa LLM)."""
    _exige_prefill()
    sessao = _recuperar(str(corpo.get("sessao") or ""))
    cortes = corpo.get("cortes") or []
    if not isinstance(cortes, list) or not cortes:
        raise HTTPException(status_code=422, detail="Marque ao menos uma faixa.")
    P = _pipeline()
    try:
        res = P.extrair_cortes(sessao["paginas"], cortes,
                               homol=(sessao["meta"] or {}).get("homologacao"), llm=_llm(),
                               pje=(sessao["meta"] or {}).get("pje"))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — rede/LLM instável não derruba a tela
        return JSONResponse(status_code=200, content={"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"})
    if res.get("ok"):
        _descartar_conflito_de_grafia(res)
        _anotar_citacoes(str(corpo.get("sessao") or ""), res)
        n = len(sessao["paginas"])
        _anotar_faixas(str(corpo.get("sessao") or ""), {
            peca: P._corte_ref(next((c for c in cortes if c.get("tipo") == tipo), {}), n)
            for peca, tipo in (("conta", P.TIPO_CONTA), ("oficio", P.TIPO_OFICIO),
                               ("sentenca", P.TIPO_SENTENCA))})
        res["sessao_paginas"] = corpo.get("sessao")
    if (T := _telemetria()):
        T.registrar_confirmacao(str(corpo.get("sessao") or ""), sessao["paginas"],
                                (sessao["meta"] or {}).get("cortes_sugeridos") or [], cortes, res)
    return res


@router.post("/extrair-pecas")
async def extrair_pecas(
    conta: UploadFile = File(...),
    oficio: UploadFile | None = File(None),
    sentencas: list[UploadFile] = File(default_factory=list),
) -> dict:
    """Pré-análise com as peças JÁ recortadas — o caminho que o jurídico usa.

    A conta é obrigatória (é dela que saem os dígitos); o ofício traz honorários,
    modalidade e ente; as sentenças só a natureza tributária.
    """
    _exige_prefill()
    P = _pipeline()
    conta_b = await conta.read()
    oficio_b = await oficio.read() if oficio is not None else None
    sent_b = [await s.read() for s in (sentencas or [])]
    try:
        res = P.extrair_pecas(conta=conta_b, oficio=oficio_b, sentencas=sent_b, llm=_llm())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if res.get("ok"):
        _descartar_conflito_de_grafia(res)
        # Os rótulos TÊM de ser os mesmos que o `extrair_pecas` gerou (a sentença
        # só é numerada quando há mais de uma), senão o `mapa_paginas` aponta
        # para uma peça que o visualizador não encontra.
        pdfs: dict[str, bytes] = {P.TIPO_CONTA: conta_b}
        if oficio_b is not None:
            pdfs[P.TIPO_OFICIO] = oficio_b
        for i, s in enumerate(sent_b):
            pdfs[P.TIPO_SENTENCA if len(sent_b) == 1 else f"{P.TIPO_SENTENCA} {i + 1}"] = s
        sid = _guardar([], {}, pdfs=pdfs)
        _anotar_citacoes(sid, res)
        res["sessao_paginas"] = sid
        if (T := _telemetria()):
            T.registrar_extracao_direta(sid, "pecas", [], conta_b, res, pecas=list(pdfs))
    return res


@router.post("/preencher")
async def preencher(arquivo: UploadFile = File(...)) -> dict:
    """Modo autônomo: processo completo → o juiz LLM acha a conta e o ofício."""
    _exige_prefill()
    P = _pipeline()
    conteudo = await arquivo.read()
    try:
        res = P.preencher(pdf_bytes=conteudo, llm=_llm())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if res.get("ok"):
        _descartar_conflito_de_grafia(res)
        sid = _guardar([], {}, pdfs={PECA_PROCESSO: conteudo})
        _anotar_citacoes(sid, res)
        _anotar_faixas(sid, {"conta": _faixa(res.get("conta_ref")),
                             "oficio": _faixa(res.get("oficio_ref")),
                             "sentenca": [f for f in map(_faixa, res.get("sentenca_refs") or []) if f]})
        res["sessao_paginas"] = sid
        if (T := _telemetria()):
            T.registrar_extracao_direta(sid, "autonomo", [], conteudo, res)
    return res


@router.get("/paginas/{sessao}")
def paginas_citadas(sessao: str, limite: int = 8) -> dict:
    """As páginas de onde o modelo tirou cada número, com o valor DESTACADO.

    Fecha o laço da conferência: em vez de acreditar no "pág. 7", o advogado vê
    a página com a tarja em cima do número. O destaque é determinístico — o
    `viewer` procura o trecho literal na página e marca o retângulo; não achar
    (número reescrito pelo modelo, página escaneada) devolve a página sem marca,
    que já é informação: o valor não está escrito ali daquele jeito.

    A citação vem no espaço CONCATENADO das peças; o `mapa` traduz de volta para
    (peça, página local), senão a pág 5 do concatenado renderizaria a pág 5 da
    conta — que pode nem existir.
    """
    _exige_prefill()
    s = _recuperar(sessao)
    citacoes, mapa, pdfs = s.get("citacoes") or {}, s.get("mapa") or {}, s.get("pdfs") or {}
    if not citacoes:
        return {"paginas": []}

    por_peca: dict[str, dict[int, list[str]]] = {}
    for pg_str, termos in citacoes.items():
        m = mapa.get(str(pg_str))
        peca = m["peca"] if m else (PECA_PROCESSO if PECA_PROCESSO in pdfs else None)
        local = m["pagina"] if m else int(pg_str)
        if peca:
            por_peca.setdefault(peca, {})[local] = termos

    from prefill.viewer import render_paginas
    saida = []
    for peca, destaques in por_peca.items():
        pdf = pdfs.get(peca)
        if not pdf:
            continue
        for img in render_paginas(pdf, destaques):
            saida.append({"peca": peca, "pagina": img["pagina"],
                          "n_marcas": img["n_marcas"],
                          "png": base64.b64encode(img["png"]).decode("ascii")})
            if len(saida) >= max(1, min(int(limite), 20)):
                return {"paginas": saida}
    return {"paginas": saida}


def extraido_da_sessao(sid: str) -> dict | None:
    """Para o envio ao CRM: o que a pré-análise desta sessão extraiu (ou None)."""
    with _TRAVA:
        sessao = _SESSOES.get(sid or "")
        return dict(sessao.get("extraido") or {}) if sessao else None


def _faixa(ref) -> tuple[int, int] | None:
    """"pp12-15" → (12, 15)."""
    import re
    m = re.fullmatch(r"pp(\d+)-(\d+)", str(ref or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def pecas_da_sessao(sid: str, deal_id) -> tuple[dict | None, str | None]:
    """Peças para anexar no card: {"conta"|"oficio"|"sentenca": [(nome, bytes)]}.

    Modo peças: os PDFs que o advogado subiu, como vieram. Modo processo (corte
    assistido ou autônomo): a faixa de cada peça, recortada do processo — nunca
    o processo inteiro. Devolve também um aviso quando não dá para anexar (a
    sessão vale 1h), para a tela dizer em vez de calar.
    """
    with _TRAVA:
        _limpar()
        sessao = _SESSOES.get(sid or "")
        if sessao is None:
            return None, ("Anexos das peças: a pré-análise expirou (vale 1h) ou o serviço "
                          "reiniciou — não anexei conta/ofício. Rode a pré-análise de novo para anexar.")
        pdfs, faixas = dict(sessao.get("pdfs") or {}), dict(sessao.get("faixas") or {})
    P = _pipeline()
    pecas: dict[str, list] = {}
    if PECA_PROCESSO not in pdfs:  # modo peças
        for peca, tipo in (("conta", P.TIPO_CONTA), ("oficio", P.TIPO_OFICIO), ("sentenca", P.TIPO_SENTENCA)):
            arqs = [b for k, b in pdfs.items() if k == tipo or k.startswith(tipo + " ")]
            if arqs:
                pecas[peca] = [(f"{peca}_{deal_id}" + (f"_{i}" if len(arqs) > 1 else "") + ".pdf", b)
                               for i, b in enumerate(arqs, 1)]
        return pecas, None
    if not faixas:
        return None, None  # análise sem extração: nada foi confirmado para anexar
    from prefill.cortar import cortar_pdf
    # a faixa é (a, b), ou uma lista delas (sentença e acórdão são documentos
    # separados nos autos: cada um vira um anexo)
    cortes = cortar_pdf(pdfs[PECA_PROCESSO], [
        {"tipo": p, "pagina_inicio": a, "pagina_fim": b}
        for p in ("conta", "oficio", "sentenca") if p in faixas
        for a, b in (faixas[p] if isinstance(faixas[p], list) else [faixas[p]])])
    for c in cortes:
        pecas.setdefault(c["tipo"], []).append((f"{c['tipo']}_{deal_id}_{c['ref']}.pdf", c["pdf_bytes"]))
    return pecas, None
