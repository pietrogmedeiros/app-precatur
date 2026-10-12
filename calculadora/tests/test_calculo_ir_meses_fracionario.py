"""`calcular_ir_rra` aceita NM fracionário (Decimal), não só inteiro.

Necessário para o rateio do NM entre parcelas pagas em datas diferentes
(superpreferência + saldo — ver test_superpreferencia.py e cenarios.py,
bloco de IR do cenário homologado). O CEPREC faz exatamente isso: 34 meses
de competência viram 17,4 e 16,6 no evento 39 do precatório
2005527-85.2025.8.13.0000/TJMG, proporcionais ao valor de cada parcela.
"""
from decimal import Decimal

from precaturia.pipeline import calculo_ir


def test_aceita_meses_fracionario_e_divide_por_ele():
    r = calculo_ir.calcular_ir_rra(
        "remuneratorio", Decimal("112158.89"), Decimal("16.6"),
        pss_deduzir=Decimal("6934.59"), honorarios_deduzir=Decimal("13019.08"),
    )
    assert r.meses_competencia == Decimal("16.6")
    assert r.base_apos_deducoes == Decimal("112158.89") - Decimal("6934.59") - Decimal("13019.08")
    assert r.base_mensal == (r.base_apos_deducoes / Decimal("16.6")).quantize(Decimal("0.01"))


def test_int_e_decimal_dao_o_mesmo_resultado():
    """Compatibilidade: quem ainda chama com int (ex.: cenário sentencial,
    que não rateia) continua funcionando idêntico a antes."""
    via_int = calculo_ir.calcular_ir_rra("remuneratorio", Decimal("500000"), 34)
    via_decimal = calculo_ir.calcular_ir_rra(
        "remuneratorio", Decimal("500000"), Decimal("34")
    )
    assert via_int.valor_ir == via_decimal.valor_ir
    assert via_int.meses_competencia == via_decimal.meses_competencia == Decimal("34")


def test_to_dict_serializa_meses_fracionario_como_string_limpa():
    """`str(Decimal("16.6"))` não deve carregar ruído de ponto flutuante —
    o caller (cenarios.py) já entrega o valor quantizado a 1 casa decimal."""
    r = calculo_ir.calcular_ir_rra("remuneratorio", Decimal("100000"), Decimal("16.6"))
    assert r.to_dict()["meses_competencia"] == "16.6"


def test_fracao_pequena_nao_e_forcada_pro_piso_de_1_mes():
    """Uma parcela pequena pode ratear pra bem menos que 1 mês (ex.: 0,3) —
    forçar um piso de 1 mês inteiro diluiria demais a base e reintroduziria a
    mesma subestimativa que o rateio existe pra evitar."""
    r = calculo_ir.calcular_ir_rra("remuneratorio", Decimal("10000"), Decimal("0.3"))
    assert r.meses_competencia == Decimal("0.3")
    assert r.base_mensal == (Decimal("10000") / Decimal("0.3")).quantize(Decimal("0.01"))


def test_piso_de_0_1_so_evita_divisao_por_zero():
    """O único piso real é 0,1 — protege o caso degenerado (fração de rateio
    nula, quando a superpreferência quita o saldo inteiro)."""
    r = calculo_ir.calcular_ir_rra("remuneratorio", Decimal("10000"), Decimal("0"))
    assert r.meses_competencia == Decimal("0.1")
