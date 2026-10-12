# -*- coding: utf-8 -*-
"""Adiciona ao snapshot da LUP-TJES os entes que faltam — na pratica, o ESTADO DO
ESPIRITO SANTO e suas autarquias/empresas estaduais (DER-ES, DETRAN, IOPES, CESAN...).

O snapshot antigo (data/lup_tjes/) so tinha os 103 municipais; o Estado nunca entrou,
e por isso ~148 leads capixabas do funil (precatorios ESTADUAIS) nao casavam no Alfred.

Fonte: API JSON publica da LUP-TJES (mesma do RPA_RJ/es_lup_api):
  GET /lup/lup/entidades_devedoras
  GET /lup/lup/precatorios?cd_entidade_devedora=<cd>&fl_eh_ultima_importacao=S&size=<n>
DA 403 na VPS (WAF AWS bloqueia datacenter) — RODAR DE CASA (IP residencial).

Grava um arquivo por ente em data/lup_tjes/<cd>_<slug>.json no formato que o
db_build.ad_tjes ja consome (cd_entidade, nome_lup, precatorios=results crus).

Uso:
    python scripts/fetch_lup_estadual_es.py            # so os entes que faltam
    python scripts/fetch_lup_estadual_es.py --todos    # re-raspa a LUP inteira
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import re
import time
import unicodedata

import requests

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DEST = os.path.join(BASE, "data", "lup_tjes")
API = "https://sistemas.tjes.jus.br/lup"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Accept": "application/json", "Referer": "https://sistemas.tjes.jus.br/lup/f/"}
DELAY = 0.3
# federais/fora do ES que aparecem no dropdown mas nao sao devedores capixabas
EXCLUIR = {"INSS - INSTITUTO NACIONAL DO SEGURO SOCIAL",
           "UNITINS - UNIVERSIDADE ESTADUAL DO TOCANTINS",
           "MUNICIPIO DE MATIPO", "MUNICIPIO DE SAO JOAO NEPOMUCENO"}


def norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().strip()


def slug(s):
    s = norm(s).lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s)).strip("_")[:50]


def get(url, params=None, tries=4):
    last = None
    for a in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=90)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa
            last = e; time.sleep(DELAY * (a + 2))
    raise RuntimeError(f"falhou {url}: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="re-raspa todos os entes (nao so os que faltam)")
    a = ap.parse_args()

    ents = get(f"{API}/lup/entidades_devedoras")
    ents = ents if isinstance(ents, list) else ents.get("data", [])
    print(f"entes no dropdown da LUP: {len(ents)}")

    ja = set()
    for f in glob.glob(os.path.join(DEST, "*.json")):
        try:
            ja.add(str(json.load(open(f, encoding="utf-8")).get("cd_entidade")))
        except Exception:
            pass
    print(f"entes ja no snapshot: {len(ja)}")

    alvos = []
    for e in ents:
        nome = e.get("de_nome_entidade", "")
        if norm(nome) in EXCLUIR:
            continue
        if not a.todos and str(e.get("cd_entidade")) in ja:
            continue
        alvos.append(e)
    print(f"entes a raspar: {len(alvos)}")

    os.makedirs(DEST, exist_ok=True)
    n_ent = n_prec = 0
    for i, e in enumerate(alvos, 1):
        cd = e["cd_entidade"]; nome = e.get("de_nome_entidade", "")
        try:
            d = get(f"{API}/lup/precatorios",
                    params={"cd_entidade_devedora": cd, "fl_eh_ultima_importacao": "S", "size": 10000})
        except RuntimeError as err:
            print(f"  [{i}/{len(alvos)}] cd={cd} {nome[:46]:46s}  ERRO: {str(err)[-40:]}")
            continue
        results = d.get("results", []) if isinstance(d, dict) else []
        total = d.get("total") if isinstance(d, dict) else None
        aviso = "  <<< TRUNCADO (total>%s)" % len(results) if total and total > len(results) else ""
        print(f"  [{i}/{len(alvos)}] cd={cd} {nome[:46]:46s} {len(results):>5} prec{aviso}")
        if not results:
            time.sleep(DELAY); continue
        out = {"cd_entidade": cd, "nome_lup": nome,
               "total": d.get("total"), "precatorios": results}
        with open(os.path.join(DEST, f"{cd}_{slug(nome)}.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
        n_ent += 1; n_prec += len(results)
        time.sleep(DELAY)

    print(f"\ngravados: {n_ent} entes | {n_prec} precatorios em {DEST}")


if __name__ == "__main__":
    main()
