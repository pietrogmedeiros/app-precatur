"""Presença literal do valor na conta — a trava da agregação aritmética.

O extrator às vezes soma duas células reais ("Total Partes" + "Total de
Sucumbências") e devolve um número que não está no documento. `valor_presente`
é a regra que pega isso: o VALOR final tem de existir em alguma página da
conta, tolerando só a formatação.

Números inventados — nenhum dado de caso real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prefill.deterministico import centavos, paginas_com_valor, valor_presente  # noqa: E402


def _pg(texto: str = "", tabela=None, pagina: int = 1) -> dict:
    return {"pagina": pagina, "texto": texto, "tabela": tabela or []}


# ── formatos aceitos ─────────────────────────────────────────────────────
@pytest.mark.parametrize("no_documento", [
    "Total Partes 129.979,06",        # brasileiro com ponto de milhar
    "Total Partes 129979,06",         # brasileiro sem ponto de milhar
    "Total Partes 129,979.06",        # americano
    "Total Partes 129 979,06",        # milhar por espaço
    "Total Partes R$129.979,06.",     # colado em R$ e em pontuação
])
def test_formatos_aceitos(no_documento):
    assert valor_presente("129.979,06", [_pg(no_documento)])


@pytest.mark.parametrize("proposto", ["129.979,06", "129979,06", "R$ 129.979,06", "129979.06"])
def test_formato_do_valor_proposto_nao_importa(proposto):
    assert valor_presente(proposto, [_pg("Total 129.979,06")])


def test_milhao_com_varios_grupos():
    assert valor_presente("1.306.006,17", [_pg("TOTAL GERAL 1.306.006,17")])
    assert valor_presente("1.306.006,17", [_pg("TOTAL GERAL 1,306,006.17")])


# ── zero é isento ────────────────────────────────────────────────────────
@pytest.mark.parametrize("zero", ["0", "0,00", "0.00", 0])
def test_zero_e_isento(zero):
    """O prompt manda devolver 0 quando a conta não destaca juros/SELIC."""
    assert valor_presente(zero, [_pg("conta sem linha de juros")])


# ── tabela ───────────────────────────────────────────────────────────────
def test_valor_so_na_celula_da_tabela():
    """O texto corrido pode vir cortado ou fora de ordem; a célula vale."""
    pagina = _pg("Resumo do cálculo", tabela=[["Principal", "100.000,00"],
                                              ["Juros", "50.000,00"]])
    assert valor_presente("50.000,00", [pagina])


# ── a agregação ──────────────────────────────────────────────────────────
def test_valor_agregado_ausente_e_rejeitado():
    """O caso real, com números inventados: as duas parcelas existem, a soma não."""
    conta = [_pg("Total Partes -> 129.979,06\nTotal de Sucumbências -> 25.995,81")]
    assert not valor_presente("155.974,87", conta)         # 129.979,06 + 25.995,81
    assert valor_presente("129.979,06", conta)             # a parcela certa passa


def test_nao_casa_por_substring():
    """1.000,00 não pode ser "achado" dentro de 11.000,00 ou de 1.000,005."""
    conta = [_pg("Total 11.000,00 e fator 1.000,005")]
    assert not valor_presente("1.000,00", conta)


def test_valor_que_nao_e_numero_nao_passa():
    assert not valor_presente("não consta", [_pg("Total 100,00")])
    assert not valor_presente(None, [_pg("Total 100,00")])


# ── escopo: só as páginas recebidas contam ───────────────────────────────
def test_controle_negativo_valor_em_outra_peca_nao_conta():
    """O MESMO número numa outra peça (aqui, o ofício) não salva um valor que o
    modelo compôs: a regra só enxerga as páginas da conta que lhe forem dadas."""
    conta = [_pg("Total Partes 129.979,06", pagina=1)]
    oficio = _pg("Valor requisitado 155.974,87", pagina=2)
    assert not valor_presente("155.974,87", conta)
    assert valor_presente("155.974,87", conta + [oficio])   # prova de que o escopo decide


def test_paginas_com_valor_devolve_onde_aparece():
    paginas = [_pg("Total 100,00", pagina=1), _pg("nada", pagina=2), _pg("de novo 100,00", pagina=3)]
    assert paginas_com_valor("100,00", paginas) == [1, 3]


# ── centavos ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada,esperado", [
    ("1.234,56", 123456), ("1234,56", 123456), ("R$ 1.234,56", 123456),
    ("1234.56", 123456), ("1.234", 123400), (1234.56, 123456), ("abc", None), (None, None),
])
def test_centavos(entrada, esperado):
    assert centavos(entrada) == esperado
