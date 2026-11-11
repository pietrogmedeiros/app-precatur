# -*- coding: utf-8 -*-
"""Avisa quando o TJRN publica EDITAL NOVO de acordo direto do Estado do RN (ou de municipio).

    python scripts/monitor_edital_acordo_rn.py                 # ultimos 45 dias
    python scripts/monitor_edital_acordo_rn.py --desde 2026-01-01

Por que o DJEN: o proprio TJRN diz (pagina de Acordo Direto) que TODOS os editais saem no
DJEN, e o site do tribunal bloqueia acesso automatico (Akamai, 403). A busca por texto do
DJEN devolve tambem milhares de intimacoes de precatorio que apenas citam "acordo direto",
entao filtra-se no cliente: orgao Divisao de Precatorios + cabecalho "EDITAL ... ACORDO
DIRETO N. xx/aaaa - DP/TJRN". Editais ja conhecidos ficam em CONHECIDOS (01/2025 do
Estado e 02/2025 de Natal; os de 2023/2024 sao anteriores).

Saida: 0 e "nenhum edital novo" ou lista dos novos (exit 1 = ha novidade, p/ cron avisar).
"""
import argparse
import re
import sys
from datetime import date, timedelta

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DJEN = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
CONHECIDOS = {"01/2025", "02/2025", "05/2024", "04/2024", "03/2024", "02/2024", "01/2024", "01/2023"}
RX_ED = re.compile(r"EDITAL[^.]{0,80}?ACORDO\s+DIRETO\s+N[ºO°.]*\s*(\d{1,2}/20\d{2})", re.I)
RX_ED2 = re.compile(r"ACORDO\s+DIRETO\s+N[ºO°.]*\s*(\d{1,2}/20\d{2})\s*[–-]\s*DP/TJRN", re.I)


def varre(desde):
    achados, pag = {}, 1
    while True:
        r = requests.get(DJEN, params={"siglaTribunal": "TJRN", "texto": "acordo direto",
                                       "dataDisponibilizacaoInicio": desde,
                                       "itensPorPagina": 100, "pagina": pag},
                         headers={"User-Agent": "Mozilla/5.0 (alfred-monitor)"}, timeout=90)
        r.raise_for_status()
        its = r.json().get("items", [])
        for it in its:
            if "Precat" not in (it.get("nomeOrgao") or ""):
                continue
            t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", it.get("texto") or ""))
            m = RX_ED.search(t[:900]) or RX_ED2.search(t[:900])
            if m:
                achados.setdefault(m.group(1), []).append(
                    (it["data_disponibilizacao"], it.get("numeroprocessocommascara"), t[:260]))
        if len(its) < 100:
            break
        pag += 1
    return achados


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default=(date.today() - timedelta(days=45)).isoformat())
    a = ap.parse_args()
    ach = varre(a.desde)
    novos = {k: v for k, v in ach.items() if k not in CONHECIDOS}
    print(f"DJEN/TJRN desde {a.desde}: editais citados = {sorted(ach) or 'nenhum'}")
    if not novos:
        print("nenhum edital novo de acordo direto.")
        return 0
    for k, v in sorted(novos.items()):
        d, proc, txt = sorted(v)[0]
        print(f"NOVO edital {k} — 1a publicacao {d} (PA {proc})\n   {txt}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
