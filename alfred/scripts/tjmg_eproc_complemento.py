# -*- coding: utf-8 -*-
"""Completa o "N. Eproc 2G" que a base RPA (snapshot 2026-07-30) nao trouxe.

Na data do snapshot o TJMG ainda nao tinha dado o CNJ de 2a instancia a ~2,3 mil
precatorios recem-expedidos (a base diz "Nao consta n Eproc"). Hoje o site ja mostra
o numero -- e e ele que o comercial cola na busca (card #6203: precatorio 21668 do
Estado de MG, eproc 2017573-72.2026.8.13.0000, nao era achado).

Fonte: consultaPorEntidadeDevedora.jsf (mesma do tjmg_epd_scraper.py), Ocultar
Fechados = Sim. A LISTA ja traz a coluna "N Eproc 2G": nao precisa expandir linha.
So raspa os entes que tem algum precatorio sem eproc na base RPA.

Saida: data/tjmg/eproc_complemento.json
  {"coletado_em": ..., "entes": {"<ente>": {"<num>": "<20 digitos>", ...}}, "falhas": [...]}
tjmg_stage.py usa o complemento so quando a base RPA nao tem o eproc.

Uso:
    python scripts/tjmg_eproc_complemento.py           # resumavel (pula ente ja feito)
    python scripts/tjmg_eproc_complemento.py --refaz   # comeca do zero
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import unicodedata

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
sys.path.insert(0, os.path.join(BASE, "scripts"))
from tjmg_stage import FONTES, chave_num, col, dig  # noqa: E402

URL = "https://www8.tjmg.jus.br/juridico/pe/consultaPorEntidadeDevedora.jsf"
SAIDA = os.path.join(BASE, "data", "tjmg", "eproc_complemento.json")


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def faltantes():
    """ente (label do site, como na base RPA) -> {chave_num} sem eproc."""
    out = {}
    for f in FONTES:
        df = pd.read_excel(f)
        c_ente, c_num, c_ep = col(df, "ente"), col(df, "precat"), col(df, "eproc")
        for _, r in df.iterrows():
            if len(dig(r[c_ep])) == 20:
                continue
            ente = str(r[c_ente]).strip()
            if ente and ente.lower() != "nan":
                out.setdefault(ente, set()).add(chave_num(r[c_num]))
    return out


def _abrir(pg):
    for t in range(4):
        try:
            pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_selector("#entidade_devedora_input", state="visible", timeout=20000)
            return True
        except Exception:
            pg.wait_for_timeout(5000 * (t + 1))
    return False


def _seleciona(pg, ente):
    """Digita o comeco do nome no autocomplete e clica a sugestao IDENTICA ao ente."""
    alvo = norm(ente)
    for q in (ente[:30], ente[:18], ente[:10]):
        if not _abrir(pg):
            return False
        inp = pg.locator("#entidade_devedora_input")
        inp.click()
        inp.fill("")
        inp.press_sequentially(q, delay=90)
        try:
            pg.wait_for_selector("#entidade_devedora_panel li", state="visible", timeout=15000)
        except Exception:
            continue
        pg.wait_for_timeout(500)
        sug = pg.locator("#entidade_devedora_panel li").all_inner_texts()
        idx = next((i for i, s in enumerate(sug) if norm(s) == alvo), None)
        if idx is not None:
            pg.locator("#entidade_devedora_panel li").nth(idx).click()
            pg.wait_for_timeout(600)
            return True
    return False


_JS_LINHAS = """() => {
  const ths = Array.from(document.querySelectorAll('#resultado thead th')).map(t => t.innerText.trim());
  const rows = Array.from(document.querySelectorAll('#resultado tbody tr[data-ri]'))
                    .map(tr => Array.from(tr.children).map(td => td.innerText.trim()));
  const cur = (document.querySelector('#resultado .ui-paginator-current') || {}).innerText || '';
  return {ths, rows, cur};
}"""


def _maior_rpp(pg):
    """Se a tabela deixa escolher linhas por pagina, pega a maior (menos paginas)."""
    sel = pg.query_selector("#resultado select.ui-paginator-rpp-options")
    if not sel:
        return
    vals = [int(v) for v in pg.evaluate("s => Array.from(s.options).map(o => o.value)", sel) if str(v).isdigit()]
    if vals and max(vals) > 15:
        sel.select_option(str(max(vals)))
        pg.wait_for_timeout(2500)


def consulta_ente(pg, ente):
    """{chave_num: eproc} de todos os pendentes do ente no site (None se nao achou o ente)."""
    if not _seleciona(pg, ente):
        return None
    pg.locator("#ocultaFechados").click()
    pg.wait_for_selector("#ocultaFechados_panel li", state="visible")
    pg.locator("#ocultaFechados_panel li", has_text=re.compile(r"^Sim$")).first.click()
    pg.wait_for_timeout(400)
    pg.locator("#consulta2").click()
    try:
        pg.wait_for_function(r"() => /Total de \d+ precat|Nenhum/.test(document.body.innerText)", timeout=120000)
    except Exception:
        return None
    pg.wait_for_timeout(800)
    _maior_rpp(pg)
    out, vistos, pagina = {}, set(), 0
    while True:
        d = pg.evaluate(_JS_LINHAS)
        ths = d["ths"]
        i_num = next((i for i, h in enumerate(ths) if "Precat" in h), None)
        i_ep = next((i for i, h in enumerate(ths) if "Eproc" in h), None)
        if i_num is None or i_ep is None:
            return out
        for c in d["rows"]:
            if len(c) > max(i_num, i_ep):
                ep = dig(c[i_ep])
                if len(ep) == 20:
                    out[chave_num(c[i_num])] = ep
        if d["cur"] in vistos:            # pagina nao avancou: fim (ou travou)
            break
        vistos.add(d["cur"])
        nxt = pg.query_selector("#resultado_paginator_bottom .ui-paginator-next") or \
            pg.query_selector(".ui-paginator-next")
        if not nxt or "ui-state-disabled" in (nxt.get_attribute("class") or ""):
            break
        nxt.click()
        pagina += 1
        try:
            pg.wait_for_function("c => ((document.querySelector('#resultado .ui-paginator-current') || {}).innerText"
                                 " || '') !== c", arg=d["cur"], timeout=60000)
        except Exception:
            break
        pg.wait_for_timeout(300)
    return out


def main():
    from playwright.sync_api import sync_playwright

    falta = faltantes()
    print(f"entes com eproc faltando na base RPA: {len(falta)} | precatorios: {sum(map(len, falta.values()))}",
          flush=True)
    res = {"fonte": URL, "coletado_em": None, "entes": {}, "falhas": []}
    if os.path.exists(SAIDA) and "--refaz" not in sys.argv:
        res = json.load(open(SAIDA, encoding="utf-8"))
        res["falhas"] = []
    # menores primeiro: mostra cedo se o fluxo funciona; o Estado de MG (16 mil) fica por ultimo
    ordem = sorted(falta, key=lambda e: (e == "ESTADO DE MINAS GERAIS", len(falta[e])))
    pend = [e for e in ordem if e not in res["entes"]]

    def salva():
        res["coletado_em"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        tmp = SAIDA + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=0)
        os.replace(tmp, SAIDA)

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.set_default_timeout(60000)
        for k, ente in enumerate(pend, 1):
            if k % 30 == 0:                # navegador novo de tempos em tempos (lote longo degrada)
                b.close()
                b = p.chromium.launch(headless=True)
                pg = b.new_page()
                pg.set_default_timeout(60000)
            t0 = time.time()
            try:
                got = consulta_ente(pg, ente)
            except Exception as e:
                got = None
                print(f"  erro: {str(e)[:100]}", flush=True)
                pg.close()
                pg = b.new_page()
                pg.set_default_timeout(60000)
            if got is None:
                res["falhas"].append(ente)
                print(f"[{k}/{len(pend)}] {ente[:50]:50s} FALHOU", flush=True)
                continue
            res["entes"][ente] = got
            ach = len(falta[ente] & set(got))
            print(f"[{k}/{len(pend)}] {ente[:50]:50s} site {len(got):5d} | faltavam {len(falta[ente]):4d} "
                  f"achados {ach:4d} | {time.time() - t0:.0f}s", flush=True)
            salva()
    salva()
    tot = sum(len(falta[e] & set(res["entes"].get(e, {}))) for e in falta)
    print(f"\nFIM. eproc recuperado p/ {tot} de {sum(map(len, falta.values()))} | falhas: {len(res['falhas'])}",
          flush=True)


if __name__ == "__main__":
    main()
