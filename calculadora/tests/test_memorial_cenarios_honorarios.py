"""Cenários por % de honorário contratual no memorial (anexo provisório).

A tabela existe para o comercial negociar enquanto o contrato de honorários
não chega, sem pedir recálculo ao jurídico. A prova central é a que motivou a
feature (caso #2405): com PSS/IR ESTIMADOS, descontar o percentual "por fora"
do líquido NÃO reproduz o motor — o percentual reduz a base de PSS/IR.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from memorial import _cenarios_honorarios_html, gerar_memorial_pdf
from precaturia.pipeline.calculadora import (
    EntradaCalculadora,
    calcular_dict,
    cenarios_honorarios_contratuais,
)

DATA_CALCULO = date(2026, 1, 10)
# Data-alvo com índice PUBLICADO (sem projeção Focus): resultado estável.
DATA_ALVO = date(2026, 6, 30)


def _entrada(**kw) -> EntradaCalculadora:
    # Valores altos e RRA curto de propósito: a base mensal do IR precisa cair
    # em faixa com parcela a deduzir > 0 — é aí que o desconto "por fora"
    # diverge do motor (com IR estimado em zero, os dois coincidem).
    base = dict(
        valor_total=Decimal("500000.00"),
        valor_principal_corrigido=Decimal("400000.00"),
        valor_juros=Decimal("100000.00"),
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
        natureza_tributaria="remuneratorio",
        estimar_pss=True,
        estimar_ir=True,
        meses_competencia=24,
    )
    base.update(kw)
    return EntradaCalculadora(**base)


def test_linha_da_grade_bate_com_o_motor_e_nao_com_regra_de_tres():
    linhas = cenarios_honorarios_contratuais(_entrada())
    por_pct = {Decimal(ln["pct"]): Decimal(ln["liquido"]) for ln in linhas}
    assert set(por_pct) == {Decimal(p) for p in ("0", "10", "15", "20", "25", "30")}

    motor_20 = Decimal(
        calcular_dict(_entrada(honorarios_contratuais_pct=Decimal("20")))
        ["cenario_homologado"]["valor_liquido_atualizado"]
    )
    assert por_pct[Decimal("20")] == motor_20

    # A "conta de padaria" (líquido × 0,8) subtrai demais: cobra PSS/IR também
    # sobre a parte do advogado. O motor tem que dar líquido MAIOR.
    linear = (por_pct[Decimal("0")] * Decimal("0.8")).quantize(Decimal("0.01"))
    assert por_pct[Decimal("20")] > linear


def test_pct_informado_entra_na_grade_e_e_marcado_como_atual():
    # 18% não está na grade default (0/10/15/20/25/30) — prova que a linha do
    # contrato real é ADICIONADA, não só que uma linha existente é marcada.
    linhas = cenarios_honorarios_contratuais(
        _entrada(honorarios_contratuais_pct=Decimal("18")))
    por_pct = {Decimal(ln["pct"]): ln for ln in linhas}
    assert Decimal("18") in por_pct
    assert por_pct[Decimal("18")]["atual"] is True
    assert sum(1 for ln in linhas if ln["atual"]) == 1


def test_sem_pct_informado_a_linha_zero_e_o_calculo_atual():
    linhas = cenarios_honorarios_contratuais(_entrada())
    por_pct = {Decimal(ln["pct"]): ln for ln in linhas}
    assert por_pct[Decimal("0")]["atual"] is True
    assert sum(1 for ln in linhas if ln["atual"]) == 1


def test_html_renderiza_linhas_marcador_e_ressalva():
    linhas = [
        {"pct": "0", "liquido": "100000.00", "atual": False},
        {"pct": "20", "liquido": "82000.00", "atual": True},
    ]
    html = _cenarios_honorarios_html(linhas)
    assert "Sem honorário contratual" in html
    assert "Contratuais de 20%" in html
    assert "← este cálculo" in html
    assert "item 2.19" in html  # ressalva do destaque
    assert "R$ 82.000,00" in html


def test_html_vazio_sem_linhas_ou_com_linha_unica():
    assert _cenarios_honorarios_html(None) == ""
    assert _cenarios_honorarios_html([]) == ""
    assert _cenarios_honorarios_html(
        [{"pct": "0", "liquido": "1.00", "atual": True}]) == ""


def test_memorial_pdf_com_cenarios_ponta_a_ponta():
    entrada = _entrada()
    res = calcular_dict(entrada)
    linhas = cenarios_honorarios_contratuais(entrada)
    pdf = gerar_memorial_pdf(
        valores=[("Total da conta", "R$ 150.000,00")],
        datas=[("Data do cálculo", "10/01/2026")],
        outros=[],
        iniciais=None,
        res=res,
        gerado_em=DATA_ALVO,
        cenarios_honorarios=linhas,
    )
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
