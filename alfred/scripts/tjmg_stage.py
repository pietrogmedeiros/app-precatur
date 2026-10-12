# -*- coding: utf-8 -*-
"""Estagia a base RICA do TJMG (raspagem RPA_RJ) para o formato que o db_build consome.

Substitui a fonte antiga do TJMG no Alfred (data/epd_itens/, a consulta interativa
do site — que NAO serve as capitais: BH, Contagem, Betim, Ipatinga... ficavam de fora).
A base do RPA cobre municipal + estadual, com valor de face, valor atualizado, processo
de execucao (origem) e data de apresentacao (Protocolo) — campos que o EPD nao tinha.

Entradas (data/rpa_mg/, copiadas do RPA_RJ, snapshot 2026-07-30):
  * mg_municipios_2026-07-30.xlsx  (18.392 precatorios municipais)
  * mg_estado_2026-07-30.xlsx      (16.521 precatorios estaduais)
  * mg_todos_entes.csv             (so p/ enriquecer superpreferencia; casa ~73%)

Saida:
  * data/tjmg/precatorios.json     (uma lista de entes, cada um com sua fila)

ORDEM DA FILA: (Ano Venc., Alimentar antes de Comum, Numero). Corrigido em
2026-09-29: a versao anterior ordenava so' por (Ano Venc., Protocolo), ignorando
natureza, e intercalava Comum no meio de Alimentar (caso Divinopolis: item
112/Comum caia entre os itens 230 e 231/Alimentar porque o protocolo dele ficava
cronologicamente no meio). Conferido contra DOIS prints do site do TJMG: dentro de
cada ANO ORCAMENTARIO o bloco Alimentar vem inteiro antes do bloco Comum daquele
mesmo ano (ex. venc 2026: Alimentar 225-241 depois Comum 112-121; ao virar pro
venc 2027 o Alimentar 242-247 volta a vir antes do Comum 122-124 daquele ano) — NAO
e' um unico bloco Alimentar global seguido de um unico bloco Comum global. Dentro
de cada (ano, natureza) a ordem e' pelo NUMERO do precatorio (contador proprio por
natureza, jah' cronologico por expedicao) — nao pelo protocolo, que nem sai
monotonico dentro do bloco. O EPD trazia uma ordem_tabela raspada; aqui ela e'
derivada, pois a base RPA nao a traz.

VALOR: usa Valor de FACE (o Alfred inteiro trabalha em face; o §23/fila e' sobre face).
O Valor Atualizado fica de fora do modelo por ora (dividia comparabilidade entre TJs).

Uso:
    python scripts/tjmg_stage.py            # le data/rpa_mg/*, grava data/tjmg/precatorios.json
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import unicodedata

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
RPA = os.path.join(BASE, "data", "rpa_mg")
SAIDA = os.path.join(BASE, "data", "tjmg", "precatorios.json")
COLETADO_EM = "2026-07-30T00:00:00+00:00"      # data do snapshot RPA (nao o mtime do arquivo)

FONTES = [
    os.path.join(RPA, "mg_municipios_2026-07-30.xlsx"),
    os.path.join(RPA, "mg_estado_2026-07-30.xlsx"),
]
CSV_PREF = os.path.join(RPA, "mg_todos_entes.csv")
# eproc que a base RPA nao trouxe ("Nao consta n Eproc"), raspado depois do site por
# scripts/tjmg_eproc_complemento.py. So preenche o que a base deixou vazio.
COMPLEMENTO_EPROC = os.path.join(BASE, "data", "tjmg", "eproc_complemento.json")

# palavras que caracterizam superpreferencia (art. 100 §2: idoso/doenca grave/deficiencia)
PREF_KEYS = ("IDAD", "IDOS", "60", "DOENC", "DEFIC", "GRAVE")


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def chave_num(s) -> str:
    """'31 A' / '31A' / '31-A' -> '31A' (o site e a base RPA nem sempre espacam igual)."""
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def carrega_complemento_eproc():
    """(ente_norm, chave_num) -> eproc (20 digitos), do complemento raspado do site."""
    if not os.path.exists(COMPLEMENTO_EPROC):
        return {}
    j = json.load(open(COMPLEMENTO_EPROC, encoding="utf-8"))
    return {(norm(e), n): ep for e, nums in j.get("entes", {}).items() for n, ep in nums.items()}


def num_key(s):
    """Chave de ordenacao do numero do precatorio dentro da natureza: numerico quando
    da', com o texto cru como desempate (cobre desdobramentos tipo '31 A'/'31 B')."""
    d = dig(s)
    return (int(d) if d else 10**9, str(s or ""))


def col(df, *subs):
    """Primeira coluna cujo nome contem TODOS os pedacos (robusto a mojibake de acento)."""
    for c in df.columns:
        cl = c.lower()
        if all(s.lower() in cl for s in subs):
            return c
    raise KeyError(subs)


def ano(x):
    d = re.findall(r"\d{4}", str(x or ""))
    return int(d[0]) if d else 9999


def iso_data(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def carrega_pref():
    """(ente_norm, num) -> superpreferencia, a partir do CSV que traz a coluna."""
    if not os.path.exists(CSV_PREF):
        return {}
    d = pd.read_csv(CSV_PREF, dtype=str, encoding="utf-8")
    d.columns = [c.replace("﻿", "") for c in d.columns]
    pref = {}
    for _, r in d.iterrows():
        p = str(r.get("preferencia") or "").strip()
        if p and any(k in norm(p) for k in PREF_KEYS):
            pref[(norm(r.get("ente_devedor")), dig(r.get("precatorio")))] = p
    return pref


def main():
    pref = carrega_pref()
    print(f"superpreferencias no CSV: {len(pref)}")
    comp = carrega_complemento_eproc()
    print(f"eproc no complemento do site: {len(comp)}")
    n_comp = 0

    por_ente = {}          # ente_nome -> lista de itens crus
    total = 0
    for f in FONTES:
        df = pd.read_excel(f)
        c_ente = col(df, "ente")
        c_num = col(df, "precat")
        c_nat = col(df, "natureza")
        c_venc = col(df, "ano venc")
        c_sit = col(df, "situa")
        c_orig = col(df, "proc", "execu")
        c_face = col(df, "valor de face")
        c_prot = col(df, "protocolo")
        c_nome = col(df, "identifica")
        c_cred = col(df, "credor")
        # "N. Eproc 2G" = o CNJ do PRECATORIO. E o unico numero que o comercial
        # recebe no card do Bitrix, e o que ele cola na busca. Vinha sendo descartado
        # aqui, e por isso nenhum precatorio de MG era localizavel por numero.
        c_eproc = col(df, "eproc")
        for _, r in df.iterrows():
            ente = str(r[c_ente]).strip()
            if not ente or ente.lower() == "nan":
                continue
            sit = str(r[c_sit] or "").strip()
            suspenso = 1 if re.search(r"suspenso|parcelado", sit, re.I) else 0
            nome = r[c_nome]
            credor = nome if (isinstance(nome, str) and nome.strip()) else r[c_cred]
            eproc = (dig(r[c_eproc]) or None) if c_eproc else None
            if not eproc or len(eproc) != 20:
                novo = comp.get((norm(ente), chave_num(r[c_num])))
                n_comp += bool(novo)
                eproc = novo or eproc
            por_ente.setdefault(ente, []).append({
                # numero CRU: o TJMG desdobra em "31", "31 A", "31 B"... e so os digitos
                # colapsam os seis no mesmo "31". db_build guarda o cru em numero_fmt
                # e os digitos em numero.
                "num": str(r[c_num]).strip(),
                "numero_origem": dig(r[c_orig]) or None,
                "numero_eproc": eproc,
                "natureza": r[c_nat],
                "venc": ano(r[c_venc]),
                "valor": float(r[c_face] or 0),
                "situacao": sit,
                "suspenso": suspenso,
                "protocolo": iso_data(r[c_prot]),
                "superpreferencia": pref.get((norm(ente), dig(r[c_num]))),
                "credor": (str(credor).strip() if credor is not None and str(credor).strip()
                           and str(credor).lower() != "nan" else None),
            })
            total += 1
        print(f"  {os.path.basename(f)}: {len(df)} linhas")
    print(f"eproc completado pelo complemento do site: {n_comp}")

    # ordem da fila por ente: so os que estao NA fila (nao suspensos), por
    # (ano venc., natureza: Alimentar antes de Comum, numero do precatorio)
    entes = []
    n_fila = 0
    for ente, itens in sorted(por_ente.items()):
        fila = [i for i in itens if not i["suspenso"]]
        fila.sort(key=lambda i: (i["venc"], str(i["natureza"] or "").strip() != "Alimentar",
                                  num_key(i["num"])))
        for pos, i in enumerate(fila, 1):
            i["ordem"] = pos
        for i in itens:
            i.setdefault("ordem", None)
        n_fila += len(fila)
        entes.append({"ente": ente, "uf": "MG", "precatorios": itens})

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as fh:
        json.dump({"fonte": "RPA_RJ ATUALIZADO 2026-07-30", "coletado_em": COLETADO_EM,
                   "entes": entes}, fh, ensure_ascii=False)
    print(f"\nentes: {len(entes)} | precatorios: {total} | na fila (nao suspensos): {n_fila}")
    print(f"com superpreferencia: {sum(1 for e in entes for i in e['precatorios'] if i['superpreferencia'])}")
    print(f"SALVO: {SAIDA}")


if __name__ == "__main__":
    main()
