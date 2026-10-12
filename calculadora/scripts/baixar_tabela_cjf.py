"""Baixa a Tabela de Correção Monetária OFICIAL do CJF (SICOM) e grava como CSV.

Autoridade da correção histórica (Manual de Cálculos da JF): cadeia
ORTN→OTN→BTN→IPC→INPC→IPCA(especial)→UFIR→IPCA-E, com os expurgos oficiais dos
Planos (Verão jan-fev/1989, Collor mar/1990-fev/1991). SUPERSEDE a tabela regional
TRF1/SJRO (`fatores_trf1_1964_2019.csv`), que divergia da autoridade no pré-1991
(expurgos tratados de outro modo — ver docs/regimes_historicos.md §6).

Fonte: https://sicom.cjf.jus.br/tabelaCorMor.php (POST acao=geraTabelaIndice).
A tabela vem como HTML-servido-como-.xls (matriz ano × mês de coeficientes que
trazem o valor daquele mês à referência `mm/aaaa`). O fator A→B é
`coef[A]/coef[B]` (independe da referência).

Rodar: `python scripts/baixar_tabela_cjf.py`  (ref default = mês recente fixo).
"""

from __future__ import annotations

import csv
import html as H
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path

URL = "https://sicom.cjf.jus.br/tabelaCorMor.php"
OUT = Path(__file__).resolve().parent.parent / "precaturia" / "data" / "historico" / "cjf_tcm_geral.csv"

# seqEncadeamento=6 = "Ações Condenatórias em Geral" — a cadeia geral do Manual JF
# (art. 21-A). Referência fixa para estabilidade do CSV versionado (o fator
# A→B independe dela).
SEQ_GERAL = "6"
REF_MES, REF_ANO = "12", "2025"

_UA = {
    "User-Agent": "Mozilla/5.0 (validacao-precaturia)",
    "Referer": URL,
    "Content-Type": "application/x-www-form-urlencoded",
}


def baixar_tcm(seq: str = SEQ_GERAL, mes: str = REF_MES, ano: str = REF_ANO) -> str:
    data = urllib.parse.urlencode({
        "acao": "geraTabelaIndice", "tipoTabela": "TCM", "seqEncadeamento": seq,
        "mesIndice": mes, "anoIndice": ano, "tipoArquivo": "xls",
    }).encode()
    req = urllib.request.Request(URL, data=data, headers=_UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("iso-8859-1", errors="replace")


def parse_matriz(raw: str) -> tuple[dict[str, Decimal], list[str]]:
    """Extrai {'YYYY-MM': coef} + as linhas da cadeia (rodapé) para documentar."""
    coef: dict[str, Decimal] = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S | re.I):
        cells = [
            H.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        ]
        if not cells or not re.fullmatch(r"\d{4}", cells[0]):
            continue
        ano = int(cells[0])
        for mes_i, val in enumerate(cells[1:13], start=1):
            v = val.replace(".", "").replace(",", ".")
            if re.fullmatch(r"\d+\.\d+", v):
                coef[f"{ano:04d}-{mes_i:02d}"] = Decimal(v)
    cadeia = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S | re.I):
        t = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", tr))).strip()
        if t.startswith("-") and len(t) > 4:
            cadeia.append(t.split(" Ex:")[0].split(" A)")[0].strip())
    return coef, cadeia


def main() -> int:
    print(f"POST {URL} (TCM, seq={SEQ_GERAL}, ref {REF_MES}/{REF_ANO})...")
    raw = baixar_tcm()
    coef, cadeia = parse_matriz(raw)
    if len(coef) < 600:
        print(f"ERRO: só {len(coef)} coeficientes — abortando (esperado ~735).")
        return 1
    meses = sorted(coef)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# fonte", f"CJF SICOM tabelaCorMor (Manual de Cálculos JF) — TCM Condenatórias Geral, ref {REF_MES}/{REF_ANO}"])
        w.writerow(["# baixado_em", datetime.utcnow().strftime("%Y-%m-%d")])
        w.writerow(["# cobertura", f"{meses[0]} a {meses[-1]}"])
        w.writerow(["# semantica", "coef traz o valor do mês à referência; fator A->B = coef[A]/coef[B] (reform-safe, expurgos oficiais embutidos)"])
        for linha in cadeia:
            w.writerow([f"# cadeia", linha])
        w.writerow(["mes", "coef"])
        for m in meses:
            w.writerow([m, coef[m]])
    print(f"-> {OUT} ({len(coef)} meses; {meses[0]}..{meses[-1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
