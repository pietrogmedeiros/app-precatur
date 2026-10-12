"""Detecção determinística do ATO DE HOMOLOGAÇÃO (regex puro, sem DB, sem LLM).

Extraído de `precaturia.pipeline.homologacao_anchor` para rodar standalone na VM.
Acha o despacho em que o juiz HOMOLOGA os cálculos ("homologo", "ficam
homologados") perto de "cálculo/conta", capturando o "Evento N" quando houver.
É a pista forte de QUAL conta é a operativa/homologada.
"""
from __future__ import annotations

import re

# Verbo de homologação como ATO JUDICIAL (o juiz decidindo) — NÃO o pedido da
# parte ("requer-se a homologação"), que tornaria o elo trivial.
_RE_HOMOLOGO = re.compile(
    r"\bhomologo\b|\b(?:julgo|ficam|restam|declaro|resta|fica)\s+homologad",
    re.IGNORECASE,
)
_RE_EVENTO = re.compile(r"\beven(?:to|\.)\s*(?:n[º.\s]*)?(\d{1,4})", re.IGNORECASE)
_RE_CALC = re.compile(r"c[áa]lculos?|conta de liquida|liquida", re.IGNORECASE)


def achar_homologacao(paginas: list[str]) -> dict | None:
    """Despacho que homologa cálculos. Varre o texto COMPLETO de cada página.
    Retorna {pagina (1-based), evento|None, trecho} ou None."""
    for i, pag in enumerate(paginas, start=1):
        txt = re.sub(r"\s+", " ", pag or "")
        for m in _RE_HOMOLOGO.finditer(txt):
            jan = txt[max(0, m.start() - 160): m.start() + 60]
            if not _RE_CALC.search(jan):
                continue
            ev = _RE_EVENTO.search(jan)
            return {
                "evento": int(ev.group(1)) if ev else None,
                "pagina": i,
                "trecho": jan.strip()[:200],
            }
    return None
