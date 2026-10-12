"""Renderiza as PÁGINAS citadas como imagem, com os valores extraídos DESTACADOS.

Fecha o loop de verificação: o advogado vê, na própria calculadora, a página de
onde cada número saiu, com o número realçado — sem sair pra abrir o PDF.
Determinístico (fitz): busca literal do trecho na página e marca o retângulo.
"""
from __future__ import annotations

import fitz


def render_pagina(pdf_bytes: bytes, pagina: int, dpi: int = 110) -> bytes | None:
    """Renderiza UMA página (1-based) como PNG, sem destaque. Para o preview de
    borda do assistente (o advogado confere onde a faixa começa/termina)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if not (1 <= pagina <= doc.page_count):
            return None
        return doc[pagina - 1].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def render_paginas(pdf_bytes: bytes, destaques: dict[int, list[str]], dpi: int = 110) -> list[dict]:
    """destaques = {pagina_1based: [termos a realçar]}. Devolve [{pagina, png, n_marcas}]."""
    out = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for pg in sorted(destaques):
            if not (1 <= pg <= doc.page_count):
                continue
            page = doc[pg - 1]
            marcas = 0
            for termo in destaques[pg]:
                termo = (str(termo) if termo is not None else "").strip()
                if len(termo) < 3:
                    continue
                for rect in page.search_for(termo)[:8]:
                    page.add_highlight_annot(rect)
                    marcas += 1
            png = page.get_pixmap(dpi=dpi).tobytes("png")
            out.append({"pagina": pg, "png": png, "n_marcas": marcas})
    finally:
        doc.close()
    return out
