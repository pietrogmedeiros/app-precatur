"""Campos de PERCENTUAL (contratuais, sucumbenciais, alíquota do PSS).

Percentual não tem milhar: "12.500" é 12,5 — e não 12.500%, que era o que a
leitura de valor em R$ fazia. Fora de 0–100, negativo ou ilegível: erro que
bloqueia o cálculo (mesmo padrão do PSS/IR). Campo VAZIO:
  - contratuais vazio → sem desconto (líquido = bruto; a tela já avisa no
    pré-preenchimento);
  - sucumbenciais vazio → sem linha no memorial;
  - alíquota vazia no modo "Por alíquota" → BLOQUEIA (decisão do time em
    30/09/2026; antes caía em 14% no motor — ver test_aliquota_padrao.py).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pssir_util import (ALIQ, NAO, calcular, erros, espiar_motor, novo_app,
                        preencher, tem_memorial, texto)


def _rodar_pct(**campos):
    at = preencher(novo_app(), pss_modo=campos.pop("pss_modo", NAO),
                   aliq=campos.pop("apss", None))
    for k, v in campos.items():
        texto(at, k).set_value(v)
    return calcular(at)


@pytest.mark.parametrize("digitado, esperado", [
    ("12.500", "12.5"), ("7.500", "7.5"), ("12,5", "12.5"), ("12.5", "12.5"),
    ("30", "30"), ("10.000", "10"),
])
def test_contratuais_le_o_percentual_sem_milhar(monkeypatch, digitado, esperado):
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(hc=digitado)
    assert not at.exception and erros(at) == []
    assert reg["entrada"].honorarios_contratuais_pct == Decimal(esperado)


@pytest.mark.parametrize("campo, rotulo", [("hc", "Contratuais"), ("hs", "Sucumbência")])
@pytest.mark.parametrize("digitado", ["150", "100,5", "150.000", "-1", "abc", "NaN", "1e2"])
def test_percentual_de_honorario_fora_do_intervalo_ou_ilegivel_bloqueia(
        monkeypatch, campo, rotulo, digitado):
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(**{campo: digitado})
    assert not at.exception
    assert any(rotulo in m and "0 a 100" in m for m in erros(at)), erros(at)
    assert "entrada" not in reg, "o motor não pode ter rodado"
    assert not tem_memorial(at)


def test_sucumbenciais_valido_nao_bloqueia(monkeypatch):
    espiar_motor(monkeypatch)
    at = _rodar_pct(hs="7.500")
    assert not at.exception and erros(at) == []
    assert tem_memorial(at)


@pytest.mark.parametrize("digitado, esperado", [
    ("7.500", "7.5"), ("14.500", "14.5"), ("11,5", "11.5"), ("14", "14"),
])
def test_aliquota_do_pss_le_o_percentual_sem_milhar(monkeypatch, digitado, esperado):
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(pss_modo=ALIQ, apss=digitado)
    assert not at.exception and erros(at) == []
    assert reg["entrada"].aliquota_pss_pct == Decimal(esperado)
    # e o PSS sai sobre 100.000 a 7,5% — não a 7.500%
    assert Decimal(reg["res"]["cenario_homologado"]["valor_pss"]) < Decimal("100000")


@pytest.mark.parametrize("digitado", ["150", "-3", "abc", "NaN"])
def test_aliquota_invalida_bloqueia_no_modo_por_aliquota(monkeypatch, digitado):
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(pss_modo=ALIQ, apss=digitado)
    assert any("líquota" in m and "0 a 100" in m for m in erros(at)), erros(at)
    assert "entrada" not in reg


def test_aliquota_ilegivel_em_outro_modo_e_ignorada(monkeypatch):
    """O campo da alíquota fica sempre visível; só vale no modo "Por alíquota"."""
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(pss_modo=NAO, apss="abc")
    assert not at.exception and erros(at) == []
    assert "entrada" in reg


# ── campo vazio: comportamento de hoje, preservado ───────────────────────────

def test_vazio_nao_e_erro_e_nada_muda(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(hc="", hs="")
    assert not at.exception and erros(at) == []
    assert reg["entrada"].honorarios_contratuais_pct is None
    cen = reg["res"]["cenario_homologado"]
    assert Decimal(cen["valor_liquido_atualizado"]) == Decimal("150000.00"), \
        "contratual vazio = sem desconto (líquido igual ao bruto), como sempre foi"


def test_aliquota_vazia_no_modo_por_aliquota_bloqueia(monkeypatch):
    """MUDANÇA DELIBERADA (30/09/2026): este teste afirmava que a alíquota vazia
    caía em 14% no motor, sem erro. O time decidiu que vazio bloqueia — o
    advogado que apaga o campo não sabia que valeria 14%."""
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(pss_modo=ALIQ, apss="")
    assert not at.exception
    assert any("informe a alíquota" in m for m in erros(at)), erros(at)
    assert "entrada" not in reg


# ── formatos que o pré-preenchimento pode gerar ──────────────────────────────

@pytest.mark.parametrize("hc_url, esperado", [
    ("30", "30"),          # card/LLM: número puro
    ("22,5", "22.5"),      # card com vírgula (bitrix._pct aceita)
    ("30.0", "30.0"),      # JSON number do LLM → str(float)
    ("12.500", "12.5"),    # três casas: milhar não existe em %
    ("10.000", "10"),
])
def test_percentual_chegando_por_url_e_lido_certo(monkeypatch, hc_url, esperado):
    reg = espiar_motor(monkeypatch)
    at = novo_app({"hc": hc_url})
    assert texto(at, "hc").value == hc_url
    preencher(at)
    calcular(at)
    assert not at.exception and erros(at) == []
    assert reg["entrada"].honorarios_contratuais_pct == Decimal(esperado)


def test_percentual_absurdo_por_url_bloqueia(monkeypatch):
    """Um "150.000" do LLM (150) chega no campo e é barrado no cálculo."""
    reg = espiar_motor(monkeypatch)
    at = novo_app({"hc": "150.000"})
    preencher(at)
    calcular(at)
    assert any("Contratuais" in m and "0 a 100" in m for m in erros(at)), erros(at)
    assert "entrada" not in reg


# ── alíquota ZERO no modo "Por alíquota": o motor a trocaria por 14% ─────────

MSG_ALIQUOTA_ZERO = "Informe uma alíquota maior que 0 ou escolha Não descontar"


@pytest.mark.parametrize("digitado", ["0", "0,00", "0.0", "0,0", "00"])
def test_aliquota_zero_no_modo_por_aliquota_bloqueia(monkeypatch, digitado):
    """O motor trata alíquota <= 0 como "não informada" e usa 14% — o advogado
    digitou 0 esperando zero e o memorial sairia com 14%, sem aviso."""
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(pss_modo=ALIQ, apss=digitado)
    assert not at.exception
    assert any(MSG_ALIQUOTA_ZERO in m for m in erros(at)), erros(at)
    assert "entrada" not in reg, "o motor não pode ter rodado"
    assert not tem_memorial(at)


def test_aliquota_zero_em_outro_modo_continua_ignorada(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(pss_modo=NAO, apss="0")
    assert not at.exception and erros(at) == []
    assert "entrada" in reg


def test_aliquota_minuscula_positiva_passa(monkeypatch):
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(pss_modo=ALIQ, apss="0,01")
    assert not at.exception and erros(at) == []
    assert reg["entrada"].aliquota_pss_pct == Decimal("0.01")


@pytest.mark.parametrize("campo", ["hc", "hs"])
def test_zero_continua_valido_nos_honorarios(monkeypatch, campo):
    """A regra do zero é só da alíquota: 0% de honorário é "sem honorário"."""
    reg = espiar_motor(monkeypatch)
    at = _rodar_pct(**{campo: "0"})
    assert not at.exception and erros(at) == []
    assert "entrada" in reg

