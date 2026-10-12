"""PSS/IR no modo "Valor no ofício (R$)": o que JÁ funciona e precisa continuar.

Estes testes passam antes de qualquer correção de borda (parse, vazio/inválido,
limites) — são a rede de proteção para os commits seguintes não mexerem no que
está certo. Conta manual do caso base (total 150.000,00, moeda da conta):

    150.000,00 − 1.234,56 (PSS) − 987,65 (IR) = 147.777,79
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pssir_util import (ALIQ, ESTIM, NAO, VALOR, calcular, espiar_motor,
                        novo_app, preencher, radios, rodar, texto)


def _cen(reg):
    return reg["res"]["cenario_homologado"]


def test_valor_declarado_substitui_a_estimativa_e_bate_com_a_conta_manual(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="1.234,56", ir_modo=VALOR, ir="987,65")
    assert not at.exception
    e = reg["entrada"]
    assert e.valor_pss == Decimal("1234.56") and e.estimar_pss is False
    assert e.valor_ir == Decimal("987.65") and e.estimar_ir is False
    cen = _cen(reg)
    assert Decimal(cen["valor_pss"]) == Decimal("1234.56")   # exatamente o digitado
    assert Decimal(cen["valor_ir"]) == Decimal("987.65")     # sem parcela de alíquota
    assert Decimal(cen["valor_liquido_atualizado"]) == Decimal("147777.79")


@pytest.mark.parametrize("pss_modo, ir_modo, esperado", [
    (NAO, NAO, dict(valor_pss=Decimal("0"), estimar_pss=False,
                    valor_ir=Decimal("0"), estimar_ir=False)),
    (ALIQ, ESTIM, dict(valor_pss=None, estimar_pss=True,
                       valor_ir=None, estimar_ir=True)),
])
def test_texto_que_sobrou_no_campo_nao_entra_no_calculo(monkeypatch, pss_modo,
                                                        ir_modo, esperado):
    """O advogado digitou o valor e trocou o radio: o campo continua visível
    e preenchido, mas quem manda é o MODO."""
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=pss_modo, pss="1.234,56", ir_modo=ir_modo, ir="987,65",
               aliq="14")
    assert not at.exception
    e = reg["entrada"]
    for campo, valor in esperado.items():
        assert getattr(e, campo) == valor, campo
    assert texto(at, "pss").value == "1.234,56", "o texto permanece na tela"


def test_url_com_valor_abre_os_radios_em_valor_da_conta():
    at = novo_app({"valor_pss": "1234.56", "valor_ir": "987.65"})
    rp, ri = radios(at)
    assert rp.value == VALOR and ri.value == VALOR
    assert texto(at, "pss").value == "1234.56"
    assert texto(at, "ir").value == "987.65"


def test_url_sem_valor_abre_em_nao_descontar():
    rp, ri = radios(novo_app({"vt": "150000.00"}))
    assert rp.value == NAO and ri.value == NAO


def test_url_com_valor_zero_tambem_abre_em_valor_da_conta():
    """`valor_pss=0` é string não vazia; o modo abre em "Valor" com "0" (que o
    motor lê como zero explícito — mesmo efeito de "Não descontar")."""
    rp, _ = radios(novo_app({"valor_pss": "0"}))
    assert rp.value == VALOR


def test_modo_explicito_na_url_vence_a_heuristica_do_valor():
    at = novo_app({"valor_pss": "1234.56", "pss_modo": "aliquota",
                   "valor_ir": "987.65", "ir_modo": "nao"})
    rp, ri = radios(at)
    assert rp.value == ALIQ and ri.value == NAO
    assert texto(at, "pss").value == "1234.56", "o valor é semeado mesmo assim"


def _snapshot(entrada_extra: dict) -> dict:
    return {
        "id": "snap-ir", "case_id": "caso-ir", "deal_id": "2387",
        "criado_em": "2026-03-10T12:00:00", "autor": "ana",
        "valor_liquido": "147777.79", "valor_card": "R$ 147.777,79",
        "motor_versao": "abc123abc123", "ultimo_mes_real": {},
        "memorial_pdf_hash": None,
        "entrada": {"valor_total": "150000.00",
                    "valor_principal_corrigido": "100000.00",
                    "valor_juros": "50000.00", "data_calculo": "2025-01-15",
                    "natureza_tributaria": "remuneratorio", **entrada_extra},
    }


def _reabrir(monkeypatch, snap: dict):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")
    import hub
    monkeypatch.setattr(hub, "snapshot", lambda sid: dict(snap))
    return novo_app({"snapshot": snap["id"]})


def test_snapshot_com_valor_ir_reabre_em_valor_da_conta(monkeypatch):
    """Hoje só o PSS era testado na reabertura; o IR usa outro ramo do código."""
    at = _reabrir(monkeypatch, _snapshot({"valor_pss": "1234.56",
                                          "valor_ir": "987.65"}))
    rp, ri = radios(at)
    assert ri.value == VALOR and rp.value == VALOR
    assert texto(at, "ir").value == "987.65"
    assert texto(at, "pss").value == "1234.56"


def test_snapshot_com_ir_estimado_ou_zero_nao_abre_em_valor(monkeypatch):
    at = _reabrir(monkeypatch, _snapshot({"estimar_ir": True, "valor_pss": "0"}))
    rp, ri = radios(at)
    assert ri.value == ESTIM and rp.value == NAO
    at = _reabrir(monkeypatch, _snapshot({"valor_ir": "0"}))
    assert radios(at)[1].value == NAO


def test_valor_declarado_fica_nominal_quando_o_total_e_atualizado(monkeypatch):
    """Decisão de desenho (não é bug): PSS/IR declarados saem SEM correção do
    total ATUALIZADO. Estimados acompanham a base; declarados não."""
    from datetime import date
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="1.234,56", ir_modo=VALOR, ir="987,65",
               alvo=date(2026, 6, 30))
    assert not at.exception
    cen = _cen(reg)
    total = Decimal(cen["valor_total_atualizado"])
    assert total > Decimal("150000.00"), "houve atualização ao presente"
    assert Decimal(cen["valor_pss"]) == Decimal("1234.56")
    assert Decimal(cen["valor_ir"]) == Decimal("987.65")
    assert Decimal(cen["valor_liquido_atualizado"]) == total - Decimal("1234.56") - Decimal("987.65")
