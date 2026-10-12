# -*- coding: utf-8 -*-
"""Coletor da lista cronologica de precatorios do TJAP.

Descoberto em 2026-08-30. O levantamento anterior (29/08) apontava um painel
Power BI "publish to web" pro TJAP com um resourceKey que depois se provou ser
do TJAM (troca no levantamento). Pesquisa do zero em 30/08 mostrou que a pagina
institucional (www.tjap.jus.br/portal/precatorio-secretaria/precatorio-lista-
cronologica.html) MUDOU: hoje ela so' tem 3 links, um deles apontando pro
sistema PROPRIO do tribunal -- NAO e' Power BI:

    https://sig.tjap.jus.br/sgpe_control_lista_precatorios/

E' um app **ScriptCase** (RAD PHP que gera formulario+grid; o mesmo motor do
"grid_precatorio_saldos.php" e outros `sig.tjap.jus.br/*_grid_*` do portal).
Balde A por via obliqua: SEM captcha, SEM login, mas STATEFUL (cookie de sessao
+ csrf_token do form). Fluxo (confirmado ao vivo, requests puro basta --
Playwright NAO e' necessario):

  1. GET  /sgpe_control_lista_precatorios/
     -> cookies de sessao + form <F1> com <select name="entidade"> (18 entes)
        e campos ocultos (csrf_token, script_case_init, etc.)
  2. POST /sgpe_control_lista_precatorios/sgpe_control_lista_precatorios.php
     reenviando TODOS os campos ocultos do <F1> + entidade=<id> +
     nmgp_opcao=alterar (e' o que o JS do onChange do <select> seta)
     -> devolve um mini-HTML com <form name="Fredir"> contendo nmgp_parms
        (a clausula WHERE literal: "1=1 and fk_pessoas_precatorio_devedor =
        '<id>'") e um NOVO script_case_init.
  3. POST /sgpe_grid_lista_precatorios/sgpe_grid_lista_precatorios.php
     com os 3 campos do Fredir (nmgp_parms, nmgp_url_saida, script_case_init)
     -> devolve a pagina da GRID (100 linhas por pagina, HTML puro).
  4. POST no MESMO endpoint da grid, AJAX (X-Requested-With: XMLHttpRequest),
     body `nmgp_opcao=ajax_navigate&script_case_init=<o da grid>&
     opc=muda_qt_linhas&parm=50000` -> devolve JSON
     `{"setValue":[{"field":"sc_grid_body","value":"<html com TODAS as
     linhas>"}, ...]}`. Testado com o Estado (12.086 linhas) e Macapa (9.681)
     numa unica chamada -- nao precisa paginar de verdade.

Colunas da grid (SEM credor -- a coluna "nome"/"ano_lista"/"numero_proc_
origem" existe no CSS do painel mas nao e' renderizada, deve ser de uma view
administrativa): ordem, dt_ref_ordem (data/hora de autuacao), numero_proc_
precatorio_rp (CNJ), natureza (Alimenticia/Comum), prioridade (Idade-60 Anos/
Deficiencia/Doenca Grave/vazio), vl_requisitado, vl_pagar (saldo), vl_pago,
ano_vencimento (exercicio orcamentario), dt_ultimo_pagamento, status_pagamento
(PAGO/NAO PAGO/PARCIALMENTE PAGO/ACORDO DIRETO - PARCIALMENTE PAGO -- o FAQ da
propria pagina cita tambem "Preparando Pagamento", "Acordo Direto - Pago
Total" e "Suspenso", nao vistos nos entes testados).

GOTCHA de rede: o host `sig.tjap.jus.br` (atras de Cloudflare) da' HTTP 522 ou
reset de conexao esporadico -- nao e' geobloqueio nem WAF de verdade, e'
flakiness pura; retry com backoff resolve (visto tambem no TJTO/TJBA).

GOTCHA de sessao: os campos ocultos (csrf_token/script_case_init) do <F1> sao
por SESSAO, nao por requisicao -- da' pra reusar a mesma sessao pra varias
buscas de ente seguidas sem re-GET. Mesmo assim o coletor faz um GET novo por
ente (mais simples de raciocinar e o custo e' desprezivel: 18 entes).

Saida: data/tjap/<id>_<slug>.json {id_entidade, nome, total, precatorios[...]}
Uso:  python scripts/fetch_tjap.py            # todos os entes
      python scripts/fetch_tjap.py 13 21      # so' estes ids
"""
import html as htmlmod
import json
import os
import re
import sys
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

BASE_DIR = r"C:\Users\victo\Precatur\Alfred"
OUT = os.path.join(BASE_DIR, "data", "tjap")
ROOT = "https://sig.tjap.jus.br"
FORM_URL = ROOT + "/sgpe_control_lista_precatorios/"
FORM_ACTION = ROOT + "/sgpe_control_lista_precatorios/sgpe_control_lista_precatorios.php"
GRID_URL = ROOT + "/sgpe_grid_lista_precatorios/sgpe_grid_lista_precatorios.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DELAY = 0.4
QT_LINHAS = 50000    # maior que o maior ente observado (Estado, 12.086)
os.makedirs(OUT, exist_ok=True)

COLS = ["ordem", "dt_ref_ordem", "numero_proc_precatorio_rp", "natureza",
        "prioridade", "vl_requisitado", "vl_pagar", "vl_pago",
        "ano_vencimento", "dt_ultimo_pagamento", "status_pagamento"]
NOMES = ["ordem", "data_autuacao", "processo", "natureza", "prioridade",
         "valor_requisitado", "valor_a_pagar", "valor_pago",
         "ano_vencimento", "data_ultimo_pagamento", "situacao"]


def slugify(s):
    s = htmlmod.unescape(s or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower() or "ente"


def brl(s):
    """'237.934,56' -> 237934.56 ; '' / None -> None."""
    m = re.search(r"[-\d.,]+", s or "")
    if not m:
        return None
    t = m.group(0).replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _req(fn, *a, tries=5, **kw):
    last = None
    for i in range(tries):
        try:
            r = fn(*a, timeout=60, **kw)
            r.raise_for_status()
            return r
        except Exception as e:                                     # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError("requisicao falhou apos %d tentativas: %r" % (tries, last))


def novo_sessao():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def listar_entes(sess=None):
    sess = sess or novo_sessao()
    r = _req(sess.get, FORM_URL)
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form", {"name": "F1"})
    if not form:
        raise RuntimeError("form F1 nao encontrado -- pagina do TJAP mudou?")
    sel = form.find("select", {"name": "entidade"})
    entes = [(o.get("value"), htmlmod.unescape(o.get_text(strip=True)))
             for o in sel.find_all("option") if o.get("value")]
    return entes


def _hidden_fields(form):
    return {inp.get("name"): inp.get("value", "")
            for inp in form.find_all("input") if inp.get("name")}


def coletar_ente(entidade_id):
    """Devolve a lista de precatorios (todas as linhas) de um ente."""
    sess = novo_sessao()
    r1 = _req(sess.get, FORM_URL)
    soup1 = BeautifulSoup(r1.text, "lxml")
    form = soup1.find("form", {"name": "F1"})
    if not form:
        raise RuntimeError("form F1 nao encontrado")
    fields = _hidden_fields(form)
    fields.update({"entidade": str(entidade_id), "nmgp_opcao": "alterar",
                   "credor": "", "cpfcnpj_credor": ""})

    r2 = _req(sess.post, FORM_ACTION, data=fields, headers={"Referer": FORM_URL})
    soup2 = BeautifulSoup(r2.text, "lxml")
    fredir = soup2.find("form", {"name": "Fredir"})
    if not fredir:
        raise RuntimeError("form Fredir nao veio (busca do ente falhou)")
    grid_fields = _hidden_fields(fredir)

    r3 = _req(sess.post, GRID_URL, data=grid_fields, headers={"Referer": r2.url})
    m = re.search(r"script_case_init\s*=\s*['\"]?(\d+)", r3.text)
    if not m:
        # pode ser ente sem nenhum precatorio -- grid nao inicializa
        return []
    sci = m.group(1)

    ajax_body = {"nmgp_opcao": "ajax_navigate", "script_case_init": sci,
                 "opc": "muda_qt_linhas", "parm": str(QT_LINHAS)}
    r4 = _req(sess.post, GRID_URL, data=ajax_body,
              headers={"Referer": r3.url, "X-Requested-With": "XMLHttpRequest"})
    try:
        data = r4.json()
    except ValueError:
        raise RuntimeError("resposta do muda_qt_linhas nao e' JSON: %r" % r4.text[:200])
    body = next((e["value"] for e in data.get("setValue", [])
                 if e.get("field") == "sc_grid_body"), None)
    if not body:
        return []

    soup4 = BeautifulSoup(body, "lxml")
    linhas = []
    for tr in soup4.select("tr[id^=SC_ancor]"):
        vals = {}
        for c in COLS:
            span = tr.select_one("span[id^=id_sc_field_%s_]" % c)
            vals[c] = span.get_text(strip=True) if span else ""
        d = dict(zip(NOMES, (vals[c] for c in COLS)))
        d["valor_requisitado_num"] = brl(d["valor_requisitado"])
        d["valor_a_pagar_num"] = brl(d["valor_a_pagar"])
        d["valor_pago_num"] = brl(d["valor_pago"])
        try:
            d["ordem"] = int(d["ordem"].replace(".", ""))     # "1.000" = mil (ponto de milhar)
        except (TypeError, ValueError):
            pass
        linhas.append(d)
    return linhas


def main():
    entes = listar_entes()
    print("entes no TJAP: %d" % len(entes))
    filtro = set(sys.argv[1:])
    if filtro:
        entes = [e for e in entes if e[0] in filtro]
        print("filtrando p/ %s: %d ente(s)" % (sorted(filtro), len(entes)))

    feitos = {f.split("_")[0] for f in os.listdir(OUT) if f.endswith(".json")}
    for i, (eid, nome) in enumerate(entes, 1):
        if eid in feitos:
            continue
        try:
            precs = coletar_ente(eid)
        except Exception as e:                                     # noqa: BLE001
            print("  [%2d/%d] id=%-3s %-45s ERRO: %r"
                  % (i, len(entes), eid, nome[:45], e), flush=True)
            continue
        rec = {"id_entidade": eid, "nome": nome, "tribunal": "TJAP",
               "total": len(precs), "precatorios": precs}
        path = os.path.join(OUT, "%s_%s.json" % (eid, slugify(nome)))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1)
        soma_req = sum(p["valor_requisitado_num"] or 0 for p in precs)
        soma_pagar = sum(p["valor_a_pagar_num"] or 0 for p in precs)
        print("  [%2d/%d] id=%-3s %-45s %5d prec  requisitado R$ %s  a pagar R$ %s"
              % (i, len(entes), eid, nome[:45], len(precs),
                 "{:>14,.2f}".format(soma_req), "{:>14,.2f}".format(soma_pagar)), flush=True)
        time.sleep(DELAY)
    print("\nOK ->", OUT)


if __name__ == "__main__":
    main()
