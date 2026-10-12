# -*- coding: utf-8 -*-
"""Repoe o nome COMPLETO no credor do TJMG a partir da lista do Callix (discador).

POR QUE: a lista cronologica do TJMG mascara pessoa fisica por LGPD -> ~55% dos
credores chegam como iniciais ("J.N.A.M."). A lista do Callix (data/callix_mg/*.xlsx)
tem o nome completo + o processo de origem + o CNJ do precatorio, porque foi
enriquecida por fora. Cruzando as duas, da p/ desmascarar os precatorios que passaram
pelo discador -- SEM tocar nos demais (so temos nome de quem foi para o Callix).

TRAVA DE SEGURANca: so troca o nome quando as INICIAIS do nome completo batem com a
mascara (ignorando preposicoes). Um mesmo processo de origem pode ter dois credores
(a parte E o advogado da sucumbencia); a validacao evita colocar o nome errado.

AUDITAVEL: marca precatorio.credor_fonte = 'Callix' no que foi reposto (NULL = lista
do tribunal). Rodado ao fim de db_build; tambem roda sozinho:
    python scripts/enriquece_credor.py
"""
from __future__ import annotations

import glob
import importlib.util
import os
import pathlib
import re
import unicodedata

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DIR = os.path.join(BASE, "data", "callix_mg")

_spec = importlib.util.spec_from_file_location("credor_norm", os.path.join(BASE, "scripts", "credor_norm.py"))
CN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CN)
PREP = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _dig(s):
    return re.sub(r"\D", "", str(s or ""))


def _norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()


def _nome_limpo(s):
    """Tira sufixos entre parenteses/barra ('(Sucumbencia', '/ MATHEUS') e espacos."""
    return re.sub(r"\s+", " ", re.split(r"[(/]", str(s or ""))[0]).strip()


def _iniciais(nome):
    return "".join(w[0] for w in _norm(_nome_limpo(nome)).split() if w and w not in PREP)


def _mask_letras(s):
    return re.sub(r"[^A-Za-z]", "", str(s or "")).upper()


def _e_mascara(s):
    return bool(re.fullmatch(r"([A-Za-z]\.){2,}", str(s or "").replace(" ", "")))


def _col(df, *chaves):
    for c in df.columns:
        cl = _norm(c).lower()
        if all(k in cl for k in chaves):
            return c
    return None


def _cpf_norm(x):
    """CPF vem como inteiro na planilha -> perde zero a' esquerda. Zera-pad em 11
    (CPF) e deixa CNPJ de 14 como esta'. None se nao parecer documento."""
    d = _dig(x)
    if not d:
        return None
    if len(d) <= 11:
        return d.zfill(11)
    return d if len(d) == 14 else None


def _carrega_nomes():
    """Le os xlsx do discador -> (por CNJ-precatorio, por origem[lista]); cada valor
    e' (nome, cpf)."""
    import pandas as pd
    por_eproc, por_orig = {}, {}
    for f in sorted(glob.glob(os.path.join(DIR, "*.xlsx"))):
        df = pd.read_excel(f)
        c_nome = _col(df, "nome")
        c_cpf = _col(df, "cpf")
        c_ep = _col(df, "cnj")                        # 'CNJ Precatorio'
        c_og = _col(df, "processo", "origem")
        for _, r in df.iterrows():
            nome = _nome_limpo(r.get(c_nome)) if c_nome else ""
            if not nome or nome.lower() == "nan":
                continue
            cpf = _cpf_norm(r.get(c_cpf)) if c_cpf else None
            par = (nome, cpf)
            if c_ep and (ep := _dig(r.get(c_ep))):
                por_eproc.setdefault(ep, par)
            if c_og and (og := _dig(r.get(c_og))):
                por_orig.setdefault(og, []).append(par)
    return por_eproc, por_orig


def _alvo_iniciais(credor):
    """As letras a bater: a propria mascara (se PF mascarada) ou as iniciais do nome
    completo ja publicado. Serve p/ confirmar que o registro do Callix e' a MESMA
    pessoa antes de colar o CPF (evita parte↔advogado no mesmo processo)."""
    return _mask_letras(credor) if _e_mascara(credor) else _iniciais(credor)


def enriquece(cx, log=print):
    """Repoe nome mascarado E popula CPF do TJMG a partir do Callix, na coleta atual.
    So grava quando as iniciais confirmam a mesma pessoa. Retorna (nomes, cpfs, rejeitados)."""
    if not glob.glob(os.path.join(DIR, "*.xlsx")):
        raise FileNotFoundError(f"sem arquivos do Callix em {DIR}")
    por_eproc, por_orig = _carrega_nomes()
    nomes = cpfs = rejeitados = 0
    alterados = []
    # origem do CPF (LGPD, A6): grava fonte e metodo junto com o CPF quando o banco ja'
    # tem as colunas (db_build.classifica_cpf da' a confianca depois). Nao muda o casamento.
    com_origem = "cpf_metodo" in {c[1] for c in cx.execute("PRAGMA table_info(precatorio)")}
    for r in cx.execute(
            "SELECT id, numero_eproc, numero_origem, credor, cpf_cnpj FROM precatorio_atual "
            "WHERE tribunal='TJMG'").fetchall():
        pid, eproc, origem, credor, cpf_atual = r
        alvo = _alvo_iniciais(credor)
        if not alvo:
            continue
        cand = via = None
        ep = _dig(eproc)
        if ep and ep in por_eproc:                    # chave 1:1 (CNJ do precatorio)
            cand, via = por_eproc[ep], "cnj_precatorio"
        if cand is None:                              # fallback: origem (pode ter varios credores)
            for c in por_orig.get(_dig(origem), []):
                if _iniciais(c[0]) == alvo:
                    cand, via = c, "iniciais_fallback"
                    break
        if cand is None:
            continue
        nome_c, cpf_c = cand
        if _iniciais(nome_c) != alvo:                 # TRAVA: mesma pessoa (iniciais)
            rejeitados += 1
            continue
        if _e_mascara(credor):                        # repoe nome so onde estava mascarado
            cx.execute("UPDATE precatorio SET credor=?, credor_fonte='Callix' WHERE id=?", (nome_c, pid))
            nomes += 1
            alterados.append(pid)
        if cpf_c and not _dig(cpf_atual):             # popula CPF onde faltava (TJMG nao tinha nenhum)
            if com_origem:                            # nunca sobrescreve: so' onde cpf_cnpj estava vazio
                cx.execute("UPDATE precatorio SET cpf_cnpj=?, cpf_fonte='callix_planilhas_mg', cpf_metodo=? "
                           "WHERE id=?", (cpf_c, via, pid))
            else:
                cx.execute("UPDATE precatorio SET cpf_cnpj=? WHERE id=?", (cpf_c, pid))
            cpfs += 1
    # credor mudou -> busca por nome (credor_norm + credor_fts) tem que acompanhar
    CN.sincroniza(cx, alterados)
    return nomes, cpfs, rejeitados


def main():
    import sqlite3
    db = os.path.join(BASE, "data", "alfred.db")
    with sqlite3.connect(db) as cx:
        nomes, cpfs, rej = enriquece(cx)
        cx.commit()
    print(f"Callix -> TJMG: {nomes} nomes repostos | {cpfs} CPFs preenchidos | {rej} rejeitados pela trava")


if __name__ == "__main__":
    main()
