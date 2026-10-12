# -*- coding: utf-8 -*-
"""Modelo de ORCAMENTO ANUAL de precatorios — art. 100 §23 (EC 136/2025).

Modulo compartilhado: substitui o "orcamento = 1% da RCL" fixo que estava espalhado
pelos scripts (build_deliverables.PCT_RCL_NOVO, parecer_orly, projecoes) por uma regra
derivada do dado, valida para REGIME GERAL e REGIME ESPECIAL.

------------------------------------------------------------------------------
1. O QUE A EC 136/2025 MUDOU
   O §23 virou TETO anual (nao piso), calculado sobre o ESTOQUE EM MORA atualizado
   em 1o de janeiro do exercicio, com REENQUADRAMENTO ANUAL. "Em mora" = precatorio
   cujo ano-orcamento JA VENCEU; precatorio do exercicio corrente ou futuro nao entra.
   Ver memoria [[p23-percentual-derivavel-faixa]] e [[pa-fiscalizacao-tjba-p23-ec136]].

2. A ESCADA (percentual por faixa de mora/RCL)
   Degraus 1,0 / 1,5 / 2,0 / 2,5 / 3,0 / 3,5% observados na planilha do NACP/TJBA.
   Ancoragem no dado oficial de MG (data/enquadramento_definitivo.csv, 854 entes):
     - inciso I -> 1,00% : mora/RCL observada de 0,00% ate 13,33%
     - 1,50%             : primeira ocorrencia em 15,50%, ultima em 23,90%
     - 2,00%             : unico caso (Corrego Danta, mora 18,48% MAS DCL/RCL 27,82%)
   => o corte 1,0->1,5 fica entre 13,33% e 15,50%, coerente com os 15% da norma.
   LIMITE CONHECIDO: acima de ~24% a escada aqui e' EXTRAPOLADA (nao ha amostra em MG),
   e o caso de Corrego Danta mostra que a Divida Consolidada Liquida tambem pesa no
   enquadramento — a funcao abaixo NAO modela isso. Onde houver percentual oficial
   (MG: enquadramento; BA: PA de Fiscalizacao do NACP), o oficial PREVALECE.

3. REGIME ESPECIAL NAO E' OUTRA MATEMATICA — E' OUTRO PATAMAR
   O §23 se aplica igualmente aos entes RE: no proprio enquadramento do TJMG, o Estado
   de Minas Gerais (RE) recebe inciso I / 1,00%, e Cana Verde, Lajinha, Ipatinga,
   Santa Rita do Sapucai e Iguatama (todos RE) tem percentual atribuido normalmente.
   O que difere e' o PATAMAR DE PAGAMENTO observado. Medido sobre 738 municipios com
   RCL + Mapa Anual CNJ ref. 2025:
       regime    n     pago/RCL mediana   media    p90     saldo/RCL mediana
       Comum    599         0,17%         0,42%   1,09%          0,21%
       Especial 139         1,33%         1,92%   3,86%          3,95%
   E, dentro dos especiais, o pagamento acompanha a faixa — em multiplo do teto:
       escada 1,0%  (n=114)  pagam mediana 1,30%   (~1,3x)
       escada 1,5%  (n=10)   pagam mediana 3,54%   (~2,4x)
       escada 2,0%  (n=3)    pagam mediana 4,54%   (~2,3x)
   Faz sentido: o regime especial do ADCT art. 101 obriga a liquidar o estoque em
   prazo determinado, o que exige percentual acima do teto do §23.

4. COMO ESCOLHER O ORCAMENTO (funcao orcamento_anual)
   Ordem de preferencia das fontes, da mais forte para a mais fraca:
     a) 'oficial'   - percentual homologado do ente (MG enquadramento / BA PA NACP)
     b) 'observado' - pago no ano de referencia do Mapa Anual CNJ, quando > 0
     c) 'teto_p23'  - escada aplicada a mora/RCL
   Para regime COMUM (a) e (c) praticamente coincidem. Para ESPECIAL, (b) costuma ser
   2-3x (c) — usar so o teto subestima muito o ritmo real.
   ATENCAO TEMPORAL: o Mapa Anual ref. 2025 e' ANTERIOR a EC 136 (09/09/2025, valendo
   para o EF 2026). Se a EC 136 passar a limitar tambem os entes RE, o ritmo observado
   em 2025 nao se repete. Por isso projecao_cenarios() devolve uma BANDA, nunca um
   numero unico, para entes em regime especial.
"""
import re
from collections import defaultdict

# Escada do art. 100 §23, incisos I a IX, na redacao da EC 136/2025 — conferida
# LITERALMENTE no texto do Planalto em 2026-08-25. Sao NOVE faixas de 0,5 p.p.,
# com cortes de 10 em 10 pontos a partir de 15%, ate 5% da RCL:
#   <=15% -> 1,0 | <=25% -> 1,5 | <=35% -> 2,0 | <=45% -> 2,5 | <=55% -> 3,0
#   <=65% -> 3,5 | <=75% -> 4,0 | <=85% -> 4,5 |  >85% -> 5,0
# CORRIGIDO nesta data: a tabela anterior ((15,1.0),(24,1.5),(33,2.0),(42,2.5),
# (51,3.0)) com teto 3,5 tinha DOIS erros — os cortes intermediarios (24/33/42/51
# em vez de 25/35/45/55) e a ausencia das tres faixas superiores, o que SUBESTIMAVA
# o teto de todo ente com mora acima de 55% da RCL (ate 30% menos orcamento, logo
# projecao longa demais). Escada validada de forma independente contra as tabelas
# §23 publicadas por TJRS (78/78 entes), TJTO e TJPR.
DEGRAUS = ((15, 1.0), (25, 1.5), (35, 2.0), (45, 2.5), (55, 3.0),
           (65, 3.5), (75, 4.0), (85, 4.5))
TETO_ESCADA = 5.0
# multiplicador empirico do pagamento observado sobre o teto, por faixa (secao 3)


def escada_p23(prop_mora_rcl_pct):
    """Percentual do §23 pela faixa de mora/RCL (em %). Ver limites na secao 2."""
    if prop_mora_rcl_pct is None:
        return None
    for limite, pct in DEGRAUS:
        if prop_mora_rcl_pct <= limite:
            return pct
    return TETO_ESCADA


def ano_orcamento(item):
    """Extrai o ANO do campo de ano-orcamento, que varia por tribunal:
    TJSP manda '<ordem>/<ano>' (ex. '6/2023'); os demais mandam o ano puro."""
    v = item.get("ano")
    if isinstance(v, int):
        return v
    m = re.search(r"(\d{4})", str(v or ""))
    return int(m.group(1)) if m else None


def mora_da_fila(fila, exercicio):
    """Estoque EM MORA = precatorios cujo ano-orcamento venceu antes do exercicio.
    Devolve (valor_em_mora, n_em_mora, valor_total, n_total)."""
    vm = vt = 0.0
    nm = nt = 0
    for it in fila:
        val = it.get("val") or 0.0
        vt += val
        nt += 1
        a = ano_orcamento(it)
        if a is not None and a < exercicio:
            vm += val
            nm += 1
    return round(vm, 2), nm, round(vt, 2), nt


def orcamento_anual(rcl, mora, regime="Comum", pago_cnj=None, pct_oficial=None,
                    valor_oficial=None):
    """Devolve dict com o orcamento anual e a fonte usada.

    rcl           RCL do ente (R$)
    mora          estoque em mora (R$) — base do §23
    regime        'Comum' | 'Especial'
    pago_cnj      pago no ano de referencia (Mapa Anual CNJ), se houver
    pct_oficial   percentual homologado do ente (MG/BA), se houver
    valor_oficial VALOR anual do deposito publicado pelo tribunal, se houver

    PRECEDENCIA (2026-08-25): o valor publicado pelo tribunal vence RCL x percentual
    — MAS SO' QUANDO ELE REVELA O TETO. Motivo medido: o tribunal calcula o deposito
    sobre a RCL DELE, que nao e' a do SICONFI; nos 42 municipios da BA em que o plano
    do Comite Gestor esta CAPADO pelo teto, 'RCL do SICONFI x %' superestimou o valor
    oficial em 41 casos (mediana +4,3%, extremos +32%), deixando a projecao otimista.

    ARMADILHA (custou uma projecao de 2098 em Riachao do Jacuipe): o `valor_anual` do
    Comite Gestor NAO e' o teto anual — e' o desembolso DESTE exercicio para zerar a
    MORA VENCIDA. Quando a mora e' menor que o teto, o plano vem igual a mora (ente
    EM DIA, nao ente parado) e usa-lo como orcamento perpetuo trava a fila para
    sempre. So' quando `mora >= teto` o plano esta limitado pelo teto e, portanto,
    REVELA a RCL que o tribunal usa. Fora disso, a fila futura anda pelo teto.
    """
    teto_calc = (rcl * (pct_oficial or escada_p23((mora / rcl * 100) if mora else 0.0)) / 100
                 if rcl and rcl > 0 else None)
    capado = (valor_oficial and mora and teto_calc
              and mora >= teto_calc * 0.999
              and abs(valor_oficial - mora) > 0.01)
    # sem RCL nenhuma, o valor publicado e' tudo que ha — melhor que nada, desde que
    # nao seja o caso "plano = mora" (que nao informa teto algum).
    sem_rcl = valor_oficial and not teto_calc and mora and abs(valor_oficial - mora) > 0.01
    if capado or sem_rcl:
        prop = (mora / rcl * 100) if (mora and rcl) else 0.0
        pct = pct_oficial or (escada_p23(prop) if rcl else None)
        return {"valor": round(valor_oficial, 2), "fonte": "oficial_valor", "pct": pct,
                "prop_mora": round(prop, 2), "pct_p23": pct,
                # o teto que o TRIBUNAL pratica e' o proprio valor publicado; o
                # teorico (RCL do SICONFI x %) fica so' como referencia de tela.
                "teto_p23": round(valor_oficial, 2),
                "teto_p23_teorico": round(teto_calc, 2) if teto_calc else None}
    if not rcl or rcl <= 0:
        return {"valor": None, "fonte": None, "pct": None, "prop_mora": None}
    prop = (mora / rcl * 100) if mora else 0.0
    pct = pct_oficial if pct_oficial else escada_p23(prop)
    teto = rcl * pct / 100

    # 'pct'     = percentual que gerou o 'valor' (varia com a fonte escolhida)
    # 'pct_p23' = degrau da escada do §23, SEMPRE — nao depende da fonte.
    # Manter os dois separados: sao grandezas diferentes, e confundi-las fazia o
    # multiplicador do regime especial cair no fallback (ver projecao_cenarios).
    comum = {"prop_mora": round(prop, 2), "teto_p23": round(teto, 2), "pct_p23": pct}
    if pct_oficial:
        return {"valor": round(teto, 2), "fonte": "oficial", "pct": pct, **comum}
    # O orcamento legal e' SEMPRE o teto do §23 (ou o oficial homologado). O que o
    # ente PAGOU de fato -- acima OU abaixo do teto -- e' um contraponto separado
    # (`ritmo_observado`, no alfred_core), nao o orcamento. Ate 20/08/2026 havia aqui
    # um ramo "Especial e pago>teto -> valor=observado": valido so PRE-EC 136 (RE
    # pagavam acima do teto p/ cumprir 2029). A EC 136 estendeu o TETO aos RE, entao
    # o orcamento legal e' o teto para todos; misturar o pago invertia a banda.
    return {"valor": round(teto, 2), "fonte": "teto_p23", "pct": pct, **comum}


def projecao_cenarios(rcl, mora, regime, pago_cnj=None, pct_oficial=None,
                      valor_oficial=None):
    """Banda de orcamento anual (conservador, central, otimista), ancorada no
    ORCAMENTO LEGAL do §23 (o `valor` de orcamento_anual: normalmente o teto; o
    observado so quando ELE E' MAIOR que o teto).

    O ritmo OBSERVADO (o que o ente pagou de fato) NAO entra nesta banda — ele e'
    um contraponto separado (`ritmo_observado`, calculado no alfred_core). Ate
    20/08/2026 o regime Especial injetava o pago no cenario `central`: fazia sentido
    PRE-EC 136, quando os RE pagavam ACIMA do teto (para cumprir o prazo de 2029 do
    art. 101 ADCT). A EC 136/2025 revogou esse prazo (art. 7) e estendeu o TETO do
    §23 aos RE (art. 101 §6 ADCT): agora eles pagam ABAIXO do teto, o `central`
    (observado) caia abaixo do `conservador` (teto) e o card "PELO TETO LEGAL DO §23"
    exibia o VALOR PAGO em vez do teto (bug encontrado testando o Estado de MG:
    teto R$1,12 bi, pago R$535 mi, e o card mostrava R$535 mi). Banda unica p/ os
    dois regimes; a divergencia teto x realidade fica no bloco do ritmo observado.
    """
    base = orcamento_anual(rcl, mora, regime, pago_cnj, pct_oficial, valor_oficial)
    if not base["valor"]:
        return None
    orc = base["valor"]
    return {"conservador": round(orc * 0.8, 2), "central": round(orc, 2),
            "otimista": round(orc * 1.2, 2), **base}


def anos_ate(acumulado, orcamento):
    """Anos de orcamento necessarios para alcancar um acumulado da fila."""
    if not orcamento or orcamento <= 0 or acumulado is None:
        return None
    return round(acumulado / orcamento, 1)


# =============================================================================
# 5. CONSUMO DO ORCAMENTO PELA FILA — art. 100 §20 (superprecatorio)
# =============================================================================
# Ate 10/08/2026 esta regra vivia DUPLICADA: em JavaScript dentro de
# build_dashboard.py (funcao proj20) e portada em Python dentro de
# parecer_orly.py. Duas implementacoes da mesma norma divergem com o tempo;
# esta e' a unica daqui em diante. Os testes em scripts/teste_modelo_p23.py
# travam o comportamento contra tres casos ja conferidos a mao.
#
# A REGRA (art. 100 §20): precatorio de grande vulto — valor superior a 15% do
# total dos precatorios do MESMO ano-orcamento daquele ente — nao disputa a
# ordem cronologica. Ele e' pago com 15% do valor a vista no ano de origem e o
# restante em 5 parcelas anuais iguais. Essas parcelas saem POR FORA da fila,
# consumindo o orcamento ANTES dos demais: e' por isso que ignorar o §20 pode
# tornar uma fila irreconhecivel (em Vila Velha, o acumulado a frente de um
# precatorio cai de R$ 80,1 mi para R$ 19,0 mi quando a regra e' aplicada).
#
# MATERIAL_MIN_SP existe para nao classificar como "grande vulto" um precatorio
# pequeno que so parece grande porque o ano-orcamento dele tem poucos itens.

MATERIAL_MIN_SP = 1_000_000.0
FRACAO_SP = 0.15          # limiar de 15% do total do ano E entrada a vista
PARCELA_SP = 0.17         # cada uma das 5 parcelas anuais seguintes
N_PARCELAS_SP = 5


def _val(it):
    v = it.get("val", it.get("valor"))
    return float(v or 0.0)


def _ano(it):
    """Ano-orcamento, tolerante ao formato de cada tribunal ('6/2023' no TJSP)."""
    for k in ("ano", "ano_orcamento", "nu_ano_orcamento"):
        if k in it:
            v = it[k]
            if isinstance(v, int):
                return v
            m = re.search(r"(\d{4})", str(v or ""))
            if m:
                return int(m.group(1))
    return None


def _ordem(it):
    for k in ("mpos", "ordem", "pos"):
        if it.get(k) is not None:
            return it[k]
    return 0


# Situacao que so' o TJCE publica (2026-08-27) e que muda a conta: o precatorio
# ja tem CAIXA RESERVADO especificamente para ele, so' falta o credor levantar.
# Tratar esse valor como "ainda por financiar" faz a fila parecer mais lenta do
# que e' de fato — foi o que atrasou a projecao de Maracanau de 2029-2031 (conta
# manual) para 2033 (motor generico, antes desta correcao): R$ 23,47 mi da fila
# ja estavam provisionados e disputando orcamento futuro que nao precisavam.
SITUACOES_PROVISIONADO = {"provisionamento total"}


def provisionado(it):
    return str(it.get("situacao") or "").strip().lower() in SITUACOES_PROVISIONADO


def regime_sem_p20(regime):
    """Regime Especial NAO tem o parcelamento do §20 (15% a vista + 5 parcelas):
    o grande vulto segue na fila como precatorio normal ate' ser pago por inteiro.
    Regra definida pelo usuario em 2026-09-21; ate' entao o motor aplicava o §20
    a todo ente, inclusive aos de regime especial."""
    return str(regime or "").strip().lower() == "especial"


def marca_superprecatorios(fila, minimo=MATERIAL_MIN_SP, regime=None):
    """Marca it['sp']=True nos precatorios de grande vulto. Devolve (n, valor).

    regime='Especial' -> ninguem e' marcado (ver regime_sem_p20)."""
    if regime_sem_p20(regime):
        for it in fila:
            it["sp"] = False
        return 0, 0.0
    total_ano = defaultdict(float)
    for it in fila:
        total_ano[str(_ano(it))] += _val(it)
    n, v = 0, 0.0
    for it in fila:
        val = _val(it)
        t = total_ano[str(_ano(it))]
        it["sp"] = bool(t > 0 and val > FRACAO_SP * t and val >= minimo)
        if it["sp"]:
            n += 1
            v += val
    return n, round(v, 2)


def ordena(fila):
    """Ordem canonica de disputa da fila — a mesma chave que proj20/acumulado_ate usam.

    Publica p/ quem precisa listar a fila item a item (ex.: tela de "fila de
    precatorios" no parecer) sem duplicar o criterio de ordenacao.
    """
    return sorted(fila, key=lambda f: (_ordem(f), _ano(f) or 9999))


def proj20(fila, orcamento, ano_base, marcar=True, regime=None):
    """Distribui o orcamento anual pela fila respeitando o §20.

    Escreve it['ano_previsto'] em cada item e devolve um resumo. Cada precatorio
    so pode ser pago a partir do seu ano-orcamento (art. 100 §5o), por isso o
    relogio salta para frente quando a fila alcanca itens de exercicio futuro.

    O superprecatorio NAO reserva orcamento desde o ano-base: ele so' entra no
    regime do §20 quando a fila cronologica CHEGA na vez dele (posicao real,
    normal + sp misturados na mesma ordem). Ate' la', os itens normais a frente
    dele consomem o orcamento cheio, sem desconto. So' a partir do ano em que o
    caixa disponivel alcanca a posicao do superprecatorio e' que ele "trava" a
    fila: 15% naquele ano + 5 parcelas de 17% nos seguintes, com prioridade sobre
    quem vem depois dele — exatamente como a lei da a ele: alternativa que ADIANTA
    o pagamento do grande vulto, nao um desconto reservado do dia 1. Corrigido em
    2026-09-04 (antes disto, ate 2026-07-23, o modelo reservava desde o ano-base
    "a pedido do usuario" — decisao que o proprio usuario reconheceu como errada:
    caso Florisvaldo Lima/Pedro Canario-ES, o superprecatorio esta na posicao 51
    de 52 e nao deveria travar quem esta na posicao 3).
    """
    if marcar:
        marca_superprecatorios(fila, regime=regime)
    elif regime_sem_p20(regime):
        for f in fila:
            f["sp"] = False
    ordenada = sorted(fila, key=lambda f: (_ordem(f), _ano(f) or 9999))
    provis = [f for f in ordenada if not f.get("sp") and provisionado(f)]

    # Provisionado nao entra na FIFO do orcamento: o caixa dele ja foi separado em
    # exercicio anterior, entao nao compete com os itens ainda por financiar. Ganha
    # o proprio ano-orcamento como previsao (e' quando o credor pode levantar, nao
    # quando o dinheiro sai do caixa do ente — isso ja aconteceu).
    for f in provis:
        f["ano_previsto"] = max(_ano(f) or ano_base, ano_base)
        f["p20"] = False
        f["provisionado"] = True

    # normal + sp na ORDEM VERDADEIRA (cronologica): o sp so' e' tratado
    # diferente quando o cursor chega nele, nao antes.
    seq = [f for f in ordenada if not provisionado(f)]

    reservado = defaultdict(float)
    ano = ano_base
    disp = orcamento
    resto = None
    i, guarda, pagos_ano_base = 0, 0, 0
    # trava anti-laco infinito; proporcional a fila (o Estado da BA tem 30k itens e a
    # trava fixa de 20000 cortava o laco no meio, deixando itens sem ano_previsto)
    limite_guarda = 20000 + 4 * len(seq)
    while i < len(seq) and guarda < limite_guarda:
        guarda += 1
        f = seq[i]
        exercicio = max(_ano(f) or ano_base, ano_base)
        if exercicio > ano:                      # art. 100 §5o: ainda nao pode
            ano = exercicio
            disp = orcamento - reservado.get(ano, 0.0)
            resto = None
            continue
        if disp <= 1e-9:
            ano += 1
            disp = orcamento - reservado.get(ano, 0.0)
            resto = None
            continue
        if f.get("sp"):
            # chegou a vez: a partir de AGORA (nao do ano-base) o §20 trava a
            # fila. gasto_ja preserva o que os itens normais deste mesmo ano
            # ja consumiram antes do cursor chegar aqui.
            gasto_ja = (orcamento - reservado.get(ano, 0.0)) - disp
            inicio = ano
            reservado[inicio] += FRACAO_SP * _val(f)
            for k in range(1, N_PARCELAS_SP + 1):
                reservado[inicio + k] += PARCELA_SP * _val(f)
            f["ano_previsto"] = inicio + N_PARCELAS_SP
            f["p20"] = True
            disp = orcamento - reservado.get(ano, 0.0) - gasto_ja
            i += 1
            continue
        resto = _val(f) if resto is None else resto
        pago = min(disp, resto)
        resto -= pago
        disp -= pago
        if resto <= 1e-6:
            f["ano_previsto"] = ano
            f["p20"] = False
            if ano == ano_base:
                pagos_ano_base += 1
            i += 1
            resto = None
        else:
            ano += 1
            disp = orcamento - reservado.get(ano, 0.0)

    normal = [f for f in seq if not f.get("sp")]
    sp = [f for f in seq if f.get("sp")]
    zera = normal[-1]["ano_previsto"] if normal else ano_base
    zera_sp = max((f["ano_previsto"] for f in sp), default=None)
    return {"zera": zera, "zera_sp": zera_sp, "n_sp": len(sp),
            "pagos_ano_base": pagos_ano_base, "reservado": dict(reservado),
            "orcamento": orcamento, "ano_base": ano_base}


def acumulado_ate(fila, item, so_normal=True, excluir_provisionado=False):
    """Soma dos valores a frente do item na fila (inclusive ele).

    so_normal=True exclui os superprecatorios, que nao disputam a ordem
    cronologica — e' o numero que explica a previsao. so_normal=False devolve a
    soma bruta, util so para conferencia.

    excluir_provisionado=True devolve o que AINDA FALTA FINANCIAR: tira os itens
    com caixa ja reservado (ver `provisionado()`). E' o numero que bate com
    `ano_previsto` do proj20 corrigido; o `acumulado_ate` padrao (False) continua
    mostrando quanto falta ANDAR na fila, que e' outra pergunta — util p/ contexto,
    mas nao p/ estimar orcamento necessario (ver `anos_ate` no alfred_core).

    Devolve None quando o PROPRIO item e' superprecatorio e so_normal=True: nesse
    caso "acumulado a frente" nao tem sentido, porque ele nao entra na disputa da
    fila (e' pago em 15% + 5 parcelas, por fora). Sem essa guarda o laco nunca
    encontrava o item — que fora pulado pelo `continue` — e somava a fila inteira,
    produzindo um numero maior que a propria soma bruta.
    """
    if so_normal and item.get("sp"):
        return None
    ordenada = sorted(fila, key=lambda f: (_ordem(f), _ano(f) or 9999))
    acc = 0.0
    for f in ordenada:
        if so_normal and f.get("sp"):
            continue
        if excluir_provisionado and provisionado(f) and f is not item:
            continue
        acc += _val(f)
        if f is item:
            break
    return round(acc, 2)


def previsao(fila, item, orcamento, ano_base):
    """Atalho: roda o proj20 e devolve (ano_previsto, acumulado_normal)."""
    proj20(fila, orcamento, ano_base)
    return item.get("ano_previsto"), acumulado_ate(fila, item)
