"""Catálogo de marcadores (prefill/marcadores.py): cada caso vem de um achado
do levantamento de palavras-chave de 28/10/2026 (índice precatur-palavras-chave)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prefill import marcadores as M  # noqa: E402
from prefill.pipeline import TIPO_CONTA, TIPO_OFICIO, _label_pagina  # noqa: E402


def tipo(texto: str):
    return M.classificar(texto)["tipo"]


# ── ofício ──────────────────────────────────────────────────────────────
def test_formulario_res_303_tjmg_sem_a_palavra_requisitorio():
    # 83% dos ofícios do corpus não dizem "ofício requisitório"
    t = ("Exmo(a). Senhor(a) Presidente do Tribunal de Justiça do Estado de Minas Gerais,\n"
         "OFÍCIO PRECATÓRIO - BENEFICIÁRIO PRINCIPAL\n1. Informações processuais\n"
         "1.1. Numeração única do processo judicial: 5000000-00.2020.8.13.0024\n")
    r = M.classificar(t)
    assert r["tipo"] == M.OFICIO and r["nivel"] == "forte"


def test_intimacao_que_cita_rpv_nao_e_oficio():
    # "Intimação de Ofício de RPV" (30 casos): cita, não é o formulário
    t = "Fica a parte intimada da expedição do RPV nº 123/2024. Data-base 01/2024."
    assert tipo(t) is None


def test_peticao_que_pede_expedicao_nao_e_oficio():
    t = ("Requer a expedição de ofício requisitório, com data-base em 01/2024 e "
         "natureza do crédito alimentar. Termos em que pede deferimento.")
    assert tipo(t) is None


def test_oficio_fraco_com_campo_do_formulario():
    t = "OFÍCIO REQUISITÓRIO Nº 55/2024\nNatureza do crédito: alimentar\n"
    r = M.classificar(t)
    assert r["tipo"] == M.OFICIO and r["nivel"] == "fraco+conteudo"


def test_rpv_sozinho_nao_decide():
    assert tipo("Pagamento da RPV conforme decisão anterior.") is None


def test_oficio_provisorio_e_sinalizado():
    assert M.classificar("Requisição de pagamento (prévia)")["provisorio"]


# ── conta ───────────────────────────────────────────────────────────────
def test_totalizacao_da_contadoria_sem_sistema_gerador():
    # TJMG: a contadoria não escreve "Projef"/"SICAR"; o rótulo do formulário basta
    t = "I - PARTES\nTotal Partes -> 120.000,00\nII - SUCUMBÊNCIAS\nIII - TOTALIZAÇÃO\n"
    r = M.classificar(t)
    assert r["tipo"] == M.CONTA and r["nivel"] == "forte"


def test_conta_por_conteudo_com_tabela():
    t = ("Valor corrigido  Juros de mora\n" + "1.000,00 2.000,00 3.000,00 4.000,00 5.000,00\n")
    assert tipo(t) == M.CONTA


def test_conteudo_sem_tabela_exige_tres():
    assert tipo("valor corrigido e juros de mora conforme sentença") is None


def test_rmi_do_inss_e_vetado():
    t = ("Renda mensal inicial  Período básico de cálculo  valor corrigido  juros de mora "
         "índice de correção\n" + "1.000,00 " * 6)
    assert tipo(t) is None


def test_oficio_com_principal_corrigido_nao_vira_conta():
    # o formulário tem "principal corrigido", "juros moratórios", "data-base"
    t = ("REQUISIÇÃO DE PAGAMENTO\nValor do principal corrigido: 1.000,00\n"
         "Valor dos juros moratórios: 500,00\nData-base: 01/2024\nValor bruto: 1.500,00\n")
    assert tipo(t) == M.OFICIO


def test_cedilha_perdida_e_maiusculas():
    assert M.conta_forte("CÁLCULO DE LIQUIDAÇAO\nRESUMO DO CALCULO")


# ── rótulo do sistema ───────────────────────────────────────────────────
@pytest.mark.parametrize("rodape,esperado", [
    ("Evento 45, PLAN1, Página 2", M.CONTA),
    ("Evento 80, RPV1, Página 1", M.OFICIO),
    ("Evento 81, PREC2, Página 3", M.OFICIO),
])
def test_rodape_do_eproc(rodape, esperado):
    r = M.classificar("texto qualquer da página\n" + rodape)
    assert r["tipo"] == esperado and r["nivel"] == "rotulo_sistema"


def test_peticao_no_eproc_so_aceita_forte():
    # a petição transcreve a conta: conteúdo de conta não pode rotular
    t = ("valor corrigido juros de mora índice de correção 1.000,00 2.000,00 3.000,00 "
         "4.000,00 5.000,00\nEvento 12, PET1, Página 4")
    assert tipo(t) is None


def test_trf1_oficio_enviando_informacoes_nao_e_requisitorio():
    assert M.rotulo_sistema(M.normalizar("Documento id 99887 - Ofício enviando informações"))["tipo"] == M.NAO_ALVO
    assert M.rotulo_sistema(M.normalizar("Documento id 99887 - Ofício requisitório"))["tipo"] == M.OFICIO


# ── integração com o pipeline ───────────────────────────────────────────
def test_label_pagina_usa_o_catalogo():
    of = {"texto": "OFÍCIO PRECATÓRIO - BENEFICIÁRIO PRINCIPAL\nNatureza do crédito"}
    ct = {"texto": "Total de Sucumbências -> 10.000,00"}
    intim = {"texto": "Ficam as partes intimadas do ofício requisitório expedido."}
    assert _label_pagina(of, 1, None) == TIPO_OFICIO
    assert _label_pagina(ct, 2, None) == TIPO_CONTA
    assert _label_pagina(intim, 3, None) is None


def test_ids_unicos_e_catalogo_no_formato_do_indice():
    ids = [m.id for m in M.MARCADORES]
    assert len(ids) == len(set(ids))
    for doc in M.catalogo():
        assert doc["tipo_registro"] == "marcador" and doc["regex"]
