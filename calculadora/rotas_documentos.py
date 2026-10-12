"""Rotas de documentos: pré-análise, assistente de corte e prefill por PDF.

O fluxo do assistente tem DOIS passos (analisar → extrair) e o segundo precisa
do substrato do primeiro. No Streamlit isso morava no `session_state`; aqui mora
numa **sessão em memória, com validade**. Em disco não pode: o repositório é
"sem banco, por desenho" justamente para não deixar PII parada — e o PDF do
processo é o documento mais sensível que passa por aqui.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/documentos", tags=["documentos"])

# Sessões do assistente: id → {"paginas", "meta", "expira"}.
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


def _guardar(paginas: list[dict], meta: dict) -> str:
    with _TRAVA:
        _limpar()
        sid = uuid.uuid4().hex
        _SESSOES[sid] = {"paginas": paginas, "meta": meta, "expira": time.time() + VALIDADE_S}
        return sid


def _recuperar(sid: str) -> dict:
    with _TRAVA:
        _limpar()
        sessao = _SESSOES.get(sid)
    if not sessao:
        raise HTTPException(status_code=410, detail=(
            "A análise expirou (ou o serviço reiniciou). Envie o PDF de novo."))
    return sessao


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
            "escaneadas": res.get("escaneadas")}
    sid = _guardar(res["paginas"], meta)
    return {
        "sessao": sid,
        "cortes_sugeridos": res.get("cortes_sugeridos"),
        "homologacao": res.get("homologacao"),
        "n_paginas": res.get("n_paginas"),
        "escaneadas": res.get("escaneadas"),
        "radar": res.get("radar"),
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
                               homol=(sessao["meta"] or {}).get("homologacao"), llm=_llm())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — rede/LLM instável não derruba a tela
        return JSONResponse(status_code=200, content={"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"})
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
        return P.extrair_pecas(conta=conta_b, oficio=oficio_b, sentencas=sent_b, llm=_llm())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"}


@router.post("/preencher")
async def preencher(arquivo: UploadFile = File(...)) -> dict:
    """Modo autônomo: processo completo → o juiz LLM acha a conta e o ofício."""
    _exige_prefill()
    P = _pipeline()
    conteudo = await arquivo.read()
    try:
        return P.preencher(pdf_bytes=conteudo, llm=_llm())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"}
