"""Abatimento de superpreferência (idoso 80+/doença grave/PcD, RCL/EC 114).

Pagamento BRUTO antecipado, abatido NA DATA em que ocorreu — não no final
sobre o valor cheio. O motor corrige o saldo até a data do pagamento (perna
1), subtrai o valor pago PROPORCIONALMENTE dos 3 componentes segregados
(principal/juros/SELIC — nenhum é blindado), e segue corrigindo o restante
até `data_alvo` (perna 2). Ver `cenarios.construir_cenarios`.

Janela de teste inteira em 2026, esfera estadual (EC 136 vigente desde
08/2025) e sem `data_apresentacao` — evita cruzar período de graça ou a
fronteira EC 113/EC 136, isolando só a mecânica do abatimento.
"""
from datetime import date
from decimal import Decimal

from precaturia.pipeline.calculadora import EntradaCalculadora, calcular_dict
from precaturia.pipeline.cenarios import _atualizar_segregado
from precaturia.pipeline import calculo_ir

DATA_CALCULO = date(2026, 1, 10)
DATA_PAGAMENTO = date(2026, 4, 10)
DATA_ALVO = date(2026, 8, 1)
PRINCIPAL = Decimal("100000.00")


def test_sem_superpreferencia_e_identico_ao_caminho_unico():
    """Regressão: sem os 2 campos novos, o resultado não muda — mesma chamada
    única de `_atualizar_segregado` de antes da feature."""
    esperado = _atualizar_segregado(
        PRINCIPAL, Decimal("0"), Decimal("0"), DATA_CALCULO, DATA_ALVO,
        esfera="estadual",
    )
    d = calcular_dict(EntradaCalculadora(
        valor_total=PRINCIPAL,
        valor_principal_corrigido=PRINCIPAL,
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
    ))
    cen = d["cenario_homologado"]
    assert cen["valor_total_atualizado"] == str(esperado.valor_total_atualizado)
    assert cen["valor_superpreferencia"] is None
    assert cen["data_pagamento_superpreferencia"] is None
    assert cen["valor_corrigido_pre_superpreferencia"] is None


def test_com_superpreferencia_abate_no_saldo_corrigido_na_data_do_pagamento():
    """O total final bate com duas pernas calculadas à mão: corrige até o
    pagamento, abate, corrige o resto até data_alvo."""
    leg1 = _atualizar_segregado(
        PRINCIPAL, Decimal("0"), Decimal("0"), DATA_CALCULO, DATA_PAGAMENTO,
        esfera="estadual",
    )
    valor_superpref = Decimal("20000.00")
    fator_restante = (
        (leg1.valor_total_atualizado - valor_superpref) / leg1.valor_total_atualizado
    )
    leg2 = _atualizar_segregado(
        leg1.principal_corrigido_atualizado * fator_restante,
        leg1.juros_moratorios_atualizado * fator_restante,
        leg1.selic_acumulada_atualizada * fator_restante,
        DATA_PAGAMENTO, DATA_ALVO,
        esfera="estadual",
    )
    esperado_total = leg2.valor_total_atualizado

    d = calcular_dict(EntradaCalculadora(
        valor_total=PRINCIPAL,
        valor_principal_corrigido=PRINCIPAL,
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
        valor_superpreferencia=valor_superpref,
        data_pagamento_superpreferencia=DATA_PAGAMENTO,
    ))
    cen = d["cenario_homologado"]
    assert cen["valor_corrigido_pre_superpreferencia"] == str(leg1.valor_total_atualizado)
    assert cen["valor_superpreferencia"] == "20000.00"
    assert cen["data_pagamento_superpreferencia"] == DATA_PAGAMENTO.isoformat()
    assert cen["valor_total_atualizado"] == str(esperado_total)

    sem_abate = _atualizar_segregado(
        PRINCIPAL, Decimal("0"), Decimal("0"), DATA_CALCULO, DATA_ALVO,
        esfera="estadual",
    )
    assert Decimal(cen["valor_total_atualizado"]) < sem_abate.valor_total_atualizado


def test_superpreferencia_maior_que_saldo_zera_sem_erro():
    """Pagamento que cobre (ou excede) o saldo corrigido não estoura — clampa
    em zero, sem ficar negativo nem levantar exceção."""
    d = calcular_dict(EntradaCalculadora(
        valor_total=PRINCIPAL,
        valor_principal_corrigido=PRINCIPAL,
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
        valor_superpreferencia=Decimal("999999999.00"),
        data_pagamento_superpreferencia=DATA_PAGAMENTO,
    ))
    cen = d["cenario_homologado"]
    assert cen["valor_total_atualizado"] == "0.00"


def test_pss_recalc_usa_base_ja_reduzida_pela_superpreferencia():
    """PSS/IR partem de `seg` (pós-abatimento) sem ajuste próprio — o valor
    estimado tem que sair MENOR com superpreferência do que sem."""
    kwargs = dict(
        valor_total=PRINCIPAL,
        valor_principal_corrigido=PRINCIPAL,
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
        natureza_tributaria="remuneratorio",
        estimar_pss=True,
        aliquota_pss_pct=Decimal("14"),
    )
    sem = calcular_dict(EntradaCalculadora(**kwargs))
    com = calcular_dict(EntradaCalculadora(
        **kwargs,
        valor_superpreferencia=Decimal("20000.00"),
        data_pagamento_superpreferencia=DATA_PAGAMENTO,
    ))
    pss_sem = Decimal(sem["cenario_homologado"]["valor_pss"])
    pss_com = Decimal(com["cenario_homologado"]["valor_pss"])
    assert pss_com < pss_sem


# Janela com um crédito maior — a Maristela (2005527-85.2025.8.13.0000/TJMG)
# não serve pra provar o valor do IR porque a base mensal fica abaixo da
# isenção nos dois cenários (rateado ou não): a alíquota dá 0% de qualquer
# jeito. Aqui a superpreferência absorve quase todo o saldo, então o NM
# rateado (poucos meses) empurra a base mensal do resto pra uma faixa alta —
# é onde a diferença aparece de verdade.
NM_PRINCIPAL = Decimal("400000.00")
NM_SUPERPREF = Decimal("300000.00")


def _cenario_com_nm_rateado():
    d = calcular_dict(EntradaCalculadora(
        valor_total=NM_PRINCIPAL,
        valor_principal_corrigido=NM_PRINCIPAL,
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
        natureza_tributaria="remuneratorio",
        estimar_ir=True,
        meses_competencia=30,
        valor_superpreferencia=NM_SUPERPREF,
        data_pagamento_superpreferencia=DATA_PAGAMENTO,
    ))
    return d["cenario_homologado"]


def test_nm_do_ir_rra_e_rateado_pela_fracao_remanescente_da_superpreferencia():
    """Mesmo critério do CEPREC (evento 39 do 2005527-85.2025.8.13.0000/TJMG:
    34 meses viram 17,4 e 16,6 pela proporção de cada parcela paga) — os 30
    meses declarados no ofício não vão inteiros pro saldo que sobra depois da
    superpreferência; são multiplicados pela mesma fração que já reduz
    principal/juros/SELIC no abatimento."""
    cen = _cenario_com_nm_rateado()
    detalhe = cen["superpreferencia_detalhe"]
    assert detalhe["meses_competencia_total"] == "30"
    fracao = Decimal(detalhe["fracao_remanescente"])
    esperado = (Decimal("30") * fracao).quantize(Decimal("0.1"))
    assert detalhe["meses_competencia_rateado"] == str(esperado)
    assert cen["ir_detalhe"]["meses_competencia"] == str(esperado)


def test_nm_cheio_em_saldo_parcial_subestimaria_o_ir():
    """Prova que o rateio muda o resultado, não só o número exibido: aplicando
    o NM CHEIO (30, o comportamento antigo) sobre a mesma base tributável já
    reduzida pela superpreferência, a base mensal cai numa faixa mais baixa
    da tabela e o IR sai bem menor do que o correto — mesma distorção
    encontrada no prognóstico da USS (que nunca rateia o NM)."""
    cen = _cenario_com_nm_rateado()
    ird = cen["ir_detalhe"]
    base_total = Decimal(ird["base_total"])
    pss = Decimal(ird["pss_deduzido"])

    nm_cheio = calculo_ir.calcular_ir_rra(
        "remuneratorio", base_total, Decimal("30"), pss_deduzir=pss,
    )
    ir_correto = Decimal(cen["valor_ir"])

    assert nm_cheio.aliquota_efetiva_pct < Decimal(ird["aliquota_efetiva_pct"])
    assert nm_cheio.valor_ir < ir_correto
    # No caso concreto: NM cheio cai na faixa de 15% (R$ 2.528,67); o rateado
    # (8,1 meses) cai em 27,5% (R$ 18.954,01) — mais de R$ 16 mil de diferença.
    assert ir_correto - nm_cheio.valor_ir > Decimal("16000")
