"""Líquido negativo é erro em QUALQUER modo (30/09/2026).

O bloqueio "PSS + IR declarados > total atualizado" não enxerga o honorário
contratual: com 30% sobre 150.000 (45.000), PSS 100.000 + IR 40.000 = 140.000
passa nele e dá líquido −35.000. A rede definitiva é o próprio resultado do
motor: `valor_liquido_atualizado < 0` → st.error com os componentes, sem
memorial e sem envio ao card.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pssir_util import (ALIQ, ESTIM, NAO, VALOR, calcular, erros, espiar_motor,
                        novo_app, preencher, tem_memorial, texto)


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")


def _tem_envio(at) -> bool:
    return any("Enviar para o card" in (e.label or "") for e in at.expander)


def _rodar(hc: str, **kw):
    at = preencher(novo_app(), **kw)
    texto(at, "hc").set_value(hc)
    return calcular(at)


def test_contratual_30_com_pss_100k_e_ir_40k_bloqueia(monkeypatch, ambiente):
    reg = espiar_motor(monkeypatch)
    at = _rodar("30", pss_modo=VALOR, pss="100.000,00", ir_modo=VALOR, ir="40.000,00")
    assert not at.exception
    msg = [m for m in erros(at) if "negativo" in m]
    assert msg, erros(at)
    m = msg[0]
    # os componentes: total, contratual, PSS, IR e o líquido
    for parte in ("150.000,00", "45.000,00", "100.000,00", "40.000,00", "35.000,00"):
        assert parte in m, (parte, m)
    assert not any("maior que o total" in x for x in erros(at)), \
        "a soma 140.000 cabe no total: este é o buraco que o teste da soma não vê"
    assert not tem_memorial(at) and not _tem_envio(at)
    assert reg["chamadas"] == 1, "a grade de honorários do memorial nem rodou"


def test_mesmos_valores_sem_contratual_passam_com_liquido_10k(monkeypatch, ambiente):
    reg = espiar_motor(monkeypatch)
    at = _rodar("0", pss_modo=VALOR, pss="100.000,00", ir_modo=VALOR, ir="40.000,00")
    assert not at.exception and erros(at) == []
    assert Decimal(reg["res"]["cenario_homologado"]["valor_liquido_atualizado"]) == Decimal("10000.00")
    assert tem_memorial(at) and _tem_envio(at)


def test_pss_declarado_sozinho_com_contratual_bloqueia(monkeypatch):
    """Vale com IR "Não descontar": 150.000 − 45.000 − 110.000 = −5.000."""
    espiar_motor(monkeypatch)
    at = _rodar("30", pss_modo=VALOR, pss="110.000,00", ir_modo=NAO)
    assert any("negativo" in m for m in erros(at)), erros(at)
    assert not tem_memorial(at)


def test_liquido_zero_passa(monkeypatch):
    espiar_motor(monkeypatch)
    at = _rodar("30", pss_modo=VALOR, pss="105.000,00", ir_modo=NAO)
    assert not at.exception and erros(at) == []


@pytest.mark.parametrize("hc", ["0", "30", "50"])
def test_modos_estimados_com_contratual_nao_disparam(monkeypatch, hc):
    """PSS/IR estimados encolhem junto com a base: nunca dão líquido negativo
    por si — o bloqueio não pode atrapalhar o uso normal."""
    espiar_motor(monkeypatch)
    at = _rodar(hc, pss_modo=ALIQ, ir_modo=ESTIM, aliq="14")
    assert not at.exception and erros(at) == []
    assert tem_memorial(at)


def test_bloqueio_persiste_no_rerun(monkeypatch, ambiente):
    espiar_motor(monkeypatch)
    at = _rodar("30", pss_modo=VALOR, pss="110.000,00", ir_modo=NAO)
    at.run()
    assert any("negativo" in m for m in erros(at))
    assert not tem_memorial(at) and not _tem_envio(at)
