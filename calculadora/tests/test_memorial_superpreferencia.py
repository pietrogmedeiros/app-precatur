"""Linha da superpreferência no memorial PDF — mesma posição/condição da
cascata em tela (`Calculadora.render_cenario`): só aparece quando o cenário
traz `valor_superpreferencia`, logo antes de "Valor total atualizado"."""
from datetime import date
from decimal import Decimal

from memorial import _cascata_html, _trilha_html, gerar_memorial_pdf
from precaturia.pipeline.calculadora import EntradaCalculadora, calcular_dict

DATA_CALCULO = date(2026, 1, 10)
DATA_PAGAMENTO = date(2026, 4, 10)
DATA_ALVO = date(2026, 8, 1)
PRINCIPAL = Decimal("100000.00")


def test_cascata_sem_superpreferencia_nao_mostra_linha():
    html = _cascata_html({"valor_total_atualizado": "100000.00"})
    assert "superpreferência" not in html.lower()


def test_cascata_com_superpreferencia_mostra_as_2_linhas_na_posicao_certa():
    cen = {
        "valor_total_atualizado": "80000.00",
        "valor_superpreferencia": "20000.00",
        "data_pagamento_superpreferencia": "2026-04-10",
        "valor_corrigido_pre_superpreferencia": "101000.00",
    }
    html = _cascata_html(cen)
    pos_corrigido = html.find("Valor corrigido até a superpreferência")
    pos_abate = html.find("Superpreferência paga em 10/04/2026")
    pos_total = html.find("Valor total atualizado")
    assert -1 < pos_corrigido < pos_abate < pos_total
    assert "R$ 101.000,00" in html  # saldo pré-abatimento
    assert "R$ 20.000,00" in html   # valor abatido


def test_trilha_mostra_fase_do_abatimento_com_principal_e_juros():
    """A trilha detalhada (fase a fase) precisa RECONCILIAR com o motor
    mesmo com o abatimento no meio — senão cai no fallback simples e a fase
    nova nunca aparece. `principal_abatido`/`juros_abatido` têm que somar
    exatamente o valor pago (proporção sobre os 2 componentes, sem SELIC
    porque a conta de teste não declara SELIC própria)."""
    juros = Decimal("50000.00")
    res = calcular_dict(EntradaCalculadora(
        valor_total=PRINCIPAL + juros,
        valor_principal_corrigido=PRINCIPAL,
        valor_juros=juros,
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
        valor_superpreferencia=Decimal("20000.00"),
        data_pagamento_superpreferencia=DATA_PAGAMENTO,
    ))
    cen = res["cenario_homologado"]
    iniciais = {"principal": str(PRINCIPAL), "juros": str(juros), "selic": "0"}
    html = _trilha_html(cen, iniciais)

    assert html != ""  # não caiu no fallback — reconciliou com o motor
    assert "Superpreferência — abatimento" in html
    det = cen["superpreferencia_detalhe"]
    principal_abatido = Decimal(det["principal_abatido"])
    juros_abatido = Decimal(det["juros_abatido"])
    assert abs((principal_abatido + juros_abatido) - Decimal("20000.00")) <= Decimal("0.02")
    assert principal_abatido > 0 and juros_abatido > 0  # proporcional, nenhum é 0


def test_memorial_pdf_gera_bytes_com_superpreferencia_ponta_a_ponta():
    """Fumaça: `calcular_dict` real (com superpreferência) alimentando
    `gerar_memorial_pdf` de verdade, sem erro e com PDF não-vazio."""
    res = calcular_dict(EntradaCalculadora(
        valor_total=PRINCIPAL,
        valor_principal_corrigido=PRINCIPAL,
        data_calculo=DATA_CALCULO,
        esfera="estadual",
        data_alvo=DATA_ALVO,
        valor_superpreferencia=Decimal("20000.00"),
        data_pagamento_superpreferencia=DATA_PAGAMENTO,
    ))
    pdf_bytes = gerar_memorial_pdf(
        valores=[("Principal corrigido", "R$ 100.000,00")],
        datas=[("Data do cálculo", "10/01/2026")],
        outros=[],
        iniciais=None,
        res=res,
        gerado_em=DATA_ALVO,
    )
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
