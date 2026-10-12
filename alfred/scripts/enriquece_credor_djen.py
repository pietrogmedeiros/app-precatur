# -*- coding: utf-8 -*-
"""Aplica o cache do DJEN (scripts/fetch_djen_nomes.py) no credor/advogado do banco --
mesmo padrao do enriquece_credor.py (Callix/TJMG), mas fonte='DJEN' e so' PREENCHE onde
credor esta' NULL (nao ha mascara pra desmascarar aqui, a fila desses tribunais nunca
teve credor nenhum).

Le data/djen_nomes/*.jsonl (1 arquivo por tribunal, escrito pelo coletor). Cada linha:
{numero, status, credores[], advogados[]}. Filtra "SIGILO" (o DJEN devolve esse literal
no lugar do nome quando o processo esta sob segredo de justica -- nao e' um nome de
credor de verdade, gravar isso seria pior que deixar NULL). Quando sobra mais de um
credor real na mesma publicacao, grava todos separados por "; " (mesmo caso de
litisconsorcio que o RPA_RJ trata do mesmo jeito).

AUDITAVEL: credor_fonte='DJEN' no que foi preenchido (NULL = lista do tribunal,
'Callix' = TJMG desmascarado). Rodado ao fim de db_build; roda sozinho tambem:
    python scripts/enriquece_credor_djen.py
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import pathlib
import sqlite3

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DIR = os.path.join(BASE, "data", "djen_nomes")

_spec = importlib.util.spec_from_file_location("credor_norm", os.path.join(BASE, "scripts", "credor_norm.py"))
CN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CN)


def _limpa(nomes):
    return [n for n in (nomes or []) if n and n.strip().upper() != "SIGILO"]


def _carrega_cache():
    """numero -> (credor_str, advogado_str). So' guarda quem tem pelo menos 1 nome real."""
    mapa = {}
    for f in sorted(glob.glob(os.path.join(DIR, "*.jsonl"))):
        for linha in open(f, encoding="utf-8"):
            linha = linha.strip()
            if not linha:
                continue
            try:
                r = json.loads(linha)
            except json.JSONDecodeError:
                continue
            credores = _limpa(r.get("credores"))
            if not credores:
                continue
            adv = "; ".join(r.get("advogados") or []) or None
            mapa[r["numero"]] = ("; ".join(credores), adv)
    return mapa


def enriquece(cx, log=print):
    if not glob.glob(os.path.join(DIR, "*.jsonl")):
        raise FileNotFoundError(f"sem cache do DJEN em {DIR}")
    mapa = _carrega_cache()
    nomes = advs = 0
    alterados = []
    for pid, numero, adv_atual in cx.execute(
            "SELECT id, numero, advogado FROM precatorio_atual "
            "WHERE credor IS NULL AND numero IS NOT NULL").fetchall():
        par = mapa.get(numero)
        if not par:
            continue
        credor_str, adv_str = par
        cx.execute("UPDATE precatorio SET credor=?, credor_fonte='DJEN' WHERE id=?", (credor_str, pid))
        nomes += 1
        alterados.append(pid)
        if adv_str and not adv_atual:
            cx.execute("UPDATE precatorio SET advogado=? WHERE id=?", (adv_str, pid))
            advs += 1
    # credor mudou -> busca por nome (credor_norm + credor_fts) tem que acompanhar
    CN.sincroniza(cx, alterados)
    return nomes, advs


def main():
    db = os.path.join(BASE, "data", "alfred.db")
    with sqlite3.connect(db) as cx:
        nomes, advs = enriquece(cx)
        cx.commit()
    print(f"DJEN: {nomes:,} nomes preenchidos | {advs:,} advogados preenchidos")


if __name__ == "__main__":
    main()
