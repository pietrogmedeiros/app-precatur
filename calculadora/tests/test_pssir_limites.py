"""Limites do valor declarado de PSS/IR: negativo e maior que o bruto.

Regras (30/09/2026):
  - negativo ou não finito é INVÁLIDO (mesmo tratamento do campo vazio);
  - PSS + IR declarados maiores que o total bruto ATUALIZADO = líquido negativo
    por construção: erro visível, sem memorial e sem envio ao card;
  - declarados iguais ao total ainda passam (líquido zero é conta válida).
O valor declarado continua NOMINAL (não é corrigido) — a comparação é contra o
total atualizado que o motor devolve, sem alterar o motor.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pssir_util import (VALOR, erros, espiar_motor, rodar, tem_memorial)


@pytest.fixture
def ambiente(monkeypatch):
    """Com o webhook no ambiente o expander de envio ao card APARECE — é o que
    torna o "não aparece" dos testes abaixo uma afirmação de verdade."""
    monkeypatch.setenv("BITRIX_WEBHOOK", "https://exemplo.invalido/rest/1/token")
    monkeypatch.setenv("HUB_URL", "https://exemplo.invalido/api")


def _tem_envio(at) -> bool:
    return any("Enviar para o card" in (e.label or "") for e in at.expander)


def test_controle_valores_normais_mostram_memorial_e_envio(monkeypatch, ambiente):
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="1.234,56", ir_modo=VALOR, ir="987,65")
    assert not at.exception and erros(at) == []
    assert tem_memorial(at)
    assert _tem_envio(at), "sem isto os testes de bloqueio não provam nada"


@pytest.mark.parametrize("campo, kw", [
    ("PSS", dict(pss_modo=VALOR, pss="-500,00")),
    ("PSS", dict(pss_modo=VALOR, pss="-0,01")),
    ("IR", dict(ir_modo=VALOR, ir="-1,00")),
])
def test_negativo_e_invalido(monkeypatch, campo, kw):
    reg = espiar_motor(monkeypatch)
    at = rodar(**kw)
    assert not at.exception
    assert any(campo in m and "negativ" in m for m in erros(at)), erros(at)
    assert "entrada" not in reg
    assert not tem_memorial(at)


def test_pss_maior_que_o_total_bloqueia_memorial_e_envio(monkeypatch, ambiente):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="200.000,00", ir_modo=VALOR, ir="987,65")
    assert not at.exception
    msgs = erros(at)
    assert any("maior que o total" in m for m in msgs), msgs
    assert not tem_memorial(at)
    assert not _tem_envio(at)
    # só a chamada que apurou o total: a grade de honorários do memorial nem rodou
    assert reg["chamadas"] == 1


def test_soma_de_pss_e_ir_maior_que_o_total_tambem_bloqueia(monkeypatch, ambiente):
    """Cada um cabe no total; juntos, não — líquido negativo do mesmo jeito."""
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="100.000,00", ir_modo=VALOR, ir="60.000,00")
    assert any("maior que o total" in m for m in erros(at)), erros(at)
    assert not tem_memorial(at) and not _tem_envio(at)


def test_ir_sozinho_maior_que_o_total_bloqueia(monkeypatch):
    espiar_motor(monkeypatch)
    at = rodar(ir_modo=VALOR, ir="150.000,01")
    assert any("maior que o total" in m for m in erros(at)), erros(at)


def test_igual_ao_total_passa_com_liquido_zero(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="100.000,00", ir_modo=VALOR, ir="50.000,00")
    assert not at.exception and erros(at) == []
    assert Decimal(reg["res"]["cenario_homologado"]["valor_liquido_atualizado"]) == 0


def test_mensagem_traz_os_valores_para_o_advogado_conferir(monkeypatch):
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="200.000,00")
    m = [m for m in erros(at) if "maior que o total" in m][0]
    assert "200.000,00" in m and "150.000,00" in m


def test_estimado_nao_dispara_o_limite(monkeypatch):
    """O limite é do valor DECLARADO; PSS/IR estimados vêm do motor e não
    passam por esta checagem."""
    from pssir_util import ALIQ, ESTIM
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=ALIQ, ir_modo=ESTIM, aliq="14")
    assert not at.exception and erros(at) == []
    assert tem_memorial(at)


def test_bloqueio_persiste_no_rerun_depois_do_calcular(monkeypatch, ambiente):
    """Qualquer outro clique reexecuta o bloco (o `_ja_calculou` recalcula):
    o bloqueio tem de valer nele também, não só no primeiro clique."""
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="200.000,00")
    assert any("maior que o total" in m for m in erros(at))
    at.run()
    assert any("maior que o total" in m for m in erros(at))
    assert not tem_memorial(at) and not _tem_envio(at)
