"""Testes OFFLINE da projeção de índices (partes determinísticas — sem rede).

Cobre o que não depende do BACEN: Páscoa/feriados, dias úteis, conversão SELIC
base 252, iteração de meses, e a tolerância do loader à 3ª coluna `origem`.
A parte de rede (fetch Focus/SGS) é validada rodando `scripts/baixar_indices.py`.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))
sys.path.insert(0, str(_RAIZ / "scripts"))

import projecao_focus as pf  # noqa: E402
from precaturia.pipeline.indices import series  # noqa: E402


# ── Páscoa (externamente verificável — pega bug no algoritmo de Meeus) ──

def test_pascoa_datas_conhecidas():
    assert pf._pascoa(2024) == date(2024, 3, 31)
    assert pf._pascoa(2025) == date(2025, 4, 20)
    assert pf._pascoa(2026) == date(2026, 4, 5)
    assert pf._pascoa(2027) == date(2027, 3, 28)


def test_feriados_moveis_derivados_da_pascoa():
    fer = pf._feriados_nacionais(2025)
    p = pf._pascoa(2025)
    assert (p - __import__("datetime").timedelta(days=2)) in fer   # Sexta-Santa
    assert (p + __import__("datetime").timedelta(days=60)) in fer  # Corpus Christi
    assert date(2025, 3, 4) in fer   # Carnaval terça 2025
    assert date(2025, 11, 20) in fer  # Consciência Negra (>=2024)
    assert date(2023, 11, 20) not in pf._feriados_nacionais(2023)


# ── Dias úteis + conversão SELIC base 252 ──

def test_dias_uteis_faixa_plausivel():
    for ano in (2026, 2027):
        for mes in range(1, 13):
            d = pf.dias_uteis(ano, mes)
            assert 17 <= d <= 23, f"{ano}-{mes:02d} = {d}"


def test_selic_conversao_base252():
    # 14% a.a. com 21 dias úteis: ((1.14)**(21/252)-1)*100 ≈ 1.0979 → quantize 1.10
    assert pf.selic_meta_para_mensal_pct(Decimal("14"), 2026, 1) > Decimal("1.0")
    # monotônico: meta maior → mensal maior (mesmo mês)
    baixa = pf.selic_meta_para_mensal_pct(Decimal("10"), 2027, 6)
    alta = pf.selic_meta_para_mensal_pct(Decimal("15"), 2027, 6)
    assert alta > baixa
    # retorna Decimal com 2 casas
    v = pf.selic_meta_para_mensal_pct(Decimal("12"), 2027, 3)
    assert isinstance(v, Decimal) and v == v.quantize(Decimal("0.01"))


def test_iter_meses():
    assert list(pf._iter_meses("2026-11", "2027-02")) == [
        "2026-11", "2026-12", "2027-01", "2027-02",
    ]
    assert list(pf._iter_meses("2027-05", "2027-05")) == ["2027-05"]


# ── Loader ignora a 3ª coluna `origem` (backward-compat) ──

def test_loader_ignora_terceira_coluna(tmp_path):
    csv3 = tmp_path / "x.csv"
    csv3.write_text(
        "# fonte,teste\n# ultimo_real,2026-06\nmes,variacao_pct,origem\n"
        "2026-06,1.12,real\n2026-07,1.05,projetado_selic_focus\n",
        encoding="utf-8",
    )
    serie = series._ler_csv(csv3)
    assert serie == {"2026-06": Decimal("1.12"), "2026-07": Decimal("1.05")}


def test_ultimo_mes_real_le_origem(tmp_path, monkeypatch):
    d = tmp_path / "indices"
    d.mkdir()
    (d / "selic.csv").write_text(
        "# ultimo_real,2026-06\nmes,variacao_pct,origem\n"
        "2026-06,1.12,real\n2026-07,1.05,projetado_selic_focus\n"
        "2026-08,1.02,projetado_selic_focus\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(series, "_DATA_DIR", d)
    assert series.ultimo_mes_real("SELIC") == "2026-06"
