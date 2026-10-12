"""Leitura de número digitado (formato BR e afins) — `numeros.py`.

A tabela é o contrato de `parse_dec` da Calculadora: a tela só embrulha estas
funções (vazio → None; inválido → aviso/erro conforme o campo).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

import numeros

VALIDOS = [
    # BR com milhar e decimal
    ("1.234,56", "1234.56"),
    ("R$ 1.234,56", "1234.56"),
    ("r$1.234,56", "1234.56"),
    ("1 234,56", "1234.56"),            # espaço solto é ruído
    ("1.234,5", "1234.5"),
    ("0,5", "0.5"),
    ("1234,56", "1234.56"),
    # americano: o ÚLTIMO separador é o decimal
    ("1,234.56", "1234.56"),
    ("1,234,567.89", "1234567.89"),
    # só ponto: milhar quando casa ^[1-9]\d{0,2}(\.\d{3})+$, senão decimal
    ("5.000", "5000"),
    ("1.234", "1234"),
    ("999.999", "999999"),
    ("1.234.567", "1234567"),
    ("1234.56", "1234.56"),
    ("1234.567", "1234.567"),           # 4 dígitos antes do ponto: decimal
    ("0.5", "0.5"),
    ("0.500", "0.5"),                   # zero à esquerda: nunca é milhar
    ("12.5", "12.5"),
    ("5000", "5000"),
    ("0", "0"),
    ("0,00", "0"),
    # sinal passa (quem proíbe negativo é a regra do campo, não o parse)
    ("-500,00", "-500"),
    ("-1.234,56", "-1234.56"),
]

VAZIOS = ["", "   ", "\t", "R$", " R$ ", None]

INVALIDOS = [
    "abc", "R$ abc", "1e3", "1E3", "NaN", "nan", "Infinity", "-Infinity", "inf",
    "1,234,567",        # várias vírgulas sem ponto decimal: ambíguo → recusa
    "1.23.4", "12.34.567", "1..2", "1,,2", "1.234,56,7", "1,234.56.7",
    "--5", "+5", "5-", "1.234,5a", ",", ".", "1,", ",5",
    "١٢٣",               # dígitos não-ASCII
]


@pytest.mark.parametrize("texto, esperado", VALIDOS)
def test_parse_valido(texto, esperado):
    assert numeros.parse_decimal_br(texto) == Decimal(esperado)


@pytest.mark.parametrize("texto", VAZIOS)
def test_parse_vazio_e_none(texto):
    assert numeros.parse_decimal_br(texto) is None


@pytest.mark.parametrize("texto", INVALIDOS)
def test_parse_invalido_levanta(texto):
    with pytest.raises(ValueError):
        numeros.parse_decimal_br(texto)


def test_resultado_valido_e_sempre_finito():
    for texto, _ in VALIDOS:
        assert numeros.parse_decimal_br(texto).is_finite()


# ── semeadura: Decimal → texto do campo, sem ambiguidade ─────────────────────

@pytest.mark.parametrize("semente, esperado", [
    ("987.650", "987,650"),     # forma ambígua (1–3 dígitos + 3 decimais)
    ("1.234", "1,234"),
    ("999.999", "999,999"),
    ("150000.00", "150000.00"), # inequívoco: não mexe (os testes de snapshot esperam isso)
    ("1234.56", "1234.56"),
    ("0.500", "0.500"),
    ("5000", "5000"),
    ("20", "20"),
    ("22.5", "22.5"),
    ("", ""),
])
def test_para_semente(semente, esperado):
    assert numeros.para_semente(semente) == esperado


@pytest.mark.parametrize("valor", [
    "987.650", "1.234", "12.500", "999.999", "0.500", "1234.567", "150000.00",
    "1234.56", "5000", "0", "0.05", "100.5",
])
def test_ida_e_volta_da_semente_preserva_o_valor(valor):
    """Snapshot grava `str(Decimal)`; reabrir semeia e a tela LÊ de novo. O que
    o parse devolve tem de ser o mesmo número que foi gravado."""
    assert numeros.parse_decimal_br(numeros.para_semente(valor)) == Decimal(valor)


# ── percentual: ponto é SEMPRE decimal (milhar=False) ────────────────────────

PERCENTUAIS_VALIDOS = [
    ("12.500", "12.5"),     # a leitura de milhar tornaria isto 12500%
    ("7.500", "7.5"),
    ("14.500", "14.5"),
    ("12,5", "12.5"),
    ("12.5", "12.5"),
    ("12,500", "12.5"),     # semente de snapshot (para_semente)
    ("10.000", "10"),       # ponto decimal: 10,000 = 10 (não há milhar em %)
    ("30", "30"),
    ("0", "0"),
    ("100", "100"),
    ("22,50", "22.5"),
    ("0.5", "0.5"),
    ("150.000", "150"),     # legível; quem o recusa é o intervalo 0–100 do campo
    ("-5", "-5"),           # sinal passa; proibir negativo é regra do campo
]

PERCENTUAIS_INVALIDOS = [
    "abc", "NaN", "Infinity", "1e2", "12.5.5", "1,2,3", "--1", "1.234,5", "1,234.5",
    "12%", ".", ",", "5.", ".5", ",5",
]


@pytest.mark.parametrize("texto, esperado", PERCENTUAIS_VALIDOS)
def test_percentual_valido(texto, esperado):
    assert numeros.parse_decimal_br(texto, milhar=False) == Decimal(esperado)


@pytest.mark.parametrize("texto", PERCENTUAIS_INVALIDOS)
def test_percentual_invalido_levanta(texto):
    with pytest.raises(ValueError):
        numeros.parse_decimal_br(texto, milhar=False)


@pytest.mark.parametrize("texto", ["", "   ", None])
def test_percentual_vazio_e_none(texto):
    assert numeros.parse_decimal_br(texto, milhar=False) is None


def test_milhar_continua_sendo_o_padrao_dos_campos_de_valor():
    assert numeros.parse_decimal_br("12.500") == Decimal("12500")
    assert numeros.parse_decimal_br("12.500", milhar=True) == Decimal("12500")
    assert numeros.parse_decimal_br("12.500", milhar=False) == Decimal("12.5")
