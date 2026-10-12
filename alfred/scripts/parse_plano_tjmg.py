# -*- coding: utf-8 -*-
"""Extrai o plano anual de pagamento do TJMG (PDFs GEPREC, exercicios 2020-2026).

Fonte: art. 64 §1º da Res. CNJ 303/2019 — o TJ publica ate 10/dez os planos
homologados do exercicio seguinte. O PDF cobre SO o REGIME ESPECIAL (~150 entes
em MG), que e' quem tem plano; o regime comum nao aparece.

Colunas do PDF: Ordem | Ente | Notas/Cumprimento | Situacao do plano | RCL |
Percentual anual da RCL | Valor mensal | Constante/Variavel | Estimativa de saida.

    python scripts/parse_plano_tjmg.py data/planos_homologados/tjmg_2024.pdf
"""
import re
import sys
import unicodedata

from pypdf import PdfReader

SITUACOES = ("Homologado", "Homologada", "Deferido parcialmente", "Não apresentou",
             "Nao apresentou", "Indeferido", "Em análise", "Em analise")
# a situacao pode quebrar linha no PDF ("Deferido \nparcialmente")
_SIT = "|".join(s.replace(" ", r"\s+") for s in SITUACOES)
LINHA = re.compile(
    r"^(\d{1,4})\s+((?:MUNIC[IÍ]PIO|ESTADO)\s+D[EO]\s+.+?)\s+(" + _SIT + r")\s+"
    r"([\d]{1,3}(?:\.[\d]{3})*,\d{2})\s+(\d+,\d{2})\s*%", re.I)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"^(MUNICIPIO|ESTADO)\s+(DE|DO|DA)\s+", "", s.strip())
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def val(s):
    return float(s.replace(".", "").replace(",", "."))


def extrai(pdf):
    """{nome_normalizado: {ordem, situacao, rcl, pct, anual}}"""
    t = "\n".join((p.extract_text() or "") for p in PdfReader(pdf).pages)
    linhas = [re.sub(r"[ \t]+", " ", x).strip() for x in t.split("\n")]
    # junta a linha seguinte quando a situacao quebrou (linha comeca com ordem+ente
    # mas ainda nao tem o par "RCL pct%")
    juntas, i = [], 0
    while i < len(linhas):
        cur = linhas[i]
        if re.match(r"^\d{1,4}\s+(MUNIC[IÍ]PIO|ESTADO)", cur, re.I) and not LINHA.match(cur):
            while i + 1 < len(linhas) and not LINHA.match(cur):
                i += 1
                cur = cur + " " + linhas[i]
                if len(cur) > 400:
                    break
        juntas.append(cur)
        i += 1
    out = {}
    for l in juntas:
        m = LINHA.match(l)
        if not m:
            continue
        rcl, pct = val(m.group(4)), val(m.group(5))
        out[norm(m.group(2))] = {
            "ordem": int(m.group(1)),
            "situacao": re.sub(r"\s+", " ", m.group(3)).strip(),
            "rcl": rcl, "pct": pct, "anual": round(rcl * pct / 100, 2)}
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    d = extrai(sys.argv[1])
    from collections import Counter
    print(f"{len(d)} entes | situacoes: {Counter(v['situacao'] for v in d.values()).most_common()}")
