# -*- coding: utf-8 -*-
"""Busca de precatorios no Alfred — apresentacao em TERMINAL.

  python scripts/db_busca.py 0003762-88.2024.8.08.0000   # nº de precatorio OU de origem
  python scripts/db_busca.py "IZIDORO DELUCA"            # nome do credor
  python scripts/db_busca.py 000.000.000-00              # CPF (mascarado na saida)
  python scripts/db_busca.py 000.000.000-00 --completo   # CPF sem mascara
  python scripts/db_busca.py --ente 407 --tribunal TJSP  # fila de um ente

Esta e' so a CAMADA DE APRESENTACAO. Consulta, projecao e mascaramento vivem em
scripts/alfred_core.py — o mesmo nucleo que a API usa, para que terminal e HTTP
nunca divirjam. A norma em si (§20/§23) esta em scripts/modelo_p23.py.
"""
import argparse
import importlib.util
import os
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# BASE resolvido a partir do proprio arquivo: funciona no Windows e na VM Linux.
# ALFRED_BASE sobrepoe quando o codigo roda de outro lugar.
BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
_spec = importlib.util.spec_from_file_location("alfred_core", os.path.join(BASE, "scripts", "alfred_core.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)


def brl(v):
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def num(v):
    return "—" if v is None else str(v).replace(".", ",")


def mostra(cx, r, completo=False):
    p = core.parecer(cx, r, completo=completo)
    pr, cr, dv = p["precatorio"], p["credor"], p["devedor"]

    print("=" * 78)
    print(f"  {pr['numero']}   [{pr['tribunal']}]")
    print("=" * 78)
    for k, v in [
        ("Credor", cr["nome"] or "— (tribunal não publica)"),
        ("CPF/CNPJ", cr["cpf_cnpj"] or "—"),
        ("Advogado", cr["advogado"] or "—"),
        ("Ente devedor", dv["ente"]),
        ("Município", f"{dv['municipio'] or '?'}/{dv['uf'] or '?'}"
                      + (f"  · regime {dv['regime']}" if dv["regime"] else "")),
        ("RCL do município", brl(dv["rcl"])),
        ("Processo de origem", pr["numero_origem"] or "—"),
        ("Natureza", pr["natureza"] or "—"),
        ("Ano orçamentário", pr["ano_orcamento"] or "—"),
        ("Superpreferência", pr["superpreferencia"] or "não"),
        ("Suspenso", "sim" if pr["suspenso"] else "não"),
        ("Valor", brl(pr["valor"])),
        ("Coletado em", (pr["coletado_em"] or "")[:10]),
    ]:
        print(f"  {k:<20} {v}")

    f = p.get("fila")
    if f:
        print("\n  POSIÇÃO NA FILA")
        print(f"  {'Ordem':<22} {f['ordem']}ª de {f['n_total']} (fila do município)")
        if f["acumulado_sem_p20"] is not None:
            print(f"  {'Acumulado à frente':<22} {brl(f['acumulado_sem_p20'])}   (fila normal, sem §20)")
            if f["n_superprecatorios"]:
                print(f"  {'':<22} {brl(f['acumulado_bruto'])}   (soma bruta — "
                      f"{f['n_superprecatorios']} superprecatório(s))")
        print(f"  {'Estoque do município':<22} {brl(f['estoque_municipio'])}")
        print(f"  {'Estoque em mora':<22} {brl(f['estoque_em_mora'])}  ({f['n_em_mora']} precatórios)")
        if f["mora_sobre_rcl_pct"] is not None:
            print(f"  {'Mora / RCL':<22} {num(f['mora_sobre_rcl_pct'])}%")

    pl = p.get("plano_exercicio")
    if pl:
        print(f"\n  PLANO DO EXERCÍCIO {pl['ano'] or ''}   (Comitê Gestor · art. 100 §23)")
        print(f"  {'Mora oficial 1º/jan':<22} {brl(pl['mora_oficial_1jan'])}")
        print(f"  {'Faixa aplicada':<22} {num(pl['pct_aplicado'])}% da RCL")
        print(f"  {'Plano a pagar no ano':<22} {brl(pl['valor_do_plano_no_ano'])}"
              f"   (≠ teto do §23 — é o desembolso do exercício)")
        rt = pl.get("rateio_por_justica")
        if rt:
            print(f"  {'Rateio por justiça':<22} TJ {num(rt['TJ'])}% · "
                  f"TRT {num(rt['TRT'])}% · TRF {num(rt['TRF'])}%")
        cf = pl.get("conformidade")
        if cf:
            print(f"  {'Está em dia?':<22} {cf['resumo']}")
            if cf["bloqueios_sisbajud_na_janela"]:
                print(f"  {'':<22} {cf['bloqueios_sisbajud_na_janela']} bloqueio(s) "
                      f"SISBAJUD na janela coletada")
        if pl.get("pa_fiscalizacao"):
            print(f"  {'Fonte':<22} PA {pl['pa_fiscalizacao']}"
                  + (f" · publicado {pl['publicado_em']}" if pl.get("publicado_em") else ""))

    g = p.get("pagamento")
    if g:
        print(f"\n  O ENTE ESTÁ PAGANDO?   ({g['fonte']}, {g['escopo']})")
        print(f"  {'Situação':<22} {g['resumo']}")
        print(f"  {'':<22} {'tribunal':<8} {'estoque abertura':>18} {'pago no ano':>16} "
              f"{'saldo':>16}")
        for x in g["por_tribunal"]:
            print(f"  {'':<22} {x['tribunal']:<8} {brl(x['anterior']):>18} "
                  f"{brl(x['pago']):>16} {brl(x['saldo']):>16}   {x['texto']}")

    j = p.get("projecao")
    if j:
        print("\n  PREVISÃO DE PAGAMENTO")
        print(f"  {'Ano previsto':<22} {j['ano_previsto']}   (cenário central; "
              f"fila zera em {j['fila_zera_em']})")
        print(f"  {'Orçamento anual':<22} {brl(j['orcamento_anual'])}  "
              f"— fonte: {j['fonte_orcamento']} · §23 = {num(j['pct_p23'])}%")
        if dv["regime"] == "Especial":
            for k in ("conservador", "central", "otimista"):
                print(f"  {'  ' + k:<22} {brl(j['banda'][k])}/ano → "
                      f"{j['ano_por_cenario'][k]}  (~{num(j['anos_de_orcamento'][k])} anos)")

    if p["avisos"]:
        print("\n  AVISOS")
        for a in p["avisos"]:
            print(f"  · {a}")


def fila_do_ente(cx, cd, tribunal, limite):
    rs = cx.execute(
        "SELECT * FROM precatorio_atual WHERE ente_id = "
        "(SELECT id FROM ente WHERE cd_externo = ? AND tribunal = ?) "
        "ORDER BY ordem LIMIT ?", (str(cd), tribunal, limite)).fetchall()
    if not rs:
        print("nada encontrado para esse ente/tribunal")
        return
    print(f"{rs[0]['ente_nome']}  [{tribunal}]  —  {len(rs)} primeiros")
    print(f"{'ord':>5}  {'processo':<26} {'nat':<10} {'ano':>5} {'valor':>16}  credor")
    for r in rs:
        print(f"{r['ordem'] or 0:>5}  {(r['numero_fmt'] or '')[:26]:<26} "
              f"{(r['natureza'] or '')[:10]:<10} {r['ano_orcamento'] or 0:>5} "
              f"{brl(r['valor']):>16}  {(core.mascara_cpf_no_texto(r['credor']) or '')[:34]}")


def main():
    ap = argparse.ArgumentParser(description="Busca de precatorios no banco do Alfred")
    ap.add_argument("termo", nargs="?", help="nº de processo, nome do credor ou CPF")
    ap.add_argument("--ente", help="cd_externo do ente (usar com --tribunal)")
    ap.add_argument("--tribunal", help="TJES|TJBA|TJRJ|TJAL|TJPE|TJSP|TJMG")
    ap.add_argument("--completo", action="store_true", help="mostra o CPF sem mascara")
    ap.add_argument("--limite", type=int, default=40)
    a = ap.parse_args()

    try:
        cx = core.conecta()
    except FileNotFoundError as e:
        sys.exit(str(e))

    if a.ente:
        fila_do_ente(cx, a.ente, (a.tribunal or "").upper(), a.limite)
        return
    if not a.termo:
        ap.error("informe um termo de busca ou --ente/--tribunal")

    rs, criterio = core.busca(cx, a.termo, a.limite)
    if not rs:
        print(f"nada encontrado para {a.termo!r} (busca por {criterio})")
        return
    print(f"{len(rs)} resultado(s) — busca por {criterio}\n")
    for r in rs:
        mostra(cx, r, completo=a.completo)
        print()


if __name__ == "__main__":
    main()
