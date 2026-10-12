"""Leitura de número digitado nos campos de valor da Calculadora.

Puro (sem Streamlit) para poder ser testado sozinho. A tela embrulha
`parse_decimal_br` em `parse_dec` (Calculadora.py) e decide o que fazer com o
`ValueError` conforme o campo: aviso nos campos comuns, erro que bloqueia o
cálculo nos campos de PSS/IR do modo "Valor da conta".

O texto chega por três caminhos — digitado, extraído do ofício pelo LLM (que é
instruído a devolver formato BR, "1.234.567,89") e semeado de um snapshot
(`str(Decimal)`, com ponto decimal). O único texto ambíguo entre eles é o de UM
ponto seguido de exatamente três dígitos ("5.000"): BR diz milhar, `str(Decimal)`
diz decimal. Este módulo lê como milhar; `para_semente` cuida de que o
snapshot nunca produza essa forma.
"""
from __future__ import annotations

import re
from decimal import Decimal

_MILHAR_PONTO = re.compile(r"[1-9][0-9]{0,2}(\.[0-9]{3})+")
_SO_PONTO_DECIMAL = re.compile(r"[0-9]+\.[0-9]+")
_SO_VIRGULA_DECIMAL = re.compile(r"[0-9]+,[0-9]+")
_AMBIGUO_DE_SEMENTE = re.compile(r"-?[1-9][0-9]{0,2}\.[0-9]{3}")
_CARACTERES = re.compile(r"[0-9.,]+")


def parse_decimal_br(texto: str | None, milhar: bool = True) -> Decimal | None:
    """Texto digitado → Decimal. Vazio → None. Inválido → ValueError.

    Regras:
      - remove "R$" e qualquer espaço;
      - ponto e vírgula juntos: o ÚLTIMO separador é o decimal, o outro é
        milhar e tem de agrupar de 3 em 3 ("1.234,56" e "1,234.56");
      - só vírgula: ela é o decimal, e só pode haver uma;
      - só ponto: milhar quando casa ^[1-9]\\d{0,2}(\\.\\d{3})+$ ("5.000",
        "1.234.567"); senão decimal ("1234.56", "0.5");
      - só dígitos, ponto, vírgula e um "-" inicial: NaN, Infinity, notação
        científica ("1e3") e o resto são inválidos.
    O sinal passa; proibir negativo é regra do campo, não do parse.

    `milhar=False` é a leitura de PERCENTUAL (contratuais, sucumbenciais,
    alíquota do PSS), que não tem separador de milhar: o ponto é SEMPRE decimal
    ("12.500" → 12,5, não 12500), a vírgula também, e usar os dois juntos é
    inválido. O padrão (`milhar=True`) é o dos campos em R$.
    """
    if texto is None:
        return None
    s = re.sub(r"R\$", "", str(texto), flags=re.IGNORECASE)
    s = re.sub(r"\s+", "", s)
    if not s:
        return None
    negativo = s.startswith("-")
    if negativo:
        s = s[1:]
    if not _CARACTERES.fullmatch(s):
        raise ValueError("use só dígitos, vírgula e ponto")

    if "," in s and "." in s:
        if not milhar:
            raise ValueError("percentual não usa separador de milhar")
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        mil = "." if dec == "," else ","
        inteiro, _, frac = s.rpartition(dec)
        agrupado = re.fullmatch(r"[0-9]{1,3}(" + re.escape(mil) + r"[0-9]{3})+", inteiro)
        if not agrupado or not re.fullmatch(r"[0-9]+", frac):
            raise ValueError("separadores de milhar/decimal fora do padrão")
        s = inteiro.replace(mil, "") + "." + frac
    elif "," in s:
        if not _SO_VIRGULA_DECIMAL.fullmatch(s):
            raise ValueError("vírgula decimal ambígua")
        s = s.replace(",", ".")
    elif "." in s:
        if milhar and _MILHAR_PONTO.fullmatch(s):
            s = s.replace(".", "")
        elif not _SO_PONTO_DECIMAL.fullmatch(s):
            raise ValueError("ponto fora do padrão")

    valor = Decimal(s)
    return -valor if negativo and valor != 0 else valor


def para_semente(texto):
    """Texto de campo numérico semeado por MÁQUINA (snapshot) → sem ambiguidade.

    `str(Decimal("987.650"))` é "987.650", que `parse_decimal_br` leria como
    987650. Nessa forma (e só nela) o ponto vira vírgula — "987,650" — que o
    parse lê como decimal. Qualquer outra forma volta como veio, então
    "150000.00", "1234.56" e "20" seguem idênticos ao que os testes de snapshot
    esperam.
    """
    if isinstance(texto, str) and _AMBIGUO_DE_SEMENTE.fullmatch(texto):
        return texto.replace(".", ",")
    return texto
