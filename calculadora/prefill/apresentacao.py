"""Extrator determinístico da data de apresentação do precatório ao tribunal.

No eproc (TRF / Justiça 4.0), uma página de separação de evento carimba a
movimentação **"REQUISIÇÃO DE PAGAMENTO DE PRECATÓRIO ENVIADA AO TRIBUNAL"** com
a data/hora do envio. Essa é a data de apresentação REAL do precatório — o fato
jurídico que o art. 100 §5º CF + Súmula Vinculante 17 usam para marcar o início
do período de graça (a partir daí não correm juros de mora). É ground truth mais
preciso que o proxy do próximo 02/04 (`cenarios._apresentacao_cutoff`).

Parser determinístico (cabeçalho/separador do PJe é gerado pelo sistema, não
fabricável → regex supera classificador semântico — ver memória do projeto).
Zero LLM. A regex exige "PRECAT(Ó)RIO" antes de "ENVIADA AO TRIBUNAL" para NÃO
casar com RPV (que não recebe graça). Layout observado (caixa alta, sem acento):

    Sequência Evento:
    REQUISICAO DE PAGAMENTO DE PRECATORIO ENVIADA AO TRIBUNAL
    11/03/2026 06:11:22
"""
from __future__ import annotations

import re
from datetime import date


# "PRECAT[Ó/O]RIO ENVIAD[A/O] AO TRIBUNAL" seguido IMEDIATAMENTE (só whitespace /
# quebra de linha do separador) da data DD/MM/AAAA E de um timestamp HH:MM:SS.
# O timestamp é o discriminador: o separador de evento do eproc sempre carimba
# data+hora logo abaixo do título, então exigi-lo evita dois falsos positivos —
# (a) a frase citada no corpo de outra peça ("...ENVIADA AO TRIBUNAL em janeiro,
# conforme fls. 11/03/2026"), e (b) um campo "Status: CANCELADO" injetado entre o
# título e a data. IGNORECASE + classe de acento cobrem as variações do PyMuPDF.
_RE_ENVIO_TRIBUNAL = re.compile(
    r"PRECAT[ÓO]RIO\s+ENVIAD[AO]\s+AO\s+TRIBUNAL\s*"
    r"(\d{2})/(\d{2})/(\d{4})\s+\d{2}:\d{2}:\d{2}",
    re.IGNORECASE,
)


# Estaduais PJe (TJES e similares) NÃO têm o separador "ENVIADA AO TRIBUNAL" do
# eproc. A apresentação é certificada por uma CERTIDÃO de encaminhamento — ex.:
# "Certifico que nesta data foi encaminhado à Assessoria de Precatório[s] do
# Tribunal de Justiça do ES o Ofício Requisitório...". A data operativa é a da
# ASSINATURA ELETRÔNICA do servidor que certificou (carimbo PJe com o MESMO
# timestamp HH:MM:SS discriminador do eproc). Exige-se a co-ocorrência, NA MESMA
# página, do marcador de encaminhamento E de uma data-com-timestamp — assim uma
# menção avulsa à "Assessoria de Precatórios" no corpo de outra peça (boilerplate
# do ofício/formulário TJES) não vira falso positivo. Caso HELAWANDRO (TJES).
_RE_ENCAMINHAMENTO_ASSESSORIA = re.compile(
    r"encaminhad[oa]\s+(?:[àáa]s?\s+)?assessoria\s+de\s+precat[óo]rio",
    re.IGNORECASE,
)
_RE_DATA_TIMESTAMP = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+\d{2}:\d{2}:\d{2}")


def extrair_data_envio_tribunal(paginas: list[str]) -> date | None:
    """Varre as páginas de um processo procurando a data de apresentação do
    PRECATÓRIO ao tribunal (art. 100 §5º + SV 17 — início do período de graça).

    Reconhece dois layouts:
    - **eproc** (TRF/Justiça 4.0): separador "...PRECATÓRIO ENVIADA AO TRIBUNAL"
      + DD/MM/AAAA HH:MM:SS.
    - **estadual PJe (TJES)**: certidão "encaminhado à Assessoria de Precatório[s]"
      → data da assinatura eletrônica (com timestamp) na mesma página.

    Quando há mais de um envio (cancelamento + reenvio, ou múltiplas certidões),
    retorna a data MAIS RECENTE — a apresentação operativa. Retorna ``None``
    quando nenhum marcador existe (processo pré-requisitório ou layout não
    coberto).
    """
    datas: list[date] = []

    def _coletar(dd: str, mm: str, yyyy: str) -> None:
        try:
            datas.append(date(int(yyyy), int(mm), int(dd)))
        except ValueError:
            # Data malformada (ex.: 32/13/2026) — ignora e segue.
            pass

    for texto in paginas:
        if not texto:
            continue
        upper = texto.upper()
        # eproc: separador "PRECATÓRIO ENVIADA AO TRIBUNAL" + timestamp.
        if "TRIBUNAL" in upper:
            for m in _RE_ENVIO_TRIBUNAL.finditer(texto):
                _coletar(m.group(1), m.group(2), m.group(3))
        # estadual PJe (TJES): certidão de encaminhamento à Assessoria de
        # Precatório[s] → data da assinatura eletrônica (timestamp) na página.
        if "ASSESSORIA DE PRECAT" in upper and _RE_ENCAMINHAMENTO_ASSESSORIA.search(texto):
            for m in _RE_DATA_TIMESTAMP.finditer(texto):
                _coletar(m.group(1), m.group(2), m.group(3))
    return max(datas) if datas else None
