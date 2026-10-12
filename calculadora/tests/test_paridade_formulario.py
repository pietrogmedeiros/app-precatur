"""Paridade entre a tela Streamlit e a camada `formulario.ler`.

Este é o teste que justifica o porte. O app do Precatur não roda Streamlit: ele
manda o formulário por HTTP e `formulario.ler` monta a `EntradaCalculadora`. Se
as duas montagens divergirem em UM campo, o número que o cliente vê muda sem
ninguém perceber — e nenhum teste do motor pegaria, porque o motor estaria certo.

Então aqui se dirige a Calculadora REAL (AppTest, como os testes de UI que já
existiam), espia a entrada que ELA montou, e compara campo por campo com a que a
camada nova monta a partir dos mesmos valores digitados.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from pssir_util import ALIQ, ESTIM, NAO, VALOR, espiar_motor, rodar

import formulario

DATA_CALC = date(2025, 1, 15)

# (nome do caso, kwargs da tela, dicionário equivalente do formulário HTTP)
CASOS = [
    (
        "pss por alíquota + ir estimado",
        dict(pss_modo=ALIQ, aliq="14", ir_modo=ESTIM, meses=36),
        {"pss_modo": "aliquota", "apss": "14", "ir_modo": "estimar", "meses": 36},
    ),
    (
        "pss e ir declarados no ofício",
        dict(pss_modo=VALOR, pss="12.000,00", ir_modo=VALOR, ir="8.500,00"),
        {"pss_modo": "valor", "pss": "12.000,00", "ir_modo": "valor", "ir": "8.500,00",
         # o campo de meses existe sempre na tela (st.form não esconde widget),
         # e o harness o deixa em 12 — o payload equivalente tem de trazê-lo.
         "meses": 12},
    ),
    (
        "nada a descontar",
        dict(pss_modo=NAO, ir_modo=NAO),
        {"pss_modo": "nao", "ir_modo": "nao", "meses": 12},
    ),
    (
        "alíquota fracionada (ponto é decimal, não milhar)",
        dict(pss_modo=ALIQ, aliq="12.500", ir_modo=ESTIM, meses=12),
        {"pss_modo": "aliquota", "apss": "12.500", "ir_modo": "estimar", "meses": 12},
    ),
]

# Campos que a tela preenche por caminhos próprios (query params, seletores que
# este harness não mexe) e que, por isso, não entram na comparação.
FORA = {"honorarios_contratuais_pct", "modalidade", "data_apresentacao",
        "data_expedicao", "valor_superpreferencia",
        "data_pagamento_superpreferencia", "reconciliacao_status"}


def _base_http(extra: dict) -> dict:
    """O mesmo preenchimento de `pssir_util.preencher`, em forma de dicionário."""
    bruto = {
        "modo": "oficio",
        "vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00", "vs": "",
        "data_calculo": DATA_CALC.isoformat(),
        "data_alvo": DATA_CALC.isoformat(),
        "natureza": "remuneratorio",
        "esfera": "auto",
    }
    bruto.update(extra)
    return bruto


@pytest.mark.parametrize("nome,kw_tela,extra_http", CASOS, ids=[c[0] for c in CASOS])
def test_a_camada_http_monta_a_mesma_entrada_que_a_tela(monkeypatch, nome, kw_tela, extra_http):
    reg = espiar_motor(monkeypatch)
    at = rodar(**kw_tela)
    assert not at.exception
    assert "entrada" in reg, "a tela não chamou o motor — caso inválido como referência"

    da_tela = reg["entrada"]
    do_http = formulario.ler(_base_http(extra_http)).entrada

    divergentes = {}
    for campo in dataclasses.fields(formulario.EntradaCalculadora):
        if campo.name in FORA:
            continue
        a = getattr(da_tela, campo.name)
        b = getattr(do_http, campo.name)
        if a != b:
            divergentes[campo.name] = (a, b)
    assert not divergentes, f"divergência tela × http: {divergentes}"


def test_o_resultado_do_motor_e_identico_pelos_dois_caminhos(monkeypatch):
    """A prova em dinheiro: o líquido tem de ser o MESMO número."""
    from precaturia.pipeline import calculadora as motor

    reg = espiar_motor(monkeypatch)
    rodar(pss_modo=ALIQ, aliq="14", ir_modo=ESTIM, meses=36)
    liquido_tela = reg["res"]["cenario_homologado"]["valor_liquido_atualizado"]

    form = formulario.ler(_base_http(
        {"pss_modo": "aliquota", "apss": "14", "ir_modo": "estimar", "meses": 36}))
    liquido_http = motor.calcular_dict(form.entrada)["cenario_homologado"]["valor_liquido_atualizado"]

    assert Decimal(str(liquido_http)) == Decimal(str(liquido_tela))


# ───────────── as recusas: o que a tela bloqueia, a camada bloqueia ─────────────

@pytest.mark.parametrize("extra,trecho", [
    ({"pss_modo": "valor", "pss": ""}, "sem valor"),
    ({"pss_modo": "valor", "pss": "abc"}, "inválido"),
    ({"pss_modo": "valor", "pss": "-10"}, "negativo"),
    ({"pss_modo": "aliquota", "apss": ""}, "informe a alíquota"),
    ({"pss_modo": "aliquota", "apss": "0"}, "maior que 0"),
    ({"pss_modo": "aliquota", "apss": "150"}, "0 a 100"),
    ({"ir_modo": "valor", "ir": ""}, "sem valor"),
    ({"hc": "150"}, "0 a 100"),
    ({"hs": "-1"}, "0 a 100"),
    ({"data_calculo": ""}, "obrigatória"),
])
def test_preenchimento_invalido_bloqueia_antes_do_motor(extra, trecho):
    with pytest.raises(formulario.ErroDeFormulario) as exc:
        formulario.ler(_base_http(extra))
    assert any(trecho.lower() in e.lower() for e in exc.value.erros), exc.value.erros


def test_modo_originario_exige_valor_e_data_base():
    with pytest.raises(formulario.ErroDeFormulario) as exc:
        formulario.ler({"modo": "originario", "data_calculo": "2025-01-15"})
    assert any("valor originário" in e.lower() for e in exc.value.erros)
    assert any("data-base" in e.lower() for e in exc.value.erros)


def test_modo_originario_com_natureza_historica_nao_manda_regime_do_preset():
    """Natureza histórica e preset SGS são caminhos excludentes — mandar os dois
    faria o motor corrigir duas vezes."""
    form = formulario.ler({
        "modo": "originario", "vo": "10.000,00",
        "data_base": "2010-01-01", "data_calculo": "2020-01-01",
        "nat_hist": "servidor", "regime": "simples-ipca-e",
    })
    assert form.entrada.natureza == "servidor"
    assert form.entrada.regime is None


def test_esfera_auto_deduz_federal_pelo_ente():
    assert formulario.ler(_base_http({"ente": "União"})).entrada.esfera == "federal"
    assert formulario.ler(_base_http({"ente": "INSS"})).entrada.esfera == "federal"
    assert formulario.ler(_base_http(
        {"ente": "Estado da Bahia"})).entrada.esfera == "estadual"
    # explícito vence a dedução
    assert formulario.ler(_base_http(
        {"ente": "União", "esfera": "estadual"})).entrada.esfera == "estadual"


def test_sucumbencial_nao_entra_no_motor():
    """Ele não sai do líquido do credor — só aparece no memorial."""
    form = formulario.ler(_base_http({"hs": "10"}))
    assert form.entrada.honorarios_sucumbenciais_pct is None
    assert form.honorarios_sucumbenciais_pct == Decimal("10")
