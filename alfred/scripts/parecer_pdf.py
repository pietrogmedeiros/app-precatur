# -*- coding: utf-8 -*-
"""PDF do parecer da CONSULTA (rota GET /parecer_id/{id}/pdf).

Gera no servidor o mesmo parecer que a UI mostra, no formato "objetivo" aprovado
no caso Marianopolis (#3091): ficha -> 4 KPIs -> veredito -> a conta -> fichas de
apoio -> avisos. Motor reportlab = controle total do documento: rodape com
disclaimer + numeracao em TODA pagina, sem cabecalho de navegador, CPF ja vem
mascarado (ou nao) do alfred_core conforme o papel.

Entrada: o dict devolvido por alfred_core.parecer() (nenhum recalculo aqui).
Saida:   bytes do PDF.

Gotchas reportlab herdados dos pareceres anteriores: Helvetica/WinAnsi NAO tem
setas/estrelas (usar », ·, §, —); cor em <font> e' string "#RRGGBB"; cabecalho de
tabela como Paragraph para quebrar linha em vez de invadir a coluna vizinha.
"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

# paleta do manual Precatur (mesma da ui.html)
PETRO = colors.HexColor("#34474D")
PETRO2 = colors.HexColor("#2a3a3f")
CREME = colors.HexColor("#FCEADC")
CINZA = colors.HexColor("#5b6b78")
LINHA = colors.HexColor("#dde4e6")
FUNDO = colors.HexColor("#f4f7f7")
VERDE = colors.HexColor("#2d6a4f")
AMBAR = colors.HexColor("#9a5b00")
VERM = colors.HexColor("#9b2c2c")
DESTQ = colors.HexColor("#fff4d6")


def brl(v, dec=2):
    if v is None:
        return "—"
    s = f"{v:,.{dec}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"R$ {s}"


def pct(v, dec=2):
    if v is None:
        return "—"
    return f"{v:.{dec}f}%".replace(".", ",")


def brl_c(v):
    """Compacto p/ KPI ('R$ 18,6 mi') — o valor exato vai na linha de apoio."""
    if v is None:
        return "—"
    if abs(v) >= 1e6:
        return "R$ " + f"{v / 1e6:.1f}".replace(".", ",") + " mi"
    if abs(v) >= 1e3:
        return "R$ " + f"{v / 1e3:.1f}".replace(".", ",") + " mil"
    return brl(v)


def _data_br(s):
    return f"{s[8:10]}/{s[5:7]}/{s[0:4]}" if s and len(s) >= 10 else (s or "—")


def _esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _S(**k):
    return ParagraphStyle(**k)


st_tit = _S(name="tit", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=PETRO)
st_sub = _S(name="sub", fontName="Helvetica", fontSize=9, leading=12.5, textColor=CINZA)
st_h1 = _S(name="h1", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=PETRO,
           spaceBefore=12, spaceAfter=4)
st_p = _S(name="p", fontName="Helvetica", fontSize=9.5, leading=13.5, alignment=TA_JUSTIFY,
          spaceAfter=5)
st_note = _S(name="note", fontName="Helvetica", fontSize=8, leading=11, textColor=CINZA,
             alignment=TA_JUSTIFY, spaceAfter=4)
st_cell = _S(name="cell", fontName="Helvetica", fontSize=8, leading=10.5)
st_cellb = _S(name="cellb", fontName="Helvetica-Bold", fontSize=8, leading=10.5)
st_key = _S(name="key", fontName="Helvetica-Bold", fontSize=8.5, leading=11.5, textColor=PETRO)
st_val = _S(name="val", fontName="Helvetica", fontSize=8.5, leading=11.5)
st_head = _S(name="head", fontName="Helvetica-Bold", fontSize=7.4, leading=9,
             textColor=colors.white)
st_klab = _S(name="klab", fontName="Helvetica-Bold", fontSize=6.6, leading=8.6,
             textColor=colors.HexColor("#dfe8ea"), alignment=TA_CENTER)
st_knum = _S(name="knum", fontName="Helvetica-Bold", fontSize=15, leading=18,
             textColor=colors.white, alignment=TA_CENTER)
st_ksub = _S(name="ksub", fontName="Helvetica", fontSize=6.6, leading=8.6,
             textColor=colors.HexColor("#dfe8ea"), alignment=TA_CENTER)
st_klab2 = _S(name="klab2", fontName="Helvetica-Bold", fontSize=6.6, leading=8.6,
              textColor=colors.HexColor("#7c6647"), alignment=TA_CENTER)
st_knum2 = _S(name="knum2", fontName="Helvetica-Bold", fontSize=13, leading=17,
              textColor=colors.HexColor("#4a3a25"), alignment=TA_CENTER)
st_ksub2 = _S(name="ksub2", fontName="Helvetica", fontSize=6.6, leading=8.6,
              textColor=colors.HexColor("#7c6647"), alignment=TA_CENTER)


def _tabela(dados, larguras, extra=None, head=True):
    if head:
        dados = [[c if isinstance(c, Paragraph) else Paragraph(str(c), st_head)
                  for c in dados[0]]] + dados[1:]
    t = Table(dados, colWidths=larguras, repeatRows=1 if head else 0)
    cmds = [("GRID", (0, 0), (-1, -1), 0.4, LINHA),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if head:
        cmds.append(("BACKGROUND", (0, 0), (-1, 0), PETRO))
    t.setStyle(TableStyle(cmds + (extra or [])))
    return t


def _ficha(pares):
    linhas = [[Paragraph(k, st_key), Paragraph(v, st_val)] for k, v in pares]
    return _tabela(linhas, [42 * mm, 124 * mm], head=False,
                   extra=[("BACKGROUND", (0, 0), (0, -1), FUNDO)])


def _caixa(texto, cor=FUNDO, borda=PETRO):
    t = Table([[Paragraph(texto, st_p)]], colWidths=[166 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), cor),
                           ("LINEBEFORE", (0, 0), (0, -1), 2.2, borda),
                           ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def gerar(p):
    """dict do alfred_core.parecer() -> bytes do PDF."""
    pr, cr, dv = p["precatorio"], p["credor"], p["devedor"]
    f = p.get("fila") or {}
    j = p.get("projecao")
    g = p.get("pagamento")
    pl = p.get("plano_exercicio")
    ed = p.get("edital_acordo")
    ritmo = (j or {}).get("ritmo_observado")
    trib = _esc(pr.get("tribunal") or "—")
    numero = pr.get("numero_eproc_fmt") or pr.get("numero") or "—"
    coleta = _data_br(pr.get("coletado_em"))
    hoje = date.today().strftime("%d/%m/%Y")
    rat = (j or {}).get("rateio")
    a_frente = None
    if f.get("acumulado_sem_p20") is not None and pr.get("valor") is not None:
        a_frente = max(f["acumulado_sem_p20"] - pr["valor"], 0)
    tem_ritmo = bool(ritmo and ritmo.get("ano_previsto"))
    ritmo_n = (ritmo or {}).get("anos_media") or 0
    ritmo_desc = f"média dos últimos {ritmo_n} anos" if ritmo_n > 1 else "último ano medido"

    flow = []
    A = flow.append

    # ---------- titulo + ficha ----------
    A(Paragraph("PRECATUR — PARECER DE PRECATÓRIO", st_tit))
    A(Paragraph(f"Posição na fila e projeção de pagamento · emitido em {hoje} · "
                f"fila do {trib} coletada em {coleta}", st_sub))
    A(Spacer(1, 7))
    nat = _esc(pr.get("natureza") or "—")
    if pr.get("natureza") == "Alimentar":
        nat += " <font color='#7c6647' size='7.5'>(preferência sobre os comuns)</font>"
    pares = [
        ("Credor", _esc(cr.get("nome") or "não publicado pelo tribunal")
         + (f" · {_esc(cr['cpf_cnpj'])}" if cr.get("cpf_cnpj") else "")),
        ("Precatório", f"<b>{_esc(numero)}</b> — {trib}"),
        ("Ente devedor", f"{_esc(dv.get('ente') or '—')} — "
                         f"{_esc(dv.get('municipio') or '?')}/{_esc(dv.get('uf') or '?')} · "
                         f"regime <b>{_esc(dv.get('regime') or '—')}</b>"),
        ("Natureza / ano-orçamento", f"{nat} · <b>{_esc(pr.get('ano_orcamento') or '—')}</b>"),
        ("Valor na fila", f"<b>{brl(pr.get('valor'))}</b> <font color='#5b6b78' size='7.5'>"
                          f"— lista do {trib} em {coleta}</font>"),
    ]
    if f.get("e_superprecatorio"):
        pares.append(("Posição", (f"<b>{f['ordem']}ª de {f.get('n_total') or '—'}</b> na fila do "
                                  f"município · " if f.get("ordem") else "")
                                 + "superprecatório (art. 100 §20): disputa a ordem cronológica "
                                   "normalmente até chegar a vez dele, aí paga 15% à vista + 5 "
                                   "parcelas anuais de 17%"))
    elif f.get("ordem"):
        pares.append(("Posição", f"<b>{f['ordem']}ª de {f.get('n_total') or '—'}</b> na fila do "
                                 f"município · <b>{brl(a_frente)}</b> à frente"))
    if pr.get("numero_origem"):
        pares.append(("Processo de origem", _esc(pr["numero_origem"])))
    A(_ficha(pares))
    A(Spacer(1, 8))

    # ---------- 4 KPIs ----------
    def _kpi(lab, num, sub, claro=False):
        cell = [[Paragraph(lab, st_klab2 if claro else st_klab)],
                [Paragraph(num, st_knum2 if claro else st_knum)],
                [Paragraph(sub, st_ksub2 if claro else st_ksub)]]
        t = Table(cell, colWidths=[38.5 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CREME if claro else PETRO),
                               ("TOPPADDING", (0, 0), (-1, 0), 5),
                               ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
                               ("TOPPADDING", (0, 1), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, 1), 1)]))
        return t

    if j:
        k = []
        _fonte_orc = j.get("fonte_orcamento")
        _rot_orc = ("plano publicado pelo tribunal" if _fonte_orc == "oficial_valor"
                    else "SE PAGAR O LIMITE DA LEI")
        # devedor que paga a fila inteira no exercicio (Uniao no TRF2, INSS nos TJs, EMBASA)
        _exerc = _fonte_orc == "pago_no_exercicio"
        if _exerc:
            k.append(_kpi("PREVISÃO DE PAGAMENTO", str(j.get("ano_previsto") or "—"),
                          "paga a fila inteira no exercício do orçamento — sem teto do §23"))
        else:
            k.append(_kpi("SE PAGAR O PLANO OFICIAL" if _fonte_orc == "oficial_valor"
                          else "SE PAGAR O LIMITE DA LEI",
                          str(j.get("ano_previsto") or "—"),
                          f"gastando {brl(j.get('orcamento_anual'))}/ano"
                          + (f" — parcela do §23 ({round(rat['fracao'] * 100)}% do total)" if rat else
                             (" — valor anual do plano do tribunal" if _fonte_orc == "oficial_valor"
                              else f" — {pct(j.get('pct_p23'), 0)} da RCL"))))
        if _exerc:
            sub_ritmo = "não se aplica — não há teto anual a medir"
        elif f.get("e_superprecatorio"):
            sub_ritmo = "não se aplica — §20: paga 15% à vista + 5 parcelas anuais quando a fila chegar nele"
        elif ritmo and ritmo.get("pago_no_ano"):
            sub_ritmo = f"pagou {brl(ritmo.get('pago_no_ano'))}/ano ao {trib} ({ritmo_desc})"
        elif ritmo:
            sub_ritmo = f"não pagou nada ao {trib} no último ano medido"
        else:
            sub_ritmo = "sem dado de pagamento para este tribunal"
        k.append(_kpi("NO RITMO REAL", str(ritmo["ano_previsto"]) if tem_ritmo else "—", sub_ritmo))
        k.append(_kpi("À FRENTE NA FILA", brl_c(a_frente),
                      (brl(a_frente) + " · " if a_frente is not None else "")
                      + f"{(f.get('ordem') or '—')}ª de {f.get('n_total') or '—'}"
                      + (f" · não soma {f['n_superprecatorios']} superprec. §20"
                         if f.get("n_superprecatorios") else ""), claro=True))
        k.append(_kpi(f"PAGO PELO ENTE EM {g['ano_ref']}" if g else "PAGO PELO ENTE",
                      brl_c(g.get("pago_no_ano")) if g else "—",
                      (brl(g.get("pago_no_ano")) + " · todas as justiças (Mapa CNJ)")
                      if g else "sem dado do Mapa CNJ",
                      claro=True))
        kt = Table([k], colWidths=[41.5 * mm] * 4)
        kt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        A(kt)
        A(Spacer(1, 8))

    # ---------- veredito (mesmas regras da UI) ----------
    if j and tem_ritmo and ritmo["ano_previsto"] > j["ano_previsto"]:
        vtxt = (f"<b>Trabalhe com {ritmo['ano_previsto']}.</b> A projeção de {j['ano_previsto']} "
                f"supõe que o município gaste o orçamento legal ({brl(j['orcamento_anual'])}/ano"
                + (" — parcela do §23 desta justiça" if rat else "") + f"). Ele paga "
                f"<b>{brl(ritmo['pago_no_ano'])}</b>/ano ao {trib} ({ritmo_desc}).")
        vcor = AMBAR
    elif j and ritmo and not ritmo.get("ano_previsto"):
        vtxt = (f"<b>Sem ritmo observável.</b> O município não pagou <b>nada</b> ao {trib} no "
                f"último ano medido — {j['ano_previsto']} é só o cenário legal, sem comportamento "
                f"que o sustente. Trate como referência, não como previsão.")
        vcor = VERM
    elif j and tem_ritmo and ritmo["ano_previsto"] < j["ano_previsto"]:
        vtxt = (f"<b>Trabalhe com {j['ano_previsto']}.</b> O ente pagou "
                f"<b>{brl(ritmo['pago_no_ano'])}</b>/ano ao {trib} — {pct(ritmo.get('pct_do_teto'), 1)} "
                f"do limite —, o que daria {ritmo['ano_previsto']}. Mas esse histórico é anterior a "
                f"{j.get('exercicio_base')}, quando o percentual da RCL ainda não funcionava como teto "
                f"(EC 136/2025). <b>{ritmo['ano_previsto']} é o melhor caso, não a previsão.</b>")
        vcor = AMBAR
    elif j and tem_ritmo:
        vtxt = (f"O ritmo observado ({brl(ritmo['pago_no_ano'])}/ano ao {trib}) <b>sustenta</b> a "
                f"projeção de {j['ano_previsto']}.")
        vcor = VERDE
    else:
        vtxt = ""
        vcor = CINZA
    # camada regime/edital (faixa Siga/Pare da UI)
    especial = (dv.get("regime") or "").lower().startswith("espec")
    if ed and ed.get("aberto"):
        etxt = (f"<b>Pare e confira:</b> regime especial com <b>edital de acordo aberto</b> "
                f"({_esc(ed.get('edital'))}) — deságio de {ed.get('desagio_min_pct')}% a "
                f"{ed.get('desagio_max_pct')}%; inscrição até {_data_br(ed.get('inscricao_fecha'))}. "
                f"É a régua de preço que o credor conhece.")
        ecor = VERM
    elif ed:
        etxt = (f"Regime especial com edital {_esc(ed.get('edital'))} <b>já encerrado</b> — "
                f"confirme se o credor voltou para a fila antes de precificar (deságio praticado: "
                f"{ed.get('desagio_min_pct')}% a {ed.get('desagio_max_pct')}%).")
        ecor = AMBAR
    elif especial:
        etxt = ("Regime especial <b>sem edital de acordo publicado</b> — paga pela fila "
                "cronológica, mas é o tipo de ente que pode abrir edital.")
        ecor = AMBAR
    elif not dv.get("regime"):
        etxt = ("Regime do ente <b>não identificado</b> — não dá para afirmar se há edital de "
                "acordo concorrendo com a proposta. Confirme o regime antes de precificar.")
        ecor = AMBAR
    else:
        etxt = ("Regime geral e sem edital de acordo: o caminho é a fila cronológica, sem "
                "alternativa oficial concorrendo com a proposta.")
        ecor = VERDE
    if vtxt:
        A(_caixa(vtxt + "<br/><font size='8.5' color='#5b6b78'>" + etxt + "</font>", DESTQ, vcor))
    else:
        A(_caixa(etxt, FUNDO, ecor))
    A(Spacer(1, 4))

    # ---------- a conta ----------
    if j and a_frente is not None and j.get("orcamento_anual"):
        orc = j["orcamento_anual"]
        anos_fila = a_frente / orc if orc else None
        ano_simples = j.get("exercicio_base", 0) + int(anos_fila) if anos_fila is not None else None
        res20 = f.get("reserva_p20") or {}
        anos_res = sorted(res20)
        sufoca = any(res20[a2] > orc for a2 in anos_res)
        piso5 = (not sufoca and pr.get("ano_orcamento") and ano_simples
                 and ano_simples < pr["ano_orcamento"])
        A(Paragraph("A conta", st_h1))
        lc = [[Paragraph("", st_cell), Paragraph(f"<b>{brl(a_frente)}</b>", st_cell),
               Paragraph("que está à frente na fila", st_cell)],
              [Paragraph("÷", st_cell), Paragraph(brl(orc), st_cell),
               Paragraph("de orçamento por ano"
                         + (f" — parcela do §23 desta justiça ({round(rat['fracao'] * 100)}% do teto)"
                            if rat else " — teto do art. 100 §23"), st_cell)],
              [Paragraph("=", st_cell),
               Paragraph(f"{anos_fila:.2f}".replace(".", ",") + " ano", st_cell),
               Paragraph(f"a conta simples daria {ano_simples}", st_cell)]]
        if sufoca:
            lc.append([Paragraph("", st_cell),
                       Paragraph(f"−{brl(res20[anos_res[0]])}", st_cell),
                       Paragraph(f"mas {f.get('n_superprecatorios')} superprecatório(s) de "
                                 f"{brl(f.get('valor_superprecatorios'))} reservam isso já em "
                                 f"{anos_res[0]} (art. 100 §20) — mais que o orçamento anual", st_cell)])
        if piso5:
            lc.append([Paragraph("", st_cell), Paragraph(str(pr["ano_orcamento"]), st_cell),
                       Paragraph(f"mas o ano orçamentário do precatório é {pr['ano_orcamento']} — "
                                 f"o art. 100 §5º proíbe pagar antes disso", st_cell)])
        lc.append([Paragraph("»", st_cellb),
                   Paragraph(f"<b>{j.get('ano_previsto') or '—'}</b>", st_cellb),
                   Paragraph("<b>ano projetado pelo orçamento legal</b>"
                             + (f" · no ritmo real: <b>{ritmo['ano_previsto']}</b>"
                                if tem_ritmo else ""), st_cellb)])
        A(_tabela(lc, [8 * mm, 34 * mm, 124 * mm], head=False,
                  extra=[("ALIGN", (1, 0), (1, -1), "RIGHT"),
                         ("BACKGROUND", (0, len(lc) - 1), (-1, len(lc) - 1), DESTQ)]))
        A(Spacer(1, 2))

    # ---------- capacidade do devedor ----------
    A(Paragraph("Capacidade do devedor", st_h1))
    cap = [] if (j or {}).get("fonte_orcamento") == "pago_no_exercicio" else         [("Receita Corrente Líquida", brl(dv.get("rcl"))
          + " <font color='#5b6b78' size='7.5'>(SICONFI/Tesouro)</font>")]
    if f.get("estoque_municipio") is not None:
        cap.append((f"Fila deste tribunal ({trib})",
                    f"{brl(f['estoque_municipio'])} — {f.get('n_total') or '?'} precatórios, "
                    f"todos os exercícios"))
    if f.get("estoque_em_mora") is not None:
        cap.append(("Já venceu (cálculo próprio)",
                    f"{brl(f['estoque_em_mora'])} — {f.get('n_em_mora') or 0} precatório(s), "
                    f"{pct(f.get('mora_sobre_rcl_pct'))} da RCL"))
    if f.get("estoque_em_mora_oficial") is not None:
        cap.append(("Já venceu (número oficial)",
                    f"<b>{brl(f['estoque_em_mora_oficial'])}</b> — "
                    f"{pct(f.get('mora_oficial_sobre_rcl_pct'))} da RCL · "
                    f"{_esc(f.get('mora_oficial_fonte') or '')} — é este que define a faixa do §23"))
    mc = f.get("estoque_em_mora_mapa_cnj")
    if mc:
        cap.append(("Já venceu (Mapa Anual/CNJ)",
                    f"{brl(mc.get('saldo'))} — {pct(mc.get('sobre_rcl_pct'))} da RCL, "
                    f"saldo em 31/12/{mc.get('ano_ref')} · declarado pelo próprio {_esc(trib)}"))
    if j and j.get("fonte_orcamento") != "pago_no_exercicio":
        cap.append(("Teto anual do §23", f"{brl(j.get('teto_p23'))} — {pct(j.get('pct_p23'), 0)} "
                                         f"da RCL: o máximo que a lei permite pagar, não o que paga"))
        if rat:
            cap.append(("Rateio entre justiças",
                        " · ".join(f"{_esc(t['tribunal'])} {t['pct']}%" for t in rat["por_tribunal"])
                        + (" <font color='#5b6b78' size='7.5'>(provisório — Mapa CNJ)</font>"
                           if rat.get("fonte") == "mapa" else
                           " <font color='#5b6b78' size='7.5'>(pelas filas reais)</font>")))
    A(_ficha(cap))

    # ---------- o devedor paga? ----------
    if g and g.get("por_tribunal"):
        A(Paragraph(f"O devedor paga? — por tribunal em {g['ano_ref']} (Mapa Anual do CNJ)", st_h1))
        lt = [["Tribunal", "Devia na abertura", "Pagou no ano", "Ficou devendo", "Leitura"]]
        destaques = []
        for i, x in enumerate(g["por_tribunal"], start=1):
            meu = x.get("tribunal") == pr.get("tribunal")
            zero = (x.get("pago") or 0) == 0 and (x.get("saldo") or 0) > 0
            est = st_cellb if meu else st_cell
            if meu:
                destaques.append(("BACKGROUND", (0, i), (-1, i), CREME))
            lt.append([Paragraph(_esc(x.get("tribunal")) + (" (o seu)" if meu else ""), est),
                       Paragraph(brl(x.get("anterior")), est),
                       Paragraph(f"<font color='{'#9b2c2c' if zero else '#22303a'}'>"
                                 f"{brl(x.get('pago'))}</font>", est),
                       Paragraph(brl(x.get("saldo")), est),
                       Paragraph(_esc(x.get("texto") or ""), st_cell)])
        A(_tabela(lt, [24 * mm, 30 * mm, 30 * mm, 30 * mm, 52 * mm],
                  extra=[("FONTSIZE", (0, 1), (-1, -1), 7.6),
                         ("ALIGN", (1, 1), (3, -1), "RIGHT")] + destaques))
        A(Paragraph("Leia a linha do seu tribunal, não a média: o mesmo caixa atende todas as "
                    "justiças, e o ente escolhe quem paga.", st_note))
        hist = g.get("historico_anual") or []
        if len(hist) > 1:
            uniforme = all(a2.get("cobertura_uniforme") is not False for a2 in hist)
            lh = [["Ano", "Expedido no ano", "Pago no ano", "Saldo no fim", "Tribunais somados"]]
            for a2 in hist:
                lh.append([Paragraph(str(a2.get("ano_ref")), st_cell),
                           Paragraph(brl(a2.get("expedidos")), st_cell),
                           Paragraph(brl(a2.get("pago")), st_cell),
                           Paragraph(brl(a2.get("saldo")), st_cell),
                           Paragraph(_esc(" · ".join(a2.get("tribunais") or [])), st_cell)])
            A(Spacer(1, 3))
            A(_tabela(lh, [14 * mm, 34 * mm, 34 * mm, 34 * mm, 50 * mm],
                      extra=[("FONTSIZE", (0, 1), (-1, -1), 7.6),
                             ("ALIGN", (1, 1), (3, -1), "RIGHT")]))
            if not uniforme:
                A(Paragraph("<font color='#9b2c2c'><b>Não compare os anos entre si:</b> a cobertura "
                            "de tribunais muda entre as linhas.</font>", st_note))

    # ---------- plano do exercicio (quando ha) ----------
    if pl and (pl.get("valor_do_plano_no_ano") is not None or pl.get("conformidade")):
        A(Paragraph(f"Plano do exercício {pl.get('ano') or ''} — homologado pelo tribunal", st_h1))
        pp = []
        if pl.get("mora_oficial_1jan") is not None:
            pp.append(("Mora oficial em 1º/jan", brl(pl["mora_oficial_1jan"])))
        if pl.get("pct_aplicado") is not None:
            pp.append(("Faixa aplicada", f"{pl['pct_aplicado']}% da RCL"))
        if pl.get("valor_do_plano_no_ano") is not None:
            pp.append(("A pagar neste exercício", f"{brl(pl['valor_do_plano_no_ano'])} — desembolso "
                       f"do ano para zerar a mora, não o teto do §23"))
        cf = pl.get("conformidade")
        if cf:
            pp.append(("Está em dia?", _esc(cf.get("resumo") or "—")
                       + (f" · {cf['bloqueios_sisbajud_na_janela']} bloqueio(s) SISBAJUD"
                          if cf.get("bloqueios_sisbajud_na_janela") else "")))
        if pp:
            A(_ficha(pp))

    # ---------- avisos ----------
    avisos = p.get("avisos") or []
    if avisos:
        A(Paragraph("O que pode mudar essa resposta", st_h1))
        for a2 in avisos:
            A(Paragraph("• " + _esc(a2), st_p))

    # ---------- documento ----------
    buf = io.BytesIO()
    rod_esq = f"Parecer de precatório · {(cr.get('nome') or 'credor não publicado')} · {numero}"

    def _rodape(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINHA)
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(CINZA)
        canvas.drawString(20 * mm, 11 * mm, rod_esq[:110])
        canvas.drawRightString(190 * mm, 11 * mm, f"pág. {doc.page}")
        canvas.setFont("Helvetica-Oblique", 6.3)
        canvas.drawString(20 * mm, 7.8 * mm,
                          "Estimativas a partir da fila publicada e das premissas declaradas — não "
                          "constituem promessa de data de pagamento · uso interno; contém dado "
                          f"pessoal (LGPD) · gerado em {hoje}")
        canvas.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=20 * mm, rightMargin=20 * mm,
                          topMargin=16 * mm, bottomMargin=20 * mm,
                          title=f"Parecer — {numero} — {(cr.get('nome') or '')}".strip(" —"),
                          author="Precatur", subject="Posição na fila e projeção de pagamento")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=_rodape)])
    doc.build(flow)
    return buf.getvalue()
