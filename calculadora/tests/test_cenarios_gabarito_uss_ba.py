"""Golden da fase precatório (art. 21-A) — gabarito USS, caso BA (23/04/2026).

Prognóstico de escritório especializado (USS) para precatório estadual TJ-BA:
conta liquidada em 31/10/2017, vencimento 2020. Exercita a cadeia pré-dez/2021
COMPLETA:

    11/2017→06/2019  IPCA-E (Tema 810) + poupança (Tema 96)          ×1,06994881
    07/2019→12/2020  graça (art. 100 §5º + SV 17): IPCA-E puro       ×1,05838925
    01/2021→11/2021  PÓS-vencimento, pré-EC 113: IPCA-E + poupança   ×1,09569015
    12/2021→07/2025  SELIC EC 113 (soma simples dentro da fase)      ×1,42730000
    08/2025→04/2026  EC 136: IPCA cheio + 2% a.a. (teto SELIC)       ×1,03602347

Os quatro fatores pré-EC 136 batem o PDF do gabarito ao 8º decimal (séries
finais, validadas contra o BCB). Regressão principal: jan–nov/2021
(pós-vencimento da graça, pré-EC 113) corre o art. 21-A (inciso XII + art. 22
— os juros VOLTAM, Tema 1037), NUNCA SELIC: o §6º ("inadimplido → SELIC",
incluído pela Res. 448/2022) só opera de dez/2021 em diante. Antes do fix
esses 11 meses caíam na SELIC (3,58% em vez de IPCA-E 9,57% + poupança) →
total 9.158.967,13 em vez de 9.924.707,72 (−R$ 765 mil).

O total do motor fica ACIMA do kit USS as-is (9.529.572,10) por 3 razões
auditadas: (a) o kit usa índices EC 136 defasados M-2 (parou em fev/2026 num
kit "até 04/2026"); (b) o kit carrega as parcelas de poupança NOMINAIS até a
fase final (contra art. 22 §1º — SELIC sobre o consolidado); (c) o motor
calcula a poupança mês a mês sobre a base corrigida (fórmula 70%×meta/12, sem
TR — o kit aplica o percentual flat sobre o principal de início de fase).
Janela inteira em meses passados/séries finais — valores estáveis.
"""
from datetime import date
from decimal import Decimal

from precaturia.pipeline.cenarios import _atualizar_segregado

# Face da conta de 31/10/2017, SEM os honorários de 15% (linhas do PDF).
USSBA_PRINCIPAL = Decimal("2947677.69")
USSBA_JUROS = Decimal("2114724.38")
USSBA_DATA_CALCULO = date(2017, 10, 31)
# Vencimento 2020 ⇒ apresentado até 01/07/2019 (corte da ÉPOCA — 1º/07 até
# 2021; EC 114/136 não retroagem) ⇒ graça 07/2019–12/2020.
USSBA_APRESENTACAO = date(2019, 6, 1)
ALVO_KIT = date(2026, 4, 30)  # data-alvo do prognóstico

Q8 = Decimal("0.00000001")


def _ussba(alvo: date = ALVO_KIT):
    return _atualizar_segregado(
        USSBA_PRINCIPAL,
        USSBA_JUROS,
        Decimal("0"),
        USSBA_DATA_CALCULO,
        alvo,
        data_apresentacao=USSBA_APRESENTACAO,
        esfera="estadual",
    )


def test_estrutura_de_fases_bate_o_art_21a():
    """5 fases em ordem cronológica com as janelas exatas do gabarito; na graça
    os juros NÃO crescem além da correção (SV 17: fator_juros == fator)."""
    r = _ussba()
    comps = r.atualizacao.componentes
    esperado = [
        ("art. 21-A", date(2017, 10, 31), date(2019, 6, 30)),
        ("período de graça", date(2019, 7, 1), date(2020, 12, 31)),
        ("art. 21-A", date(2021, 1, 1), date(2021, 11, 30)),
        ("SELIC (EC 113", date(2021, 12, 1), date(2025, 7, 31)),
        ("EC 136", date(2025, 8, 1), date(2026, 4, 30)),
    ]
    assert len(comps) == len(esperado), [c.regime for c in comps]
    for c, (rotulo, ini, fim) in zip(comps, esperado):
        assert rotulo in c.regime, (rotulo, c.regime)
        assert c.inicio == ini
        assert c.fim == fim
    graca = comps[1]
    assert graca.fator_juros.quantize(Q8) == graca.fator.quantize(Q8)


def test_fatores_batem_o_pdf_ao_8o_decimal():
    """Correção por fase idêntica ao prognóstico (mesmas séries oficiais).
    Exceção deliberada: EC 136 com índices COMPLETOS até abr/2026 — o kit parou
    no IPCA de fev/2026 (defasagem M-2, 1,02015098)."""
    r = _ussba()
    fatores = [c.fator.quantize(Q8) for c in r.atualizacao.componentes]
    assert fatores[0] == Decimal("1.06994881")  # IPCA-E 11/2017–06/2019
    assert fatores[1] == Decimal("1.05838925")  # IPCA-E graça 07/2019–12/2020
    assert fatores[2] == Decimal("1.09569015")  # IPCA-E 01–11/2021
    assert fatores[3] == Decimal("1.42730000")  # SELIC soma-RF 12/2021–07/2025
    assert fatores[4] == Decimal("1.03602347")  # IPCA cheio 08/2025–04/2026


def test_pos_graca_pre_ec113_corre_21a_nunca_selic():
    """Regressão do bug: mês anterior a dez/2021 nunca vira SELIC, mesmo com a
    graça vencida (31/12/2020). A fase jan–nov/2021 acumula poupança na linha
    de juros (juros crescem MAIS que o principal)."""
    r = _ussba()
    comps = r.atualizacao.componentes
    for c in comps:
        if "SELIC (EC 113" in c.regime:
            assert c.inicio >= date(2021, 12, 1), c.inicio
    pos_graca = comps[2]
    assert "art. 21-A" in pos_graca.regime
    assert pos_graca.fator_juros > pos_graca.fator


def test_janela_isolada_pos_graca_2021():
    """Janela pura jan–nov/2021 pós-vencimento: um único componente do art.
    21-A (IPCA-E ×1,09569015), juros nascem SÓ da poupança, SELIC zero."""
    r = _atualizar_segregado(
        Decimal("100000"),
        Decimal("0"),
        Decimal("0"),
        date(2020, 12, 31),
        date(2021, 11, 30),
        data_apresentacao=USSBA_APRESENTACAO,
        esfera="estadual",
    )
    comps = r.atualizacao.componentes
    assert len(comps) == 1, [c.regime for c in comps]
    assert "art. 21-A" in comps[0].regime
    assert comps[0].fator.quantize(Q8) == Decimal("1.09569015")
    assert r.principal_corrigido_atualizado == Decimal("109569.01")
    # Poupança (70%×meta/12) mês a mês sobre a base corrigida ≈ 2,7% no ano.
    assert r.juros_moratorios_atualizado == Decimal("2732.38")
    assert r.selic_acumulada_atualizada == Decimal("0.00")


def test_juros_novos_expostos_por_fase():
    """Decomposição da linha de juros (estilo gabarito): as fases 21-A expõem
    a poupança somada (valor exato + Σ das taxas mensais), a EC 136 expõe os
    2% a.a., e graça/SELIC expõem zero. Identidade por fase:
    juros_fim = juros_ini × fator + juros_novos (base do display do memorial)."""
    r = _ussba()
    comps = r.atualizacao.componentes
    esperados = [
        Decimal("245147.24"),  # poupança 11/2017–06/2019 (Σ 7,7729% a.m.)
        Decimal("0.00"),       # graça — juros zerados (SV 17)
        Decimal("91207.19"),   # poupança 01–11/2021 (Σ 2,4938% a.m.)
        Decimal("0.00"),       # SELIC consolida (embute juros)
        Decimal("81124.55"),   # 2% a.a. EC 136 (9 × 2%/12 = 1,5%)
    ]
    assert [c.juros_novos for c in comps] == esperados
    assert comps[0].taxa_juros_novos.quantize(Q8) == Decimal("0.07772917")
    assert comps[2].taxa_juros_novos.quantize(Q8) == Decimal("0.02493750")
    assert comps[4].taxa_juros_novos.quantize(Q8) == Decimal("0.01500000")
    # Identidade da decomposição, fase a fase (fecha com o bucket final).
    j = USSBA_JUROS
    for c in comps:
        j = j * c.fator + c.juros_novos
    assert abs(j.quantize(Decimal("0.01")) - r.juros_moratorios_atualizado) <= Decimal("0.05")


def test_memoria_de_calculo_pss_ir_exposta():
    """O dict do cenário expõe a memória dos descontos ESTIMADOS (consumida
    pelo memorial): PSS (base decomposta × alíquota) e IR-RRA (base → PSS
    deduzido → base mensal → faixa → valor), fechando com a cascata. Inputs =
    simulação real do caso (valores cheios + destaque de 15% no fim)."""
    from precaturia.pipeline.calculadora import EntradaCalculadora, calcular_dict

    d = calcular_dict(EntradaCalculadora(
        valor_total=Decimal("5955767.14"),
        valor_principal_corrigido=Decimal("3467856.11"),
        valor_juros=Decimal("2487911.03"),
        data_calculo=USSBA_DATA_CALCULO,
        natureza_tributaria="remuneratorio",
        estimar_pss=True,
        aliquota_pss_pct=Decimal("14"),
        estimar_ir=True,
        meses_competencia=320,
        honorarios_contratuais_pct=Decimal("15"),
        modalidade="precatorio",
        data_apresentacao=date(2019, 7, 1),
        esfera="estadual",
        data_alvo=date(2026, 4, 1),
    ))
    cen = d["cenario_homologado"]
    pss_d, ir_d = cen["pss_detalhe"], cen["ir_detalhe"]
    assert pss_d["principal_atualizado"] == "6362709.64"
    assert pss_d["contratuais_pct"] == "15"
    assert pss_d["base"] == "5408303.19"
    assert pss_d["aliquota_pct"] == "14"
    assert pss_d["valor"] == cen["valor_pss"] == "757162.45"
    assert ir_d["meses_competencia"] == "320"
    assert ir_d["pss_deduzido"] == "757162.45"
    assert ir_d["base_mensal"] == "14534.81"
    assert ir_d["aliquota_efetiva_pct"] == "27.5"
    assert ir_d["parcela_dedutivel"] == "908.73"
    assert ir_d["valor_ir"] == cen["valor_ir"] == "988269.68"


def test_total_golden():
    """Totais na data-alvo do kit (30/04/2026). Acima do kit as-is — índices
    defasados M-2 + parcelas de poupança nominais (ver docstring do módulo)."""
    r = _ussba()
    assert r.atualizacao.status == "ok"
    assert r.principal_corrigido_atualizado == Decimal("5408303.18")
    assert r.juros_moratorios_atualizado == Decimal("4516404.54")
    assert r.valor_total_atualizado == Decimal("9924707.72")
    assert r.valor_total_atualizado > Decimal("9529572.10")  # kit as-is
