# -*- coding: utf-8 -*-
"""Atos do Nucleo de Precatorios (NACP) -> tabelas `nacp_plano` e `nacp_ato`.

  python scripts/db_nacp.py                 # (re)carrega no banco existente
  python scripts/db_nacp.py --resumo
  python scripts/db_nacp.py --ibge 2919207

Fonte: data/djen_nacp_<uf>.json, coletado por scripts/fetch_djen_nacp.py.
Este modulo so carrega e interpreta.

------------------------------------------------------------------------------
POR QUE ISTO EXISTE (e por que nao da' para usar o Mapa do CNJ no lugar)

O Mapa Anual do CNJ responde "quanto o ente pagou no ano passado". Ele NAO
responde as duas perguntas que o time comercial faz de verdade:

    1. Quanto o ente DEVE PAGAR este ano?      -> plano anual do Comite Gestor
    2. Ele esta EM DIA com esse plano AGORA?   -> certidao de regularidade

E ha uma armadilha entre as duas fontes, que ja custou uma analise errada:

    CNJ, "saldo devedor" de Lauro de Freitas/BA (fim de 2025)  R$ 4.729.331,49
    Comite Gestor, mora em 1o/jan/2026 do mesmo ente           R$    53.756,15

Os dois estao certos e medem coisas diferentes. O §23 da EC 136/2025 manda usar
o "estoque de precatorios EM MORA, atualizado, em 1o de janeiro" — so o que ja
venceu o prazo do art. 100 §5o. O saldo do CNJ inclui divida ainda DENTRO do
prazo. Confundir os dois superestima a mora em ~88x e faz o modelo projetar uma
fila represada que nao existe. Por isso a mora oficial vira coluna propria aqui,
nunca sobrescreve nada do Mapa, e as duas fontes convivem lado a lado.

O GRAO e' (ano, ente): o plano e' anual e reenquadrado todo 1o de janeiro, entao
2027 entra ao lado de 2026 em vez de sobrescrever.

Um unico despacho do Comite Gestor traz a tabela do ESTADO INTEIRO (148 entes na
BA em 2026) e e' republicado no PA de Fiscalizacao de cada municipio — por isso
o coletor deduplica por ano antes de gravar.
"""
import argparse
import json
import os
import pathlib
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
DB = os.path.join(BASE, "data", "alfred.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS nacp_plano (
  ano            INTEGER NOT NULL,     -- exercicio do plano (reenquadra todo 1o/jan)
  uf             TEXT NOT NULL,
  tribunal       TEXT NOT NULL,        -- tribunal que fiscaliza (TJBA, ...)
  ibge           TEXT,                 -- NULL em autarquia/empresa estatal
  devedor        TEXT NOT NULL,        -- nome como sai no despacho
  mora_1jan      REAL,                 -- estoque EM MORA em 1o/jan (base do §23)
  pct_aplicado   REAL,                 -- faixa do §23 aplicada (1,0 .. 5,0)
  valor_anual    REAL,                 -- teto/plano de pagamento do exercicio
  rateio_tj      REAL,
  rateio_trt     REAL,
  rateio_trf     REAL,
  fonte_pa       TEXT,                 -- PA de Fiscalizacao onde saiu
  fonte_data     TEXT,
  fonte_id_djen  INTEGER,
  PRIMARY KEY (ano, uf, devedor)
);

CREATE TABLE IF NOT EXISTS nacp_ato (
  id_djen    INTEGER PRIMARY KEY,      -- id da publicacao: dedup natural
  tipo       TEXT NOT NULL,            -- certidao_regular | certidao_irregular
                                       -- | bloqueio_sisbajud | relacao_orcamento
  data       TEXT NOT NULL,
  uf         TEXT NOT NULL,
  tribunal   TEXT NOT NULL,
  ibge       TEXT,
  ente       TEXT,
  pa         TEXT,
  situacao   TEXT,                     -- REGULAR | IRREGULAR (so em certidao)
  ano_plano  INTEGER,
  ano_orcamento INTEGER
);

CREATE INDEX IF NOT EXISTS ix_nacp_plano_ibge ON nacp_plano(ibge);
CREATE INDEX IF NOT EXISTS ix_nacp_ato_ibge   ON nacp_ato(ibge, data);
"""


# --------------------------------------------------------------- carga
def carrega(cx, uf=None):
    """Carrega data/djen_nacp_<uf>.json. Sem uf, carrega todos os que existirem."""
    cx.executescript(SCHEMA)
    pasta = pathlib.Path(BASE) / "data"
    alvos = ([pasta / f"djen_nacp_{uf.lower()}.json"] if uf
             else sorted(pasta.glob("djen_nacp_*.json")))
    n_plano = n_ato = 0
    for fn in alvos:
        if not fn.exists():
            print(f"  (!) {fn} nao existe — pule ou rode fetch_djen_nacp.py")
            continue
        d = json.load(open(fn, encoding="utf-8"))
        u, trib = d["uf"], d["tribunal"]

        for chave, bloco in (d.get("tabela_p23") or {}).items():
            ano = bloco.get("ano") or int(chave)
            f = bloco.get("fonte") or {}
            for e in bloco.get("entes") or []:
                r = e.get("rateio") or {}
                cx.execute(
                    "INSERT OR REPLACE INTO nacp_plano (ano, uf, tribunal, ibge, devedor,"
                    " mora_1jan, pct_aplicado, valor_anual, rateio_tj, rateio_trt, rateio_trf,"
                    " fonte_pa, fonte_data, fonte_id_djen)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ano, u, trib, e.get("ibge"), e["devedor"], e.get("mora_1jan"),
                     e.get("pct_aplicado"), e.get("valor_anual"), r.get("TJ"), r.get("TRT"),
                     r.get("TRF"), f.get("pa"), f.get("data"), f.get("id_djen")))
                n_plano += 1

        for a in d.get("atos") or []:
            cx.execute(
                "INSERT OR REPLACE INTO nacp_ato (id_djen, tipo, data, uf, tribunal, ibge,"
                " ente, pa, situacao, ano_plano, ano_orcamento) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (a.get("id_djen"), a["tipo"], a["data"], u, trib, a.get("ibge"),
                 a.get("ente"), a.get("pa"), a.get("situacao"), a.get("ano_plano"),
                 a.get("ano_orcamento")))
            n_ato += 1
    # Correcoes pontuais: o DJEN publica a planilha do NACP num instante; o tribunal pode
    # retificar depois (ex.: RCL corrigida -> percentual muda). data/nacp_correcoes.csv
    # traz o valor vigente com a fonte, e vence o registro do DJEN.
    pc = pathlib.Path(BASE) / "data" / "nacp_correcoes.csv"
    if pc.exists():
        import csv
        for r in csv.DictReader(open(pc, encoding="utf-8-sig")):
            cx.execute("UPDATE nacp_plano SET pct_aplicado=?, valor_anual=? "
                       "WHERE uf=? AND ibge=? AND ano=?",
                       (float(r["pct_aplicado"]), float(r["valor_anual"]),
                        r["uf"], r["ibge"], int(r["ano"])))
    cx.commit()
    return n_plano, n_ato


def existe(cx):
    return bool(cx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nacp_plano'").fetchone())


# --------------------------------------------------------------- consulta
def plano(cx, ibge, ano=None):
    """Plano anual vigente do ente (o mais recente, ou de um ano especifico)."""
    if not existe(cx):
        return None
    q = "SELECT * FROM nacp_plano WHERE ibge = ?"
    p = [ibge]
    if ano:
        q += " AND ano = ?"
        p.append(ano)
    q += " ORDER BY ano DESC LIMIT 1"
    r = cx.execute(q, p).fetchone()
    return dict(r) if r else None


def conformidade(cx, ibge):
    """Ultimo sinal de que o ente esta (ou nao) em dia com o plano.

    Ordena por data e devolve o ato mais recente entre certidao e bloqueio — um
    bloqueio SISBAJUD posterior a uma certidao REGULAR significa que o ente
    voltou a atrasar, e e' isso que precisa aparecer para quem consulta.
    """
    if not existe(cx):
        return None
    rs = cx.execute(
        "SELECT tipo, data, situacao, ano_plano, pa FROM nacp_ato"
        " WHERE ibge = ? AND tipo IN ('certidao_regular','certidao_irregular','bloqueio_sisbajud')"
        " ORDER BY data DESC LIMIT 12", (ibge,)).fetchall()
    if not rs:
        return None
    ult = dict(rs[0])
    bloqueios = [dict(r) for r in rs if r["tipo"] == "bloqueio_sisbajud"]
    certidoes = [dict(r) for r in rs if r["tipo"].startswith("certidao")]
    if ult["tipo"] == "bloqueio_sisbajud":
        codigo, texto = "bloqueio", (
            f"houve bloqueio SISBAJUD em {ult['data']} — sinal de atraso no plano")
    elif ult.get("situacao") == "REGULAR":
        codigo, texto = "regular", (
            f"certidao de {ult['data']}: REGULAR no Plano de Pagamento"
            + (f" de {ult['ano_plano']}" if ult.get("ano_plano") else ""))
    else:
        codigo, texto = "irregular", f"certidao de {ult['data']}: IRREGULAR"
    return {"codigo": codigo, "texto": texto, "em": ult["data"], "pa": ult.get("pa"),
            "ultima_certidao": certidoes[0] if certidoes else None,
            "ultimo_bloqueio": bloqueios[0] if bloqueios else None,
            "n_bloqueios_12m": len(bloqueios)}


def _brl(v):
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def resumo(cx):
    if not existe(cx):
        print("nacp_plano ainda nao existe — rode a carga.")
        return
    print("PLANOS §23 (Comite Gestor):")
    for r in cx.execute("SELECT ano, uf, COUNT(*) n, SUM(ibge IS NOT NULL) com_ibge,"
                        " SUM(valor_anual) tot FROM nacp_plano GROUP BY ano, uf"):
        print(f"  {r['ano']} {r['uf']}: {r['n']} entes ({r['com_ibge']} com IBGE)"
              f" · plano somado {_brl(r['tot'])}")
    print("ATOS:")
    for r in cx.execute("SELECT uf, tipo, COUNT(*) n, MIN(data) de, MAX(data) ate"
                        " FROM nacp_ato GROUP BY uf, tipo ORDER BY uf, n DESC"):
        print(f"  {r['uf']} {r['tipo']:<20} {r['n']:>4}  ({r['de']} .. {r['ate']})")


def mostra(cx, ibge):
    p = plano(cx, ibge)
    c = conformidade(cx, ibge)
    m = cx.execute("SELECT nome, uf, rcl FROM municipio WHERE ibge = ?", (ibge,)).fetchone()
    print(f"{(m['nome'] + '/' + m['uf']) if m else ibge}")
    if p:
        print(f"  PLANO {p['ano']} ({p['tribunal']})")
        print(f"    mora em 1o/jan     {_brl(p['mora_1jan'])}")
        print(f"    faixa §23          {p['pct_aplicado']}% da RCL")
        print(f"    plano do exercicio {_brl(p['valor_anual'])}")
        print(f"    rateio             TJ {p['rateio_tj']}% · TRT {p['rateio_trt']}%"
              f" · TRF {p['rateio_trf']}%")
        if m and m["rcl"]:
            print(f"    teto de {p['pct_aplicado']}% da RCL = {_brl(m['rcl'] * p['pct_aplicado'] / 100)}"
                  f"  (o plano usa o MENOR entre teto e mora)")
        print(f"    fonte              PA {p['fonte_pa']} · {p['fonte_data']}")
    else:
        print("  sem plano §23 carregado para este ente")
    print(f"  CONFORMIDADE: {c['texto'] if c else 'sem ato do NACP no periodo coletado'}")
    if c and c["n_bloqueios_12m"]:
        print(f"    bloqueios SISBAJUD na janela: {c['n_bloqueios_12m']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf")
    ap.add_argument("--resumo", action="store_true")
    ap.add_argument("--ibge")
    a = ap.parse_args()
    cx = sqlite3.connect(DB)
    cx.row_factory = sqlite3.Row
    try:
        if a.ibge:
            mostra(cx, a.ibge)
        elif a.resumo:
            resumo(cx)
        else:
            np, na = carrega(cx, a.uf)
            print(f"carregado: {np} linhas de plano, {na} atos")
            resumo(cx)
    finally:
        cx.close()


if __name__ == "__main__":
    main()
