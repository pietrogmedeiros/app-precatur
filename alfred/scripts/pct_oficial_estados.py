# -*- coding: utf-8 -*-
"""Percentual do §23 (% da RCL) HOMOLOGADO pelo tribunal para o GOVERNO DO ESTADO.

Existe porque a fonte oficial dos municipios (nacp_plano da BA, enquadramento do TJMG)
nao cobre os Estados: sem este arquivo o Estado cai na escada por mora/RCL
(modelo_p23.escada_p23) e erra quando o plano do ente fica ACIMA da escada.
Ex. medido em 13/10/2026: RJ paga 1,5% (plano do ente) e a escada dava 1,0%; PR paga
2,0% e a escada dava 1,0%.

Chave = pseudo-IBGE de 2 digitos do Estado (o mesmo de db_mapa.UF_PSEUDO_IBGE).
So entra Estado cujo percentual saiu de DOCUMENTO DO TRIBUNAL com o exercicio de 2026.
Ficam de fora, de proposito (sem percentual 2026 em fonte do tribunal): SC, SP, GO, CE,
PI, RN, PB e RR (RR so tem noticia de imprensa: 2,64%). MG vem do enquadramento do TJMG
(alfred_core.enquadramento_mg), que traz tambem a mora oficial.

SE (28), RO (11) e DF (53) estao aqui mas o banco ainda nao tem pseudo-municipio para
eles: a linha so passa a valer quando o Estado ganhar RCL/ente no db_build.

Fonte e data de cada linha: nao trocar o percentual sem trocar o documento.
"""

_TJ = "Tribunal de Justiça"

TABELA = {
    "29": {"uf": "BA", "pct": 1.0, "fonte": f"{_TJ} da Bahia (NACP)",
           "documento": "Decisão do NACP no PA 8036311-04.2021.8.05.0000 — plano 2026 do Estado (R$ 673,3 mi/ano)",
           "data": "29/01/2026"},
    "33": {"uf": "RJ", "pct": 1.5, "fonte": f"{_TJ} do Rio de Janeiro",
           "documento": "Plano de pagamento 2026 do Estado (portal 'Entes devedores — regime especial', API planoPagamento)",
           "data": "11/10/2026"},
    "43": {"uf": "RS", "pct": 1.5, "fonte": f"{_TJ} do Rio Grande do Sul",
           "documento": "Planilha do art. 100 §23 / EC 136 — 2026 (Estado do RS, Especial)",
           "data": "2026"},
    "21": {"uf": "MA", "pct": 1.0, "fonte": f"{_TJ} do Maranhão",
           "documento": "Planos de pagamento 2026 — entes sob Regime Especial (art. 101 ADCT, EC 136/2025)",
           "data": "27/02/2026"},
    "41": {"uf": "PR", "pct": 2.0, "fonte": f"{_TJ} do Paraná",
           "documento": "Relatório compacto dos Planos de Pagamento do Regime Especial 2026",
           "data": "2026"},
    "28": {"uf": "SE", "pct": 1.0, "fonte": f"{_TJ} de Sergipe",
           "documento": "Plano de Pagamento 2026 / Ato de Rateio 01/2026 (Regime Especial)",
           "data": "04/05/2026"},
    "16": {"uf": "AP", "pct": 1.0, "fonte": f"{_TJ} do Amapá",
           "documento": "Plano de pagamento do exercício 2026 (EC 136/2025): aporte anual = 1% da RCL do Estado",
           "data": "05/12/2025"},
    "53": {"uf": "DF", "pct": 1.0, "fonte": f"{_TJ} do DF e Territórios (COORPRE)",
           "documento": "Despacho do Plano 2026 homologado (dívida/RCL 11,17% → 1%)",
           "data": "06/02/2026"},
    "11": {"uf": "RO", "pct": 1.0, "fonte": f"{_TJ} de Rondônia (COGESP)",
           "documento": "Planilha 123/2025 — Plano de Pagamentos dos Entes no Regime Especial 2026",
           "data": "11/12/2025"},
    "51": {"uf": "MT", "pct": 1.0, "fonte": f"{_TJ} de Mato Grosso (Presidência)",
           "documento": "Decisão no precatório 0003875-20.2008.8.11.0000: plano 2026 homologado de ofício, piso de 1% da RCL",
           "data": "10/12/2025"},
    "26": {"uf": "PE", "pct": 1.0, "fonte": f"{_TJ} de Pernambuco",
           "documento": "Ato de Rateio 2026 / Plano de pagamento anual 2026 homologado",
           "data": "2026"},
    "17": {"uf": "TO", "pct": 1.0, "fonte": f"{_TJ} do Tocantins",
           "documento": "Plano do Regime Especial 2026 (Estado a 1% da RCL)",
           "data": "2026"},
}


def pct_estado(ibge):
    """{'pct','fonte','documento','data','uf'} do Estado, ou None se nao ha documento."""
    return TABELA.get(str(ibge or "").strip())
