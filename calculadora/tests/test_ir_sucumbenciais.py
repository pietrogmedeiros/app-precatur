"""IR sobre o sucumbencial: 3% no requisitório federal, 27,5% nos demais
(pedido do Matheus, 09/11/2026). Só exibição no memorial — não toca líquido."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import formulario  # noqa: E402
import memorial  # noqa: E402

_BASE = {"modo": "oficio", "vt": "150.000,00", "vp": "100.000,00", "vj": "50.000,00",
         "data_calculo": "2025-01-01", "data_alvo": "2025-01-01",
         "natureza": "remuneratorio", "hs": "10"}


@pytest.mark.parametrize("extra,esperado", [
    ({"esfera": "federal"}, "3"),
    ({"esfera": "auto", "ente": "União"}, "3"),
    ({"esfera": "estadual"}, "27.5"),
    ({"esfera": "auto"}, "27.5"),
    ({"esfera": "federal", "ir_suc": "27.5"}, "27.5"),   # escolha explícita ganha
    ({"esfera": "estadual", "ir_suc": "3"}, "3"),
    ({"esfera": "estadual", "ir_suc": "lixo"}, "27.5"),  # valor fora da lista = automático
])
def test_aliquota_do_ir_sucumbencial(extra, esperado):
    assert formulario.ler({**_BASE, **extra}).ir_sucumbenciais_pct == Decimal(esperado)


def test_memorial_desconta_3_por_cento_no_federal():
    html = memorial._honorarios_html({}, Decimal("10"), Decimal("1000.00"), Decimal("3"))
    assert "(−) IR sobre os sucumbenciais (3%)" in html
    assert "970,00" in html


def test_memorial_sem_aliquota_continua_em_27_5():
    html = memorial._honorarios_html({}, Decimal("10"), Decimal("1000.00"))
    assert "27,5%" in html and "725,00" in html
