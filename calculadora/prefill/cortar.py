"""Corte físico do PDF por faixa de páginas (fitz), determinístico.

O advogado confirma as faixas no assistente; aqui cada faixa vira um PDF próprio
(1 ofício real = 1 peça = 1 corte). São os artefatos que, no M2, vão para os
campos tipados do Bitrix; no M1 servem de download e prova visual do corte.

`garbage=4, deflate=True` no `tobytes` evita o inchaço de slice conhecido (uma
subseleção ingênua carrega o xref inteiro do master) — ver memória do projeto.
"""
from __future__ import annotations

import re
import unicodedata

import fitz


def _slug(texto: str | None, limite: int = 24) -> str:
    t = unicodedata.normalize("NFKD", texto or "corte").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return (t or "corte")[:limite]


def cortar_pdf(pdf_bytes: bytes, cortes: list[dict], n_paginas: int | None = None) -> list[dict]:
    """Fatia `pdf_bytes` nas faixas `cortes` = [{tipo, pagina_inicio, pagina_fim}].

    Devolve [{tipo, ref, nome, n_paginas, pdf_bytes}] — um item por faixa válida.
    Páginas são 1-based (inclusivas); faixas inválidas/fora do documento são
    silenciosamente descartadas (a UI valida antes, isto é a rede defensiva).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = n_paginas or doc.page_count
    out: list[dict] = []
    try:
        for i, corte in enumerate(cortes, start=1):
            try:
                a, b = int(corte["pagina_inicio"]), int(corte["pagina_fim"])
            except (KeyError, TypeError, ValueError):
                continue
            a, b = min(a, b), max(a, b)
            a = max(a, 1)
            b = min(b, total)
            if a > b:
                continue
            tipo = corte.get("tipo") or "corte"
            novo = fitz.open()
            novo.insert_pdf(doc, from_page=a - 1, to_page=b - 1)
            pdf = novo.tobytes(garbage=4, deflate=True)
            novo.close()
            out.append({
                "tipo": tipo,
                "ref": f"pp{a}-{b}",
                "nome": f"{i:02d}_{_slug(tipo)}_pp{a}-{b}.pdf",
                "n_paginas": b - a + 1,
                "pdf_bytes": pdf,
            })
    finally:
        doc.close()
    return out
