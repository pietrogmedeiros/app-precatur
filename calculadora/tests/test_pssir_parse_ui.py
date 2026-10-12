"""A tela lê os campos de PSS/IR com o parse novo — digitado e semeado.

Dois caminhos entram no mesmo campo de texto: o que o advogado DIGITA e o que
o pré-preenchimento/snapshot SEMEIA por URL. Os dois têm de dar o mesmo número.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pssir_util import (VALOR, calcular, espiar_motor, novo_app, preencher,
                        rodar, texto)


@pytest.mark.parametrize("digitado, esperado", [
    ("1.234,56", "1234.56"),
    ("1234.56", "1234.56"),
    ("5.000", "5000"),           # antes: 5,00
    ("1,234.56", "1234.56"),     # antes: 1,23456
    ("1.234", "1234"),           # antes: 1,234
    ("0.5", "0.5"),
])
def test_pss_digitado_e_lido_certo(monkeypatch, digitado, esperado):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss=digitado)
    assert not at.exception
    assert reg["entrada"].valor_pss == Decimal(esperado)


def test_ir_digitado_com_ponto_de_milhar_e_lido_certo(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = rodar(ir_modo=VALOR, ir="5.000")
    assert not at.exception
    assert reg["entrada"].valor_ir == Decimal("5000")


def test_pre_preenchimento_por_url_le_o_mesmo_numero(monkeypatch):
    """A extração do LLM é instruída a devolver formato BR ("5.000") — e o
    campo recebe o texto como veio."""
    reg = espiar_motor(monkeypatch)
    at = novo_app({"valor_pss": "5.000", "valor_ir": "1.234,56"})
    assert texto(at, "pss").value == "5.000"
    preencher(at, pss_modo=VALOR, ir_modo=VALOR, pss=None, ir=None)
    calcular(at)
    assert not at.exception
    assert reg["entrada"].valor_pss == Decimal("5000")
    assert reg["entrada"].valor_ir == Decimal("1234.56")


def test_pre_preenchimento_decimal_com_ponto_continua_certo(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = novo_app({"valor_pss": "1234.56", "valor_ir": "987.65"})
    preencher(at, pss_modo=VALOR, ir_modo=VALOR)
    calcular(at)
    assert not at.exception
    assert reg["entrada"].valor_pss == Decimal("1234.56")
    assert reg["entrada"].valor_ir == Decimal("987.65")


def test_snapshot_com_tres_casas_decimais_nao_vira_milhar(monkeypatch):
    """`str(Decimal("987.650"))` é "987.650" — a forma que o parse novo leria
    como milhar (987650). A semeadura do snapshot desfaz a ambiguidade."""
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")
    import hub
    snap = {
        "id": "snap-3c", "case_id": "caso-3c", "deal_id": "2387",
        "criado_em": "2026-03-10T12:00:00", "autor": "ana",
        "valor_liquido": "1", "valor_card": "R$ 1,00", "motor_versao": "x",
        "ultimo_mes_real": {}, "memorial_pdf_hash": None,
        "entrada": {"valor_total": "150000.00", "valor_principal_corrigido": "100000.00",
                    "valor_juros": "50000.00", "data_calculo": "2025-01-15",
                    "natureza_tributaria": "remuneratorio",
                    "valor_pss": "1234.567", "valor_ir": "987.650"},
    }
    monkeypatch.setattr(hub, "snapshot", lambda sid: dict(snap))
    reg = espiar_motor(monkeypatch)
    at = novo_app({"snapshot": "snap-3c"})
    from pssir_util import DATA_CALC
    for d in at.date_input:
        if d.label.startswith("Data de atualização"):
            d.set_value(DATA_CALC)
    calcular(at)
    assert not at.exception
    assert reg["entrada"].valor_ir == Decimal("987.650")
    assert reg["entrada"].valor_pss == Decimal("1234.567")
