"""Modo "Valor no ofício (R$)" com campo vazio ou inválido: erro, não estimativa.

Antes: o campo vazio (ou o texto inválido, que só gerava um aviso) virava
`valor_pss=None`, e com a natureza informada o motor ESTIMAVA sozinho — 14% de
PSS e IR-RRA (com meses=1, se os meses ficassem em 0, inflando o IR) — enquanto
o memorial rotulava o modo como "Valor no ofício". Agora o cálculo é bloqueado
com uma mensagem que diz o que fazer.
"""
from __future__ import annotations

import pytest

from pssir_util import (ALIQ, ESTIM, NAO, VALOR, erros, espiar_motor,
                        rodar, tem_memorial)


def _bloqueado(at, reg, palavra_chave: str):
    assert not at.exception, [e.value for e in at.exception]
    msgs = erros(at)
    assert any(palavra_chave in m and "outro modo" in m for m in msgs), msgs
    assert "entrada" not in reg, "o motor não pode ter sido chamado"
    assert not tem_memorial(at), "sem cálculo não há memorial"


@pytest.mark.parametrize("texto", ["", "   ", "abc", "1e3", "NaN", "Infinity", "1,234,567"])
def test_pss_vazio_ou_invalido_bloqueia_o_calculo(monkeypatch, texto):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss=texto)
    _bloqueado(at, reg, "PSS")


@pytest.mark.parametrize("texto", ["", "abc", "NaN"])
def test_ir_vazio_ou_invalido_bloqueia_o_calculo(monkeypatch, texto):
    reg = espiar_motor(monkeypatch)
    at = rodar(ir_modo=VALOR, ir=texto)
    _bloqueado(at, reg, "IR")


def test_vazio_com_meses_zero_nao_infla_o_ir_em_silencio(monkeypatch):
    """O pior caso do comportamento antigo: meses=0 (default da tela) fazia o
    motor assumir 1 mês e estimar um IR-RRA de ~R$ 22.741 sobre a base."""
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="1.234,56", ir_modo=VALOR, ir="", meses=0)
    _bloqueado(at, reg, "IR")


def test_os_dois_vazios_listam_os_dois_erros(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="", ir_modo=VALOR, ir="")
    msgs = " | ".join(erros(at))
    assert "PSS" in msgs and "IR" in msgs
    assert "entrada" not in reg


def test_mensagem_do_invalido_mostra_o_que_foi_digitado(monkeypatch):
    espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="12abc")
    assert any("12abc" in m for m in erros(at))


@pytest.mark.parametrize("modo_pss, modo_ir", [(NAO, NAO), (ALIQ, ESTIM)])
def test_texto_invalido_em_outro_modo_e_ignorado(monkeypatch, modo_pss, modo_ir):
    """O erro só vale para o modo "Valor no ofício": em qualquer outro, o texto
    que sobrou no campo não incomoda nem bloqueia."""
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=modo_pss, pss="abc", ir_modo=modo_ir, ir="", aliq="14")
    assert not at.exception
    assert erros(at) == []
    assert "entrada" in reg


def test_zero_explicito_no_modo_valor_e_valido(monkeypatch):
    """"0" é uma resposta (conta sem PSS), diferente de campo vazio."""
    from decimal import Decimal
    reg = espiar_motor(monkeypatch)
    at = rodar(pss_modo=VALOR, pss="0", ir_modo=VALOR, ir="0,00")
    assert not at.exception and erros(at) == []
    assert reg["entrada"].valor_pss == Decimal("0")
    assert reg["entrada"].valor_ir == Decimal("0")
