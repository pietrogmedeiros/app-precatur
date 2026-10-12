"""Etapa 12 — cenários paralelos para a oferta comercial.

A regra inviolável #3 do README pede: "toda análise produz cálculo com
índice homologado E com índice legal/sentencial; oferta comercial usa o
pior cenário".

v1 implementa cenários **declarativos** (sem recalcular o principal):

- **Homologado**: o que a conta da etapa 8 efetivamente declarou. É o
  que a Fazenda vai pagar segundo a memória do contador. PSS/IR
  aplicados conforme etapas 9/10. Sucumbenciais descontados conforme
  pct da etapa 8.
- **Sentencial**: o que daria se aplicado o regime da etapa 7.
  - Se reconciliação = `conforme`: cenário sentencial = cenário
    homologado (mesmo número, marcado como "convergente").
  - Se reconciliação = `divergente`: cenário sentencial fica em
    "valor sob revisão" — não dá pra estimar sem séries de índices
    versionadas (v2). O dossiê mostra a divergência textualmente.
  - Se reconciliação ∈ {decisao_silente, etapa7_nao_rodada, nao_comparado}:
    cenário sentencial fica "indisponível".

O **pior cenário** (menor valor líquido) define a base da oferta. v1
sempre usa o homologado como pior (já que sentencial = homologado
quando conforme, indisponível caso contrário) — exceto se o advogado
sinalizar manualmente que a divergência inflar o sentencial (fluxo
fora do escopo da v1).

Cálculo do valor líquido em cada cenário:
    valor_liquido = valor_total - valor_pss - valor_ir - valor_honorarios_sucumbenciais
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal, NotRequired, TypedDict

from precaturia.pipeline import calculo_ir, calculo_pss, credor_advogado
from precaturia.pipeline.indices import IndiceNaoSuportado, aplicar_regime, cobertura
from precaturia.pipeline.indices.aplicar import fator_periodo
from precaturia.pipeline.indices.series import load_serie


CenarioNome = Literal["homologado", "sentencial"]
SentencialStatus = Literal["convergente", "recalculado", "sob_revisao", "indisponivel"]
AtualizacaoStatus = Literal[
    "ok",
    "ok_ajustada_cobertura",
    "sem_data_origem",
    "data_alvo_igual_origem",
    "data_alvo_anterior_origem",
    "cobertura_insuficiente",
    "sem_valor",
]


class OficioGroundTruthDict(TypedDict):
    """Bloco de ground truth de um ofício requisitório (etapa 5 v4+).

    Produzido por `api.cases._oficios_ground_truth` a partir do
    `LlmCall.response_json` da última run pass de cada `Document` tipo='oficio'
    do caso, com `FieldReview` overrides aplicados. Consumido por
    `_construir_cenarios_oficio` para projetar cada ofício individualmente.

    `valor_credor` é o LÍQUIDO cedível declarado pelo ofício (ground truth da
    projeção). Os 3 valores monetários auxiliares (oficial/sucumb/contr) são
    informativos. `data_oficio` é a data oficial do ato (cadastro/expedição).
    `data_base` é a data ATÉ a qual o `valor_credor` já está corrigido — é a
    origem correta da projeção (o ofício atualiza o valor até a data base e
    a expedição vem meses depois). Fallback para `data_oficio` quando ausente.
    """

    document_id: str
    document_nome: str | None
    llm_call_id: str
    data_oficio: date | None
    data_base: date | None
    # "precatorio" | "rpv" | None — detectado por regex determinístico no
    # texto do ofício (api.cases._detectar_modalidade_oficio). Gateia o
    # período de graça (art. 100 §5º CF + SV 17): só precatório recebe graça;
    # RPV é pago em 60 dias, sem janela de graça.
    modalidade: str | None
    valor_oficial_oficio: Decimal | None
    valor_credor: Decimal | None
    valor_sucumbenciais: Decimal | None
    valor_contratuais: Decimal | None
    # Decomposição "VALORES HISTÓRICOS (HOMOLOGADO)" do requisitório (etapa 5
    # v11+): principal corrigido SEM juros + juros moratórios, no BRUTO. Usados
    # por _base_tributavel_oficio para a base de PSS/IR sem juros. None quando o
    # ofício não decompõe (cai na aproximação valor_credor com juros).
    valor_principal: Decimal | None
    valor_juros: Decimal | None
    # Valor bruto do precatório (etapa 5). FALLBACK do crédito: quando o ofício
    # é uma DECISÃO homologatória ("valor da execução R$ X") sem campos de
    # requisitório formal (valor_oficial/valor_credor null), `valor_credor` é
    # preenchido a partir daqui — senão o valor extraído se perde e a oferta
    # fica vazia (caso CASO/TJMG). `valor_de_bruto` sinaliza esse fallback.
    valor_bruto: Decimal | None
    valor_de_bruto: bool
    # GUARD coletiva: True quando o fallback valor_bruto FOI SUPRIMIDO porque o
    # texto do ofício é uma execução coletiva (lista de N substituídos + total
    # geral). Evita ancorar a oferta no total geral (caso CASO) quando a lista
    # vem como ofício, não como conta tipo='calculo' (que o guard já cobre).
    coletiva_no_oficio: bool
    # Regra 8 (ii) do CLAUDE.md — classificação manual do beneficiário do
    # ofício: True = crédito do exequente (entra no agregado da oferta);
    # False = crédito de terceiro (advogado sucumbenciais, listado separado);
    # None = não classificado (não agrega).
    e_credor_exequente: bool | None
    # Natureza do crédito do ofício (etapa 5 v7+): "principal" | "multa" |
    # "honorarios" | "outro" | None. Em multi-ofício, a análise completa roda
    # sobre o ofício "principal"; os demais são apenas listados.
    natureza_requisicao: str | None
    # Nome literal do beneficiário/credor (etapa 5 v8+) e sinal de cessão de
    # crédito (art. 100 §13 CF). Em desapropriação/precatório cedido, o credor
    # é o CESSIONÁRIO nomeado no requisitório, não o exequente original — sem
    # esses campos a cessão fica invisível (caso CASO). Informativos: não
    # entram no cálculo, surfaceiam o destinatário correto na lista de ofícios.
    nome_credor: str | None
    cessao: str | None
    # Número da requisição (precatório/RPV, ex.: "297-2025") — IDENTIDADE do
    # requisitório, usada para deduplicar o MESMO precatório re-juntado em 2
    # Documents (Documento id diferente). Ver _oficios_ground_truth (dedup C).
    numero_requisicao: str | None
    # Data REAL de envio do precatório ao tribunal (separador eproc "PRECATÓRIO
    # ENVIADA AO TRIBUNAL"), extraída no upload. Quando presente, ancora o
    # período de graça com precisão (art. 100 §5º), com precedência sobre o
    # proxy do próximo 02/04 — mas abaixo do override manual do revisor. None em
    # não-eproc/pré-requisitório. Ver `apresentacao_extrator`.
    data_envio_tribunal: date | None
    # F3 (regra 1): True quando a citação do valor-ÂNCORA da oferta (o campo em
    # `ancora_campo`, precedência valor_oficial_oficio > valor_credor > valor_bruto)
    # foi ANULADA pelo citation_validator (status != ok/pagina_corrigida) — o valor
    # entra na oferta sem lastro verificável. SINALIZA (ressalva), não bloqueia.
    # False também quando a citação nunca foi emitida (campo ausente do diagnóstico)
    # ou houve override humano editado. NotRequired: snapshots/fixtures legados sem
    # a chave são lidos via .get → tratados como False.
    ancora_sem_citacao: NotRequired[bool]
    ancora_campo: NotRequired[str | None]
    # F1/F2 (caso CASO): document_ids dos ofícios ANTERIORES que este
    # bloco SUPERSEDE — a re-expedição do MESMO crédito (Req 08/2022 -> Precatório
    # 2025, mesmo valor_bruto+data_base+credor, número/data diferentes) foi
    # colapsada em `_oficios_ground_truth` para não dobrar a oferta. Lista vazia/
    # ausente no caso comum. Observabilidade: a oferta/achados surfaceiam que
    # houve re-expedição absorvida (não some silenciosamente).
    supersede_ids: NotRequired[list[str]]
    # F3: True quando o texto do ofício é uma Certidão de Conferência /
    # demonstrativo / prévia (sinal bruto do regex, 1 de 2 gates). Quando a 4ª
    # passada de dedup CONFIRMA (face ≈ soma de ≥2 parcelas do mesmo crédito), o
    # bloco-resumo é REMOVIDO da lista (não é crédito próprio; somá-lo dobraria o
    # precatório) e seu document_id vai p/ `supersede_ids` da maior parcela —
    # rastreável. NotRequired: ausente no caso comum (lido via .get → False).
    e_conferencia_texto: NotRequired[bool]


@dataclass(frozen=True)
class ComponenteAtualizacao:
    """Um trecho do regime composto de atualização.

    A EC 113/2021 e a EC 136/2025 dividem o pós-data_calculo da conta em
    até 2 períodos quando o intervalo cruza 2025-08-01 (vigência efetiva
    da EC 136). Cada trecho carrega seu regime, fator e marca se o cap
    SELIC da EC 136 foi acionado.
    """

    regime: str
    fator: Decimal
    inicio: date
    fim: date
    cap_acionado: bool = False
    # Fator aplicado à LINHA DE JUROS na fase. Igual a `fator` na SELIC/graça;
    # na EC 136 difere (a IPCA encadeia + os 2% a.a. entram na linha de juros).
    fator_juros: Decimal = Decimal("1")
    # Juros NOVOS que a fase SOMOU na linha de juros além da correção (poupança
    # do art. 22 na fase precatório; 2% a.a. na EC 136). Decomposição EXATA
    # (estilo gabarito): juros_fim = juros_ini × fator + juros_novos. Zero nas
    # fases SELIC/graça (lá a linha de juros só corrige/consolida).
    juros_novos: Decimal = Decimal("0")
    # Soma das taxas mensais desses juros novos (fração — 0.0761 = 7,61%).
    # Informativa p/ display: as taxas incidem MÊS A MÊS sobre o principal
    # corrigido, não de uma vez sobre a base de início da fase.
    taxa_juros_novos: Decimal = Decimal("0")

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "fator": str(self.fator),
            "inicio": self.inicio.isoformat(),
            "fim": self.fim.isoformat(),
            "cap_acionado": self.cap_acionado,
            "fator_juros": str(self.fator_juros),
            "juros_novos": str(self.juros_novos),
            "taxa_juros_novos": str(self.taxa_juros_novos),
        }


@dataclass(frozen=True)
class Atualizacao:
    """Atualização do valor líquido entre `data_origem` e `data_alvo`.

    A proposta de compra do precatório precisa estar em moeda da data em
    que é feita, não da data em que a conta foi confeccionada. O regime
    composto reflete a evolução constitucional:

    - **EC 113/2021** (vigente desde 09/12/2021): SELIC unificada (correção
      + juros num único índice).
    - **EC 136/2025** (efeitos materiais desde 01/08/2025): IPCA para
      correção monetária + juros simples 2% a.a., capped pela SELIC
      acumulada do mesmo período.

    Para intervalos que cruzam 01/08/2025, a v1 compõe os dois regimes em
    sequência. ADI 7873 discute a constitucionalidade da EC 136 — o
    payload sinaliza essa pendência quando o trecho EC 136 é aplicado.
    """

    regime: str  # rótulo legível do regime aplicado (ex.: "SELIC + EC 136 IPCA+2%")
    fator: Decimal  # fator combinado dos componentes
    data_origem: date | None
    data_alvo: date  # data efetivamente aplicada (após eventual ajuste)
    status: AtualizacaoStatus
    mensagem: str
    componentes: list[ComponenteAtualizacao] = field(default_factory=list)
    ressalva_adi: str | None = None  # preenchido quando há trecho EC 136
    data_alvo_solicitada: date | None = None  # != data_alvo quando houve ajuste

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "fator": str(self.fator),
            "data_origem": self.data_origem.isoformat() if self.data_origem else None,
            "data_alvo": self.data_alvo.isoformat(),
            "data_alvo_solicitada": (
                self.data_alvo_solicitada.isoformat()
                if self.data_alvo_solicitada
                else None
            ),
            "status": self.status,
            "mensagem": self.mensagem,
            "componentes": [c.to_dict() for c in self.componentes],
            "ressalva_adi": self.ressalva_adi,
        }


# ─────────────────────────── EC 136/2025 ───────────────────────────


EC_136_VIGENCIA = date(2025, 8, 1)
"""Início do regime IPCA+2% (EC 136) para entes ESTADUAIS/DF/MUNICIPAIS —
competência ago/2025 (Provimento CNJ 207/2025, arts. 2º-3º). É o default."""

EC_136_VIGENCIA_FEDERAL = date(2025, 9, 1)
"""Início do regime IPCA+2% para requisitórios FEDERAIS — competência set/2025
(Provimento CNJ 207/2025): a União mantém SELIC até ago/2025 e só migra em
set/2025. Ver docs/regimes_historicos.md §0 achado 1."""


def _ec136_vigencia(esfera: str | None) -> date:
    """Data de início do regime EC 136 conforme a esfera do ente devedor
    (Provimento CNJ 207/2025). `esfera='federal'` → set/2025; qualquer outro
    valor (estadual/municipal/None) → ago/2025."""
    return EC_136_VIGENCIA_FEDERAL if (esfera or "").lower() == "federal" else EC_136_VIGENCIA

JUROS_SIMPLES_POS_EC_136_ANUAL = Decimal("0.02")
"""Juros simples de 2% a.a. previstos pela EC 136 — aplicados sobre o
valor de origem do período (não compõem com a correção IPCA)."""

# A EC 136/2025 prevê correção pela IPCA cheia (BACEN 433), NÃO pela IPCA-E
# (IPCA-15, BACEN 10764) usada no pré-precatório e no período de graça pelo
# Manual de Cálculos da JF. Diferem ~0,05-0,1 pp/mês — só o trecho EC 136 usa
# "IPCA". O pré-precatório e a graça seguem em "IPCA-E" (ver `fator_ipca_e`).
_INDICE_CORRECAO_EC_136 = "IPCA"

_RESSALVA_ADI_7873 = (
    "EC 136/2025 sob discussão constitucional (ADI 7873). O regime "
    "IPCA + 2% a.a. (capped SELIC) pode ser revertido — confirmar antes "
    "de fechar a oferta."
)


def _meses_entre_exclusivo_inclusivo(de_exclusivo: date, ate_inclusivo: date) -> int:
    """Conta meses do período usando a convenção do Manual JF: mês inicial
    excluído, mês final incluído. Retorna 0 quando ate <= de no mesmo mês.
    """
    if (ate_inclusivo.year, ate_inclusivo.month) <= (de_exclusivo.year, de_exclusivo.month):
        return 0
    return (
        (ate_inclusivo.year - de_exclusivo.year) * 12
        + (ate_inclusivo.month - de_exclusivo.month)
    )


def _ultimo_dia_mes_anterior(d: date) -> date:
    """Último dia do mês anterior a `d` (para servir como `de_exclusivo`
    de um período que começa no mês de `d`)."""
    if d.month == 1:
        return date(d.year - 1, 12, 31)
    # Dia 28 funciona como "último dia" pra qualquer mês via convenção do
    # `_iterar_meses` (só importa o mês/ano).
    return date(d.year, d.month - 1, 28)


def _fator_ec_136(de_exclusivo: date, ate_inclusivo: date) -> tuple[Decimal, bool]:
    """Fator IPCA + 2% a.a. simples no período pós-EC 136, capped pela
    SELIC acumulada do mesmo intervalo.

    Retorna `(fator, cap_acionado)`.

    Composição (decisão de design v1 — interpretação "soma de fatores"):
        fator_combinado = fator_IPCA_acumulado + juros_simples_acumulado

    Cap (decisão de design v1 — comparação acumulada): se
    fator_combinado > fator_SELIC, aplica SELIC.
    """
    fator_ipca = fator_periodo(_INDICE_CORRECAO_EC_136, de_exclusivo, ate_inclusivo)
    n_meses = _meses_entre_exclusivo_inclusivo(de_exclusivo, ate_inclusivo)
    juros_simples = (
        JUROS_SIMPLES_POS_EC_136_ANUAL * Decimal(n_meses) / Decimal("12")
    )
    fator_combinado = fator_ipca + juros_simples
    fator_selic = fator_periodo("SELIC", de_exclusivo, ate_inclusivo)
    if fator_combinado > fator_selic:
        return fator_selic, True
    return fator_combinado, False


def _fator_composto(
    data_origem: date, data_alvo: date
) -> tuple[Decimal, list[ComponenteAtualizacao], bool]:
    """Compõe fator entre `data_origem` (excl) e `data_alvo` (incl),
    cruzando a EC 136 se necessário.

    Retorna `(fator_total, componentes, tem_trecho_ec_136)`.

    Casos:
    - Ambos antes da vigência → 1 componente SELIC (EC 113).
    - Ambos após a vigência → 1 componente EC 136 (IPCA+2% capped SELIC).
    - Intervalo cruza → 2 componentes (SELIC até jul/2025 + EC 136 de ago/2025).
    """
    componentes: list[ComponenteAtualizacao] = []
    tem_ec_136 = False

    # Caso 1: intervalo todo pré-EC 136
    if (data_alvo.year, data_alvo.month) < (EC_136_VIGENCIA.year, EC_136_VIGENCIA.month):
        fator_selic = fator_periodo("SELIC", data_origem, data_alvo)
        componentes.append(
            ComponenteAtualizacao(
                regime="SELIC (EC 113/2021)",
                fator=fator_selic,
                inicio=data_origem,
                fim=data_alvo,
            )
        )
        return fator_selic, componentes, tem_ec_136

    # Caso 2: intervalo todo pós-EC 136
    if (data_origem.year, data_origem.month) >= (EC_136_VIGENCIA.year, EC_136_VIGENCIA.month):
        fator_ec136, cap = _fator_ec_136(data_origem, data_alvo)
        tem_ec_136 = True
        componentes.append(
            ComponenteAtualizacao(
                regime="IPCA + 2% a.a. (EC 136/2025, capped SELIC)",
                fator=fator_ec136,
                inicio=data_origem,
                fim=data_alvo,
                cap_acionado=cap,
            )
        )
        return fator_ec136, componentes, tem_ec_136

    # Caso 3: cruza a vigência. Primeiro período SELIC até jul/2025
    # inclusivo (último mês com regime EC 113). Segundo período EC 136
    # a partir de ago/2025 até data_alvo.
    fim_periodo_1 = _ultimo_dia_mes_anterior(EC_136_VIGENCIA)  # = 2025-07-XX
    fator_selic = fator_periodo("SELIC", data_origem, fim_periodo_1)
    componentes.append(
        ComponenteAtualizacao(
            regime="SELIC (EC 113/2021)",
            fator=fator_selic,
            inicio=data_origem,
            fim=fim_periodo_1,
        )
    )
    fator_ec136, cap = _fator_ec_136(fim_periodo_1, data_alvo)
    tem_ec_136 = True
    componentes.append(
        ComponenteAtualizacao(
            regime="IPCA + 2% a.a. (EC 136/2025, capped SELIC)",
            fator=fator_ec136,
            inicio=EC_136_VIGENCIA,
            fim=data_alvo,
            cap_acionado=cap,
        )
    )
    fator_total = fator_selic * fator_ec136
    return fator_total, componentes, tem_ec_136


@dataclass(frozen=True)
class Cenario:
    nome: CenarioNome
    disponivel: bool
    valor_total: Decimal | None
    valor_pss: Decimal | None
    valor_ir: Decimal | None
    honorarios_sucumbenciais_pct: Decimal | None
    valor_honorarios_sucumbenciais: Decimal | None
    valor_liquido: Decimal | None  # em moeda da data_calculo da conta
    valor_liquido_atualizado: Decimal | None = None  # em moeda da data_alvo
    atualizacao: Atualizacao | None = None
    observacoes: list[str] = field(default_factory=list)
    status_sentencial: SentencialStatus | None = None  # só preenchido pro sentencial
    # Honorários contratuais (destacados no ofício, não na conta). Quando
    # presentes, são abatidos do valor_total — só o saldo do credor (tipicamente
    # 70%) entra na atualização e no cálculo de PSS/IR. Comportamento
    # alinhado com escritório especializado (gabarito USS, caso CASO).
    honorarios_contratuais_pct: Decimal | None = None
    valor_honorarios_contratuais: Decimal | None = None
    # Componentes segregados em moeda da data_alvo (modelo Projef Web —
    # principal/juros congelados, SELIC linear como overlay). Preenchidos
    # quando `atualizacao` está disponível.
    principal_corrigido_atualizado: Decimal | None = None
    juros_moratorios_atualizado: Decimal | None = None
    selic_acumulada_atualizada: Decimal | None = None
    valor_total_atualizado: Decimal | None = None
    # Memória de cálculo dos descontos ESTIMADOS (estilo gabarito): preenchidos
    # apenas quando o recalc de metodologia rodou (PSS por alíquota / IR-RRA
    # recalculado sobre a base atualizada). Valores declarados/override não têm
    # memória (o número é do advogado). `ir_detalhe` = ResultadoIR.to_dict()
    # (base → PSS deduzido → base mensal → faixa → valor); `pss_detalhe` traz
    # base decomposta (principal atualizado + SELIC, líquido do destaque) e
    # alíquota. Consumo: memorial da calculadora (PDF) e UI.
    pss_detalhe: dict | None = None
    ir_detalhe: dict | None = None
    # Superpreferência (idoso 80+/doença grave/PcD, RCL/EC 114): pagamento
    # BRUTO antecipado abatido na data em que ocorreu (ver construir_cenarios).
    # `valor_corrigido_pre_superpreferencia` é o saldo corrigido até essa data,
    # ANTES do abate — exposto só para exibição (tela/memorial), não usado em
    # nenhum outro cálculo.
    valor_superpreferencia: Decimal | None = None
    data_pagamento_superpreferencia: date | None = None
    valor_corrigido_pre_superpreferencia: Decimal | None = None
    # Memória de cálculo do abatimento (estilo pss_detalhe/ir_detalhe): quanto
    # cada componente segregado tinha antes/depois do pagamento. Consumida
    # pelo memorial para render a fase do abatimento na trilha.
    superpreferencia_detalhe: dict | None = None
    # Fonte do cenário — sinaliza pra UI/dossiê se o pipeline partiu do
    # ofício (etapa 5 v4) ou do cálculo homologado (etapa 8). Quando
    # "oficio", valor_pss/valor_ir/sucumb/contr são decomposição do
    # ofício (não recalculadas), e valor_liquido = valor_credor.
    # Quando "agregado_exequente", o cenário é a soma dos blocos com
    # `e_credor_exequente=True` (regra 8 ii do CLAUDE.md) — campos de
    # decomposição de atualização (`atualizacao`, principal/juros/selic)
    # ficam null porque cada bloco tem seu próprio.
    # "recebivel_unico_exequente": N requisições do MESMO crédito (mesmo credor +
    # natureza + data_base) agregadas por DEFAULT — é UM crédito fracionado, não N
    # créditos distintos (caso CASO). PSS/IR contados UMA vez (regra 8 ii sem
    # exigir ?agregar, porque não há "soma de créditos distintos").
    fonte: Literal[
        "calculo", "oficio", "agregado_exequente", "recebivel_unico_exequente"
    ] = "calculo"

    def to_dict(self) -> dict:
        return {
            "nome": self.nome,
            "disponivel": self.disponivel,
            "valor_total": _decimal_str(self.valor_total),
            "valor_pss": _decimal_str(self.valor_pss),
            "valor_ir": _decimal_str(self.valor_ir),
            "honorarios_sucumbenciais_pct": _decimal_str(self.honorarios_sucumbenciais_pct),
            "valor_honorarios_sucumbenciais": _decimal_str(self.valor_honorarios_sucumbenciais),
            "honorarios_contratuais_pct": _decimal_str(self.honorarios_contratuais_pct),
            "valor_honorarios_contratuais": _decimal_str(self.valor_honorarios_contratuais),
            "valor_liquido": _decimal_str(self.valor_liquido),
            "valor_liquido_atualizado": _decimal_str(self.valor_liquido_atualizado),
            "principal_corrigido_atualizado": _decimal_str(self.principal_corrigido_atualizado),
            "juros_moratorios_atualizado": _decimal_str(self.juros_moratorios_atualizado),
            "selic_acumulada_atualizada": _decimal_str(self.selic_acumulada_atualizada),
            "valor_total_atualizado": _decimal_str(self.valor_total_atualizado),
            "atualizacao": self.atualizacao.to_dict() if self.atualizacao else None,
            "observacoes": self.observacoes,
            "status_sentencial": self.status_sentencial,
            "fonte": self.fonte,
            "pss_detalhe": self.pss_detalhe,
            "ir_detalhe": self.ir_detalhe,
            "valor_superpreferencia": _decimal_str(self.valor_superpreferencia),
            "data_pagamento_superpreferencia": (
                self.data_pagamento_superpreferencia.isoformat()
                if self.data_pagamento_superpreferencia
                else None
            ),
            "valor_corrigido_pre_superpreferencia": _decimal_str(
                self.valor_corrigido_pre_superpreferencia
            ),
            "superpreferencia_detalhe": self.superpreferencia_detalhe,
        }


@dataclass(frozen=True)
class BlocoOficio:
    """Um ofício requisitório projetado individualmente até `data_alvo`.

    Multi-ofício (regra inviolável #6/#8 do CLAUDE.md): cada ofício é um
    pagamento independente (beneficiário/modalidade/base distintos). Não
    somam. `valor_credor` é o LÍQUIDO cedível declarado pelo ofício e funciona
    como ground truth da projeção — a atualização SELIC/IPCA-E + EC 136 +
    período de graça é aplicada sobre ele até `data_alvo`.

    PSS/IR vêm do override do caso (etapa 9/10) e são aplicados APENAS aos
    blocos com `e_credor_exequente=True` — a regra de tributação é própria
    do credor, e ofícios de terceiros (advogado sucumbenciais) têm
    tratamento distinto fora do escopo da agregação do exequente.
    Sucumb/contr saem direto do ofício como decomposição informativa do
    bruto declarado.
    """

    document_id: str
    document_nome: str | None
    llm_call_id: str
    data_oficio: date
    # Brutos e decomposição declarados no ofício.
    valor_oficial_oficio: Decimal | None
    valor_credor: Decimal
    valor_sucumbenciais: Decimal | None
    valor_contratuais: Decimal | None
    # Projeção até data_alvo via _atualizar_segregado.
    valor_credor_atualizado: Decimal
    principal_corrigido_atualizado: Decimal
    juros_moratorios_atualizado: Decimal
    selic_acumulada_atualizada: Decimal
    valor_total_atualizado: Decimal
    atualizacao: Atualizacao
    # Regra 8 (ii) — classificação manual do beneficiário (vide
    # OficioGroundTruthDict). Quando True, PSS/IR do override do caso
    # entram em valor_pss/valor_ir e o líquido é agregado em
    # ResultadoCenarios.valor_oferta_base.
    e_credor_exequente: bool | None = None
    # "principal" | "multa" | "honorarios" | "outro" | None — em multi-ofício,
    # a análise/oferta roda sobre o de natureza "principal"; os demais listam.
    natureza_requisicao: str | None = None
    # Beneficiário literal + sinal de cessão (etapa 5 v8+). Informativos: quem
    # RECEBE este ofício (cessionário em crédito cedido, art. 100 §13 CF).
    nome_credor: str | None = None
    cessao: str | None = None
    # Data-base do ofício (data até a qual o valor_credor já está corrigido).
    # Surfaca a data-base no resumo quando não há conta (etapa 8) — multi-ofício
    # federal. Ver resumo.py (fallback de data_base).
    data_base: date | None = None
    valor_pss: Decimal | None = None
    valor_ir: Decimal | None = None
    valor_liquido: Decimal | None = None
    valor_liquido_atualizado: Decimal | None = None
    observacoes: list[str] = field(default_factory=list)
    # F3 (regra 1): True quando o valor-âncora da oferta deste ofício teve a
    # citação ANULADA (ver OficioGroundTruthDict.ancora_sem_citacao). Surfaça a
    # ressalva "confirmar no PDF"; NÃO altera nenhum valor. No FIM da dataclass
    # de propósito (não quebra construtores posicionais).
    ancora_sem_citacao: bool = False

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "document_nome": self.document_nome,
            "llm_call_id": self.llm_call_id,
            "data_oficio": self.data_oficio.isoformat(),
            "valor_oficial_oficio": _decimal_str(self.valor_oficial_oficio),
            "valor_credor": _decimal_str(self.valor_credor),
            "valor_sucumbenciais": _decimal_str(self.valor_sucumbenciais),
            "valor_contratuais": _decimal_str(self.valor_contratuais),
            "valor_credor_atualizado": _decimal_str(self.valor_credor_atualizado),
            "principal_corrigido_atualizado": _decimal_str(
                self.principal_corrigido_atualizado
            ),
            "juros_moratorios_atualizado": _decimal_str(
                self.juros_moratorios_atualizado
            ),
            "selic_acumulada_atualizada": _decimal_str(
                self.selic_acumulada_atualizada
            ),
            "valor_total_atualizado": _decimal_str(self.valor_total_atualizado),
            "atualizacao": self.atualizacao.to_dict(),
            "e_credor_exequente": self.e_credor_exequente,
            "natureza_requisicao": self.natureza_requisicao,
            "nome_credor": self.nome_credor,
            "cessao": self.cessao,
            "data_base": self.data_base.isoformat() if self.data_base else None,
            "valor_pss": _decimal_str(self.valor_pss),
            "valor_ir": _decimal_str(self.valor_ir),
            "valor_liquido": _decimal_str(self.valor_liquido),
            "valor_liquido_atualizado": _decimal_str(self.valor_liquido_atualizado),
            "observacoes": list(self.observacoes),
            "ancora_sem_citacao": self.ancora_sem_citacao,
        }


@dataclass
class ResultadoCenarios:
    cenario_homologado: Cenario
    cenario_sentencial: Cenario
    pior_cenario: CenarioNome | None  # None se nenhum disponível
    valor_oferta_base: Decimal | None  # = pior_cenario.valor_liquido
    # Multi-ofício (regra 8 do CLAUDE.md): lista de ofícios independentes
    # projetados individualmente. Vazia no caminho legado (etapa 8). Quando
    # `multi_oficio=True`, `valor_oferta_base` fica None e os dois cenários
    # ficam `disponivel=False` — frontend/dossiê devem renderizar a lista.
    blocos_oficio: list[BlocoOficio] = field(default_factory=list)
    multi_oficio: bool = False

    def to_dict(self) -> dict:
        return {
            "cenario_homologado": self.cenario_homologado.to_dict(),
            "cenario_sentencial": self.cenario_sentencial.to_dict(),
            "pior_cenario": self.pior_cenario,
            "valor_oferta_base": _decimal_str(self.valor_oferta_base),
            "blocos_oficio": [b.to_dict() for b in self.blocos_oficio],
            "multi_oficio": self.multi_oficio,
        }


def _decimal_str(v: Decimal | None) -> str | None:
    if v is None:
        return None
    return str(v)


def _to_decimal(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _q(d: Decimal | None) -> Decimal | None:
    if d is None:
        return None
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _extrair_campo(payload: dict | None, campo: str) -> Decimal | None:
    """Extrai `{campo}.valor` de um response_json no formato CampoExtraido."""
    if not isinstance(payload, dict):
        return None
    obj = payload.get(campo)
    if isinstance(obj, dict):
        return _to_decimal(obj.get("valor"))
    return None


def _parse_data(valor) -> date | None:
    if not isinstance(valor, str):
        return None
    try:
        if len(valor) == 7:
            return date.fromisoformat(valor + "-01")
        return date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


def _ultimo_dia_mes(ano: int, mes: int) -> date:
    import calendar

    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def _indices_necessarios(
    data_origem: date, data_alvo: date, data_apresentacao: date | None = None
) -> list[str]:
    """Índices que o cálculo do fator vai tocar entre as datas — usado para
    recuar `data_alvo` à última data coberta por TODOS eles.

    - SELIC: sempre (regime pré-EC 136 e cap pós-EC 136).
    - "IPCA" (BACEN 433): trecho EC 136, quando o intervalo alcança a vigência.
    - "IPCA-E" (BACEN 10764): SÓ quando um mês de graça realmente cai na janela
      coberta (`_graca_na_janela_coberta`). Sem `data_apresentacao` — monolítico
      ou sem graça — a IPCA-E não entra: senão capava a oferta num índice que o
      cálculo não usa, e a IPCA-E publica ~1 mês depois da 433 (recuo a menos).
    """
    indices = ["SELIC"]
    if (data_alvo.year, data_alvo.month) >= (EC_136_VIGENCIA.year, EC_136_VIGENCIA.month):
        indices.append(_INDICE_CORRECAO_EC_136)
    if data_apresentacao is not None and _graca_na_janela_coberta(
        data_alvo, data_apresentacao, indices
    ):
        indices.append("IPCA-E")
    return indices


def _ultima_data_coberta(indices: list[str]) -> date | None:
    """Último dia do último mês coberto por TODOS os índices passados.

    Retorna `None` se algum índice não tem série disponível.
    """
    ultimos: list[tuple[int, int]] = []
    for nome in indices:
        try:
            _, ultimo = cobertura(nome)
        except (KeyError, FileNotFoundError):
            return None
        ano_s, mes_s = ultimo.split("-")
        ultimos.append((int(ano_s), int(mes_s)))
    if not ultimos:
        return None
    # `min` por (ano, mês) — o intervalo termina onde TODOS ainda têm dado.
    ano, mes = min(ultimos)
    return _ultimo_dia_mes(ano, mes)


def _ajustar_data_alvo(
    data_origem: date, data_alvo: date, data_apresentacao: date | None = None
) -> tuple[date, bool]:
    """Ajusta `data_alvo` para a última data coberta pelas séries necessárias.

    Retorna `(data_alvo_efetiva, ajustada)`. `ajustada=True` quando a data
    solicitada excede a cobertura e foi recuada. Se a cobertura termina
    antes da `data_origem`, retorna a `data_alvo` original (deixa o
    chamador detectar `cobertura_insuficiente` pela exceção downstream).

    `data_apresentacao` (segregado) habilita o gate de graça: a IPCA-E só
    limita o recuo quando um mês de graça cai na janela coberta.
    """
    indices = _indices_necessarios(data_origem, data_alvo, data_apresentacao)
    ultima = _ultima_data_coberta(indices)
    if ultima is None:
        return data_alvo, False
    if (data_alvo.year, data_alvo.month) <= (ultima.year, ultima.month):
        return data_alvo, False
    # Se a cobertura termina antes da própria origem, nada a ajustar — a
    # chamada vai falhar adiante e cair em `cobertura_insuficiente`.
    if (ultima.year, ultima.month) <= (data_origem.year, data_origem.month):
        return data_alvo, False
    return ultima, True


def _atualizar(
    valor: Decimal | None, data_origem: date | None, data_alvo: date
) -> tuple[Decimal | None, Atualizacao]:
    """Atualiza `valor` entre `data_origem` (exclusivo) e `data_alvo` (inclusivo).

    Aplica o regime constitucional composto:
    - Trecho até 2025-07-31: SELIC unificada (EC 113/2021).
    - Trecho desde 2025-08-01: IPCA + 2% a.a. simples, capped pela SELIC
      acumulada (EC 136/2025, sob discussão na ADI 7873).

    Quando o intervalo cruza a vigência da EC 136, devolve `Atualizacao`
    com 2 `componentes` e ressalva ADI. Bordas tratadas com `status`
    específico — UI sinaliza confiança ao advogado.
    """
    regime_inicial = "SELIC (EC 113/2021)"

    if valor is None:
        return None, Atualizacao(
            regime=regime_inicial,
            fator=Decimal("1"),
            data_origem=data_origem,
            data_alvo=data_alvo,
            status="sem_valor",
            mensagem="valor_liquido indisponível — nada a atualizar.",
        )
    if data_origem is None:
        return None, Atualizacao(
            regime=regime_inicial,
            fator=Decimal("1"),
            data_origem=None,
            data_alvo=data_alvo,
            status="sem_data_origem",
            mensagem=(
                "data_calculo da etapa 8 não disponível — sem origem para "
                "atualizar a oferta."
            ),
        )
    # Mesmo mês: a conta já cobriu até esse mês (convenção do Manual JF:
    # mês alvo incluído). Fator = 1, valor inalterado.
    if (data_alvo.year, data_alvo.month) <= (data_origem.year, data_origem.month):
        if (data_alvo.year, data_alvo.month) < (data_origem.year, data_origem.month):
            status: AtualizacaoStatus = "data_alvo_anterior_origem"
            mensagem = (
                f"data_alvo ({data_alvo.isoformat()}) anterior à data_calculo "
                f"({data_origem.isoformat()}) — proposta em moeda da conta."
            )
        else:
            status = "data_alvo_igual_origem"
            mensagem = (
                f"data_alvo no mesmo mês de data_calculo "
                f"({data_origem.isoformat()}) — proposta em moeda da conta."
            )
        return valor, Atualizacao(
            regime=regime_inicial,
            fator=Decimal("1"),
            data_origem=data_origem,
            data_alvo=data_alvo,
            status=status,
            mensagem=mensagem,
        )

    data_alvo_efetiva, ajustada = _ajustar_data_alvo(data_origem, data_alvo)

    try:
        fator, componentes, tem_ec_136 = _fator_composto(data_origem, data_alvo_efetiva)
    except IndiceNaoSuportado as e:
        return None, Atualizacao(
            regime=regime_inicial,
            fator=Decimal("1"),
            data_origem=data_origem,
            data_alvo=data_alvo,
            status="cobertura_insuficiente",
            mensagem=(
                f"Séries de índices não cobrem o intervalo solicitado: "
                f"{e.motivo}. Atualize as séries (scripts/baixar_indices.py) "
                "ou escolha data_alvo mais antiga."
            ),
        )

    atualizado = (valor * fator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    regime_legivel = " + ".join(c.regime for c in componentes) if componentes else regime_inicial
    cap_acionado = any(c.cap_acionado for c in componentes)
    msg_extra = " (cap SELIC acionado)" if cap_acionado else ""
    status_final: AtualizacaoStatus = "ok"
    msg_ajuste = ""
    if ajustada:
        status_final = "ok_ajustada_cobertura"
        msg_ajuste = (
            f" Data alvo solicitada {data_alvo.isoformat()} excede a cobertura "
            f"das séries — recuada para {data_alvo_efetiva.isoformat()} (último "
            "mês publicado)."
        )
    mensagem = (
        f"Atualização de {data_origem.isoformat()} (excl) a "
        f"{data_alvo_efetiva.isoformat()} (incl): fator total {fator}"
        f"{msg_extra}. Composição: {regime_legivel}.{msg_ajuste}"
    )
    ressalva = _RESSALVA_ADI_7873 if tem_ec_136 else None
    return atualizado, Atualizacao(
        regime=regime_legivel,
        fator=fator,
        data_origem=data_origem,
        data_alvo=data_alvo_efetiva,
        status=status_final,
        mensagem=mensagem,
        componentes=componentes,
        ressalva_adi=ressalva,
        data_alvo_solicitada=data_alvo if ajustada else None,
    )


# ──────────── Decomposição SELIC histórica (inferência) ────────────


_EC113_VIGENCIA_SELIC = date(2021, 12, 1)

# ── FASE PRECATÓRIO — art. 21-A da Res. CNJ 303/2019 ────────────────────────
# Cadeia oficial (incisos X–XIII) para o trecho ANTERIOR à EC 113 (dez/2021),
# aplicada da data-base do precatório até o pagamento. Convenção MENSAL (por
# competência, como o resto do motor): os marcos dia-exato do texto (09/12/2009,
# 25/03/2015) viram competências.
#   inciso X    IPCA-E   jan/2001    → 09/12/2009   (antes do cursor entrar na TR)
#   inciso XI   TR       10/12/2009  → 25/03/2015   (dez/2009 → mar/2015)
#   inciso XII  IPCA-E   26/03/2015  → 30/11/2021   (abr/2015 → nov/2021)
#   inciso XIII SELIC    dez/2021 em diante         (= _EC113_VIGENCIA_SELIC)
_TR_JANELA_INI = date(2009, 12, 1)
_TR_JANELA_FIM = date(2015, 3, 1)
# §7º (Res. 482/2022): a TR do inciso XI vale SOMENTE para precatório EXPEDIDO ou
# PAGO até 25/03/2015 (modulação das ADIs 4357/4425 codificada). Sem data de
# expedição informada, o default é NÃO aplicar TR (usa IPCA-E) — é o regime do que
# foi expedido depois da modulação, o caso comum.
_MODULACAO_TR = date(2015, 3, 25)
# Art. 22: juros de mora na fase precatório incidem só até nov/2021; de dez/2021
# em diante a SELIC incide sobre o consolidado e embute os juros.
_ART22_JUROS_FIM = date(2021, 11, 1)
# Juros de mora da fase precatório = poupança do art. 1º-F (Lei 9.494/97, red. Lei
# 11.960/2009), vigente desde jul/2009. Antes disso a taxa depende do regime do
# título (natureza), que este motor não conhece → não acumula e avisa.
_POUPANCA_INICIO = date(2009, 7, 1)


def _taxa_poupanca_mes(mes_iso: str) -> Decimal:
    """Taxa de juros da poupança do mês (fração a.m.) — art. 1º-F red. Lei
    11.960/2009: 0,5% até abr/2012; depois min(0,5%; 70%×meta Selic/12).
    Delega ao motor histórico (`juros_historicos`), que é a fonte única da
    fórmula. Fora da cobertura da meta Selic → 0 (não inventa juros)."""
    from precaturia.pipeline import juros_historicos as _jh

    try:
        return _jh.taxa_poupanca_mensal(mes_iso)
    except (_jh.JurosForaDeCobertura, ValueError, FileNotFoundError):
        return Decimal("0")


def _inferir_selic_historica(
    principal_corrigido: Decimal,
    juros: Decimal,
    periodos_correcao: list[dict] | None,
    data_calculo: date | None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Decompõe `principal_corrigido` em principal pré-SELIC + SELIC acumulada.

    Quando a etapa 8 não separa `valor_selic` (layout Projef antigo), o
    `principal_corrigido` inclui a SELIC acumulada desde EC 113 (12/2021).
    Usando as séries BACEN, calculamos o fator SELIC no período e separamos.

    Retorna ``(principal_sem_selic, juros_sem_selic, selic_inferida)``.
    Se não for possível inferir (sem período SELIC, cobertura insuficiente),
    retorna os valores originais com ``selic=0``.
    """
    if not periodos_correcao or not data_calculo:
        return principal_corrigido, juros, Decimal("0")

    inicio_selic: date | None = None
    for p in periodos_correcao:
        if p.get("indice") != "SELIC":
            continue
        raw = p.get("inicio_data")
        if raw:
            try:
                inicio_selic = date.fromisoformat(raw)
            except ValueError:
                pass
            break
        inicio_selic = _EC113_VIGENCIA_SELIC
        break

    if inicio_selic is None or inicio_selic >= data_calculo:
        return principal_corrigido, juros, Decimal("0")

    try:
        fator = fator_periodo("SELIC", inicio_selic, data_calculo)
    except (IndiceNaoSuportado, KeyError):
        return principal_corrigido, juros, Decimal("0")

    if fator <= Decimal("1"):
        return principal_corrigido, juros, Decimal("0")

    total_com_selic = principal_corrigido + juros
    total_pre_selic = (total_com_selic / fator).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    selic_inferida = (total_com_selic - total_pre_selic).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    proporcao_principal = (
        principal_corrigido / total_com_selic if total_com_selic else Decimal("1")
    )
    principal_sem_selic = (total_pre_selic * proporcao_principal).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    juros_sem_selic = (total_pre_selic - principal_sem_selic).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return principal_sem_selic, juros_sem_selic, selic_inferida


# ─────────────── Updater segregado (modelo Projef Web) ───────────────


@dataclass(frozen=True)
class ResultadoSegregado:
    """Saída do `_atualizar_segregado` — modelo Projef Web.

    Após data_calculo:
    - `principal_corrigido_atualizado` = `principal_corrigido_inicial`
      (congelado em moeda da conta).
    - `juros_moratorios_atualizado` = `juros_moratorios_inicial`
      (congelado).
    - `selic_acumulada_atualizada` cresce como overlay LINEAR sobre a base
      `principal_corrigido_inicial` (não compõe com SELIC anterior → sem
      anatocismo). Pré-EC 136: `Σ tx_selic[m] × principal_inicial`.
      Pós-EC 136: `Σ min(tx_ipca[m] + 2/12 %, tx_selic[m]) × principal_inicial`.

    Esse desenho casa com a conta Projef: cada parcela atualizada cresce
    sobre o principal_corrigido CONGELADO da conta, sem juros sobre juros.
    """

    principal_corrigido_atualizado: Decimal
    juros_moratorios_atualizado: Decimal
    selic_acumulada_atualizada: Decimal
    atualizacao: Atualizacao

    @property
    def valor_total_atualizado(self) -> Decimal:
        return (
            self.principal_corrigido_atualizado
            + self.juros_moratorios_atualizado
            + self.selic_acumulada_atualizada
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def to_dict(self) -> dict:
        return {
            "principal_corrigido_atualizado": str(self.principal_corrigido_atualizado),
            "juros_moratorios_atualizado": str(self.juros_moratorios_atualizado),
            "selic_acumulada_atualizada": str(self.selic_acumulada_atualizada),
            "valor_total_atualizado": str(self.valor_total_atualizado),
            "atualizacao": self.atualizacao.to_dict(),
        }


_JUROS_SIMPLES_EC_136_MES = JUROS_SIMPLES_POS_EC_136_ANUAL / Decimal("12")


def _primeiro_dia_mes_local(d: date) -> date:
    return date(d.year, d.month, 1)


def _proximo_mes_local(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


# Art. 100 §5º CF — o corte de apresentação orçamentária mudou POR ÉPOCA e NÃO
# retroage (docs/regimes_historicos.md §0 achado 2, verificado): apresentado até
# a data-limite do exercício X entra no orçamento de X+1 (pago até 31/12 de X+1);
# após, vai para X+2. A data-limite vigente:
#   • até 2021              → 1º de julho     (redação original / EC 30 / EC 62)
#   • 2022 até a EC 136     → 2 de abril      (EC 114/2021, efeitos a partir de 2022)
#   • a partir da EC 136    → 1º de fevereiro (EC 136, vigência 09/09/2025;
#                             1ª aplicação: até 01/02/2026 → pagamento até 31/12/2027)
# A transição 02/04 → 02/02 é pela VIGÊNCIA da EC 136 (09/09/2025), não por ano.
# A checagem por ANO abaixo é EXATA mesmo assim: a única janela em que 02/04 ≠
# 02/02 é fev-abr, e nenhuma apresentação de fev-abr cai depois de 09/09/2025
# (fev-abr/2025 é anterior a 09/09; set-dez/2025 é indiferente, pois já passou
# dos dois cortes). Logo 2025 inteiro usa 02/04 e só 2026+ usa 02/02.
# Comparação INCLUSIVA na data-limite ("até"): apresentado no corte → X+1; +1 dia → X+2.
def _corte_apresentacao(ano: int) -> tuple[int, int]:
    """`(mês, dia)` da data-limite de apresentação vigente no exercício `ano`."""
    if ano <= 2021:
        return (7, 1)   # 1º de julho
    if ano <= 2025:
        return (4, 2)   # 2 de abril (EC 114) — 2025 inteiro (ver nota acima)
    return (2, 1)       # 1º de fevereiro (EC 136, desde 09/09/2025)

# Acima deste valor a requisição é inequivocamente precatório (o maior teto de
# RPV — 60 salários mínimos federais — fica ~R$ 91k em 2026). Usado só como
# rede de segurança contra falso 'rpv' na detecção de modalidade (o formulário
# TJES traz "RPV/Pequeno Valor" como boilerplate). Abaixo disso, respeita-se a
# modalidade detectada.
_TETO_RPV_PRECATORIO = Decimal("100000")


def _vencimento_periodo_graca(data_apresentacao: date) -> date:
    """Vencimento constitucional (fim da graça) = 31/12 do ano de pagamento P.

    Art. 100 §5º CF: apresentado até a data-limite do ano X (ver
    `_corte_apresentacao`, que varia por época) → P = X+1; após → P = X+2.
    Súmula Vinculante 17: no período entre a inclusão no orçamento e o
    vencimento não incidem juros — só correção monetária.
    """
    mes, dia = _corte_apresentacao(data_apresentacao.year)
    cutoff = date(data_apresentacao.year, mes, dia)
    if data_apresentacao <= cutoff:
        return date(data_apresentacao.year + 1, 12, 31)
    return date(data_apresentacao.year + 2, 12, 31)


def _primeiro_mes_graca(data_apresentacao: date) -> tuple[int, int]:
    """`(ano, mês)` do primeiro mês de graça = FEVEREIRO do ano anterior ao
    pagamento (art. 100 §5º CF pós-EC 136).

    A graça NÃO começa logo após a apresentação. O precatório roda índices
    normais (SELIC/EC 136) até fechar no orçamento — o corte de 02/02 do ano
    P-1 — e só então entra na graça, que corre de 1º/02 de (P-1) até 31/12 de
    P (janela fixa de 23 meses). P = ano de pagamento (= ano do vencimento).
    """
    venc = _vencimento_periodo_graca(data_apresentacao)  # 31/12 de P
    return venc.year - 1, 2  # fevereiro de (P-1)


def _graca_na_janela_coberta(
    data_alvo: date, data_apresentacao: date, indices_base: list[str]
) -> bool:
    """True se ao menos um mês de graça (a janela fev de P-1 → dez de P) cai
    dentro da janela coberta por `indices_base` (SELIC + IPCA), limitada por
    `data_alvo`. Só então a IPCA-E precisa entrar no recuo — senão a oferta
    seria capada num índice que o cálculo não chega a usar.
    """
    ultima_base = _ultima_data_coberta(indices_base)
    if ultima_base is None:
        return False
    fim = min(
        (data_alvo.year, data_alvo.month),
        (ultima_base.year, ultima_base.month),
    )
    primeiro_graca = _primeiro_mes_graca(data_apresentacao)
    venc = _vencimento_periodo_graca(data_apresentacao)
    return primeiro_graca <= (venc.year, venc.month) and fim >= primeiro_graca


def _apresentacao_cutoff(data_oficio: date) -> date:
    """Proxy da data de apresentação: a próxima data-limite constitucional
    (art. 100 §5º; ver `_corte_apresentacao`, que varia por época) em ou após
    `data_oficio`.

    A data de apresentação real raramente está nos autos. Em vez de usar a
    data de expedição do ofício como âncora da graça, usa-se a data-limite do
    ciclo orçamentário em que o precatório é incluído. Override do revisor
    (`data_apresentacao`, FieldReview) continua tendo precedência.
    """
    mes, dia = _corte_apresentacao(data_oficio.year)
    cutoff = date(data_oficio.year, mes, dia)
    if data_oficio <= cutoff:
        return cutoff
    prox_mes, prox_dia = _corte_apresentacao(data_oficio.year + 1)
    return date(data_oficio.year + 1, prox_mes, prox_dia)


def _atualizar_segregado(
    principal_corrigido_inicial: Decimal,
    juros_moratorios_inicial: Decimal,
    selic_acumulada_inicial: Decimal,
    data_origem: date | None,
    data_alvo: date,
    data_apresentacao: date | None = None,
    esfera: str | None = None,
    data_expedicao: date | None = None,
) -> ResultadoSegregado:
    """Atualiza os componentes entre `data_origem` (excl) e `data_alvo` (incl)
    pelo modelo ENCADEADO (chained), espelhando LBZ / Projef / Manual de Cálculos
    da JF (Res. CJF 784/2022).

    Cada fase de CORREÇÃO monetária multiplica o valor consolidado corrente
    (principal + juros + SELIC já acumulada) pelo fator seguinte — a correção
    "telescopa" (`V0·(1+i1)·(1+i2)`). NÃO é anatocismo: a Súmula 121 STF veda
    juros sobre juros, não correção sobre valor que contém juros (STJ pacífico).

    Quatro regimes temporais:

    0. **Fase precatório (art. 21-A Res. CNJ 303/2019)** — meses ANTERIORES a
       dez/2021 que ainda não venceram a graça: TR (dez/2009→mar/2015, SÓ se
       `data_expedicao` ≤ 25/03/2015 — §7º/modulação das ADIs 4357/4425) ou
       IPCA-E (incisos X e XII). Correção ENCADEIA sobre principal+juros; os
       juros de mora do art. 22 (poupança do art. 1º-F, desde jul/2009) somam na
       LINHA DE JUROS até nov/2021. Sem `data_expedicao`, o default é IPCA-E (sem
       TR). Vale para TODO mês pré-dez/2021 fora da graça — inclusive APÓS o
       vencimento (os juros voltam, Tema 1037); o §6º (inadimplido → SELIC) só
       opera quando a SELIC existe na cadeia, de dez/2021 em diante.

    1. **SELIC (EC 113)** — de dez/2021 em diante, inclusive pós-vencimento da
       graça (art. 21-A §6º). SIMPLES DENTRO da fase (`1 + Σ taxas mensais`, aplicada
       uma vez ao principal+juros) para NÃO reintroduzir SELIC-sobre-SELIC; só
       encadeia ENTRE fases. Até 2025-07-31.

    2. **EC 136** (`cursor ≥ 2025-08-01`, fora da graça): IPCA (correção,
       compõe/encadeia principal+juros+selic) + 2% a.a. (juros de mora, simples,
       somado à linha de JUROS). Teto: mês em que IPCA+2%/12 > SELIC vira SELIC.

    3. **Período de graça** (`data_apresentacao < cursor ≤ vencimento_graca`):
       art. 100 §5º CF + SV 17 — sem juros de mora; só IPCA-E (correção pura),
       encadeando sobre TUDO. `vencimento_graca` = 31/12 do ano X+1
       (apresentação ≤ 02/04 ano X) ou X+2 (após).

    A SELIC/EC 136-2% (juros) nunca reincide sobre juros já acumulados; a
    correção (IPCA/IPCA-E) encadeia sobre o consolidado inteiro. Sem
    `data_apresentacao`, não há graça (só SELIC/EC 136).

    Bordas:
    - `data_origem is None` → status `sem_data_origem`, valores intactos.
    - `data_alvo <= data_origem` → mesmo mês/anterior, sem ação.
    - Cobertura insuficiente → status `cobertura_insuficiente`.
    - `data_alvo > cobertura` → recua para a última data coberta
      (status `ok_ajustada_cobertura`).
    """
    if data_origem is None:
        return ResultadoSegregado(
            principal_corrigido_atualizado=principal_corrigido_inicial,
            juros_moratorios_atualizado=juros_moratorios_inicial,
            selic_acumulada_atualizada=selic_acumulada_inicial,
            atualizacao=Atualizacao(
                regime="SELIC (EC 113/2021)",
                fator=Decimal("1"),
                data_origem=None,
                data_alvo=data_alvo,
                status="sem_data_origem",
                mensagem=(
                    "data_calculo da etapa 8 não disponível — sem origem para "
                    "atualizar os componentes."
                ),
            ),
        )

    if (data_alvo.year, data_alvo.month) <= (data_origem.year, data_origem.month):
        if (data_alvo.year, data_alvo.month) < (data_origem.year, data_origem.month):
            status: AtualizacaoStatus = "data_alvo_anterior_origem"
            msg = (
                f"data_alvo ({data_alvo.isoformat()}) anterior à data_calculo "
                f"({data_origem.isoformat()}) — componentes em moeda da conta."
            )
        else:
            status = "data_alvo_igual_origem"
            msg = (
                f"data_alvo no mesmo mês de data_calculo "
                f"({data_origem.isoformat()}) — componentes em moeda da conta."
            )
        return ResultadoSegregado(
            principal_corrigido_atualizado=principal_corrigido_inicial,
            juros_moratorios_atualizado=juros_moratorios_inicial,
            selic_acumulada_atualizada=selic_acumulada_inicial,
            atualizacao=Atualizacao(
                regime="SELIC (EC 113/2021)",
                fator=Decimal("1"),
                data_origem=data_origem,
                data_alvo=data_alvo,
                status=status,
                mensagem=msg,
            ),
        )

    data_alvo_efetiva, ajustada = _ajustar_data_alvo(
        data_origem, data_alvo, data_apresentacao
    )

    try:
        # Graça (fase 2) corrige por IPCA-E (10764, Manual JF); o trecho EC 136
        # (fase 1/3 pós-vigência) corrige por IPCA cheio (433, texto da EC).
        serie_ipca_e = load_serie("IPCA-E")
        serie_ipca_ec136 = load_serie(_INDICE_CORRECAO_EC_136)
        serie_selic = load_serie("SELIC")
        # Fase precatório: TR do inciso XI (janela 2009-2015, condicionada ao §7º).
        serie_tr = load_serie("TR")
    except (KeyError, FileNotFoundError) as e:
        return ResultadoSegregado(
            principal_corrigido_atualizado=principal_corrigido_inicial,
            juros_moratorios_atualizado=juros_moratorios_inicial,
            selic_acumulada_atualizada=selic_acumulada_inicial,
            atualizacao=Atualizacao(
                regime="SELIC (EC 113/2021)",
                fator=Decimal("1"),
                data_origem=data_origem,
                data_alvo=data_alvo,
                status="cobertura_insuficiente",
                mensagem=f"Séries de índices indisponíveis: {e}",
            ),
        )

    # ── Modelo ENCADEADO: cada fase de CORREÇÃO monetária (IPCA-E da graça, IPCA
    # da EC 136) multiplica o valor consolidado corrente (principal + juros +
    # SELIC já acumulada) pelo fator seguinte — a correção "telescopa"
    # (V0·(1+i1)·(1+i2)) e NÃO é anatocismo (Súmula 121 STF veda juros s/ juros,
    # não correção; STJ). A SELIC fica SIMPLES DENTRO de cada fase (1+Σtaxas,
    # aplicada uma vez ao principal+juros) para não reintroduzir SELIC-sobre-SELIC
    # (o bug monolítico que inflava a Luciana); ela só encadeia ENTRE fases. A
    # linha de SELIC já acumulada da conta (`selic`) fica CONGELADA — não recebe
    # correção nem SELIC nova (espelha o gabarito Projef/CalculadoraPDF: a SELIC
    # acumulada é carregada nominalmente). Ver Manual JF (Res. CJF 784/2022).
    principal = principal_corrigido_inicial
    juros = juros_moratorios_inicial
    selic = selic_acumulada_inicial

    # Run SIMPLES de SELIC-like (EC 113 + meses capados da EC 136) contíguo,
    # aplicado de uma vez ao principal+juros ao fim do run.
    selic_run = Decimal("0")
    selic_run_inicio: date | None = None
    selic_run_fim: date | None = None
    # Segmentos p/ display: [tipo, inicio, fim, fator_principal]. tipo ∈
    # {'selic','ec136','graca'}.
    segmentos: list[list] = []
    seg_atual: list | None = None  # [tipo, inicio, fim, principal_no_inicio]
    meses_ec136 = 0
    meses_cap_ec136 = 0
    cap_acionado_em_algum_mes = False
    tem_ec_136 = False
    tem_graca = False
    # Fase precatório (art. 21-A): flags p/ observabilidade e ressalvas.
    tem_fase_prec = False
    usou_tr = False
    juros_pre_poupanca_ignorados = False  # meses < jul/2009 sem taxa conhecida
    # §7º: TR só p/ expedido/pago até 25/03/2015. Sem a data → NÃO usa TR (IPCA-E).
    tr_permitida = data_expedicao is not None and data_expedicao <= _MODULACAO_TR

    def _flush_selic() -> None:
        """Aplica o run SELIC acumulado (simples) ao principal+juros e registra o
        segmento. A SELIC NÃO incide sobre a SELIC já acumulada (`selic`)."""
        nonlocal principal, juros, selic_run, selic_run_inicio, selic_run_fim
        if selic_run_inicio is None:
            return
        f = Decimal("1") + selic_run
        principal *= f
        juros *= f
        segmentos.append([
            "selic", selic_run_inicio,
            _ultimo_dia_mes(selic_run_fim.year, selic_run_fim.month), f, f,
            Decimal("0"), Decimal("0"),  # SELIC consolida — sem juros novos
        ])
        selic_run = Decimal("0")
        selic_run_inicio = None
        selic_run_fim = None

    def _fechar_seg() -> None:
        """Fecha o segmento composto atual (graça / EC 136 / fase 21-A),
        registrando os fatores de crescimento do principal E dos juros e
        DECOMPONDO a linha de juros (estilo gabarito): `juros_novos` = o que a
        fase somou além da correção (poupança do art. 22 / 2% a.a. da EC 136) —
        identidade exata juros_fim = j0 × fator + juros_novos. `taxa` = soma
        das taxas mensais aplicadas (informativa)."""
        nonlocal seg_atual
        if seg_atual is None:
            return
        tipo, ini, fim, p0, j0, taxa = seg_atual
        fator = principal / p0 if p0 > 0 else Decimal("1")
        fator_j = juros / j0 if j0 > 0 else Decimal("1")
        juros_novos = juros - j0 * fator
        if juros_novos < Decimal("0.005"):  # ruído de precisão em fase sem juros novos
            juros_novos = Decimal("0")
        segmentos.append(
            [tipo, ini, _ultimo_dia_mes(fim.year, fim.month), fator, fator_j,
             juros_novos, taxa]
        )
        seg_atual = None

    ec136_vig = _ec136_vigencia(esfera)  # ago/2025 (estadual) ou set/2025 (federal)
    vencimento_graca = (
        _vencimento_periodo_graca(data_apresentacao)
        if data_apresentacao is not None
        else None
    )
    # Início da graça = data-limite do orçamento do ano anterior ao pagamento
    # (P-1), NÃO a apresentação. Antes disso o precatório corre índice normal
    # (SELIC/EC 136); só a partir daqui entra na graça (sem juros — SV 17). A
    # data-limite varia por época (ver `_corte_apresentacao`): 1º/07 até 2021,
    # 02/04 (2022-2025), 1º/02 (EC 136, 2026+).
    if vencimento_graca is not None:
        _p_menos_1 = vencimento_graca.year - 1
        _cmes, _ = _corte_apresentacao(_p_menos_1)
        # 1º dia do MÊS do corte (o mês do corte é o 1º mês de graça) — mantém a
        # convenção do modelo original (Feb 1 no corte 02/02), agora por época.
        inicio_graca = date(_p_menos_1, _cmes, 1)
    else:
        inicio_graca = None

    cursor = _proximo_mes_local(_primeiro_dia_mes_local(data_origem))
    fim_iter = _primeiro_dia_mes_local(data_alvo_efetiva)

    try:
        while cursor <= fim_iter:
            mes_iso = f"{cursor.year:04d}-{cursor.month:02d}"
            tx_selic_pct = serie_selic.get(mes_iso)
            if tx_selic_pct is None:
                raise IndiceNaoSuportado(
                    f"mês {mes_iso} fora da cobertura da SELIC",
                    {"mes": mes_iso},
                )
            tx_selic = tx_selic_pct / Decimal("100")

            # Fase 2 (graça): a janela [1º/02 de (P-1) → 31/12 de P] (art. 100
            # §5º CF pós-EC 136 + SV 17). Só IPCA-E sobre principal+juros; SELIC/
            # juros parados. NÃO começa na apresentação — o precatório roda índice
            # normal (SELIC/EC 136) até fev de (P-1).
            em_graca = (
                inicio_graca is not None
                and vencimento_graca is not None
                and cursor >= inicio_graca
                and cursor <= vencimento_graca
            )
            if em_graca:
                # Correção pura (SV 17 suspende juros): IPCA-E ENCADEIA sobre tudo.
                # NOTA (decisão jurídica pendente — regimes_historicos §0 achado 3):
                # a Res. 303 art. 21-A §5º manda IPCA-E (inciso XII) na graça e é o
                # que os tribunais/Projef aplicam; a leitura "IPCA cheio (433) na
                # graça regida pela EC 136" é literal mas contestada. Mantemos
                # IPCA-E (alinhado ao tribunal) até o advogado decidir.
                tem_graca = True
                _flush_selic()
                tx_ipca_pct = serie_ipca_e.get(mes_iso)
                if tx_ipca_pct is None:
                    raise IndiceNaoSuportado(
                        f"mês {mes_iso} fora da cobertura do IPCA-E (graça)",
                        {"mes": mes_iso},
                    )
                if seg_atual is None or seg_atual[0] != "graca":
                    _fechar_seg()
                    seg_atual = ["graca", cursor, cursor, principal, juros, Decimal("0")]
                f = Decimal("1") + tx_ipca_pct / Decimal("100")
                principal *= f
                juros *= f
                # SELIC já acumulada CONGELADA (não recebe correção) — só
                # principal e juros crescem na graça.
                seg_atual[2] = cursor
            elif cursor < _EC113_VIGENCIA_SELIC:
                # ── Fase precatório (art. 21-A Res. 303) ──────────────────────
                # Todo mês pré-EC 113 fora da graça — ANTES ou DEPOIS do
                # vencimento: correção dos incisos X/XII (IPCA-E, ou TR na
                # janela do §7º) + juros do art. 22 (poupança; correm antes da
                # graça — Tema 96 — e VOLTAM após o vencimento — Tema 1037). O
                # §6º ("inadimplido → SELIC", incluído pela Res. 448/2022) só
                # opera de dez/2021 em diante, quando a SELIC existe na cadeia;
                # aplicá-lo a meses de 2021 retroagiria a norma e contraria o
                # inciso XII + art. 22 (gabarito USS, caso BA: jan–nov/2021
                # pós-graça = IPCA-E + poupança, nunca SELIC).
                tem_fase_prec = True
                _flush_selic()
                usa_tr = tr_permitida and _TR_JANELA_INI <= cursor <= _TR_JANELA_FIM
                if usa_tr:
                    usou_tr = True
                    tx_pct = serie_tr.get(mes_iso)
                    rotulo_seg = "fase_tr"
                    nome_idx = "TR"
                else:
                    tx_pct = serie_ipca_e.get(mes_iso)
                    rotulo_seg = "fase_ipcae"
                    nome_idx = "IPCA-E"
                if tx_pct is None:
                    raise IndiceNaoSuportado(
                        f"mês {mes_iso} fora da cobertura do {nome_idx} "
                        "(fase precatório art. 21-A)",
                        {"mes": mes_iso, "indice": nome_idx},
                    )
                if seg_atual is None or seg_atual[0] != rotulo_seg:
                    _fechar_seg()
                    seg_atual = [rotulo_seg, cursor, cursor, principal, juros, Decimal("0")]
                f = Decimal("1") + tx_pct / Decimal("100")
                principal *= f
                juros *= f
                # SELIC já acumulada CONGELADA (mesma regra das demais fases).
                # Juros de mora do art. 22: poupança (art. 1º-F) sobre o principal
                # corrente, simples, na LINHA DE JUROS — só até nov/2021.
                if cursor <= _ART22_JUROS_FIM:
                    if cursor >= _POUPANCA_INICIO:
                        tx_poup = _taxa_poupanca_mes(mes_iso)
                        juros += tx_poup * principal
                        seg_atual[5] += tx_poup  # p/ display (taxa_juros_novos)
                    else:
                        juros_pre_poupanca_ignorados = True
                seg_atual[2] = cursor
            elif cursor < ec136_vig:
                # SELIC EC 113: acumula SIMPLES (aplicada de uma vez no fim do run).
                _fechar_seg()
                selic_run += tx_selic
                if selic_run_inicio is None:
                    selic_run_inicio = cursor
                selic_run_fim = cursor
            else:
                # EC 136: IPCA (correção, ENCADEIA sobre tudo) + 2% a.a. (juros,
                # na linha de juros); teto SELIC → mês capado vira SELIC-like.
                tem_ec_136 = True
                meses_ec136 += 1
                tx_ipca_pct = serie_ipca_ec136.get(mes_iso)
                if tx_ipca_pct is None:
                    raise IndiceNaoSuportado(
                        f"mês {mes_iso} fora da cobertura do IPCA (EC 136)",
                        {"mes": mes_iso},
                    )
                tx_ipca = tx_ipca_pct / Decimal("100")
                if tx_ipca + _JUROS_SIMPLES_EC_136_MES > tx_selic:
                    # Teto SELIC: mês vira SELIC pura, simples (acumula no run).
                    cap_acionado_em_algum_mes = True
                    meses_cap_ec136 += 1
                    _fechar_seg()
                    selic_run += tx_selic
                    if selic_run_inicio is None:
                        selic_run_inicio = cursor
                    selic_run_fim = cursor
                else:
                    _flush_selic()
                    if seg_atual is None or seg_atual[0] != "ec136":
                        _fechar_seg()
                        seg_atual = ["ec136", cursor, cursor, principal, juros, Decimal("0")]
                    principal *= Decimal("1") + tx_ipca
                    juros *= Decimal("1") + tx_ipca
                    # SELIC já acumulada CONGELADA (não recebe correção).
                    # 2% a.a. (juros de mora), simples, sobre o principal corrente,
                    # somado à LINHA DE JUROS (não incide sobre juros já vencidos).
                    juros += _JUROS_SIMPLES_EC_136_MES * principal
                    seg_atual[5] += _JUROS_SIMPLES_EC_136_MES  # p/ display
                    seg_atual[2] = cursor

            cursor = _proximo_mes_local(cursor)
    except IndiceNaoSuportado as e:
        return ResultadoSegregado(
            principal_corrigido_atualizado=principal_corrigido_inicial,
            juros_moratorios_atualizado=juros_moratorios_inicial,
            selic_acumulada_atualizada=selic_acumulada_inicial,
            atualizacao=Atualizacao(
                regime="SELIC (EC 113/2021)",
                fator=Decimal("1"),
                data_origem=data_origem,
                data_alvo=data_alvo,
                status="cobertura_insuficiente",
                mensagem=(
                    f"Séries de índices não cobrem o intervalo solicitado: "
                    f"{e.motivo}. Atualize as séries (scripts/baixar_indices.py) "
                    "ou escolha data_alvo mais antiga."
                ),
            ),
        )

    # Fecha runs/segmentos pendentes e ordena cronologicamente para o display.
    _flush_selic()
    _fechar_seg()
    segmentos.sort(key=lambda s: s[1])

    selic_atualizada = selic.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_final = principal + juros + selic
    base_inicial = (
        principal_corrigido_inicial
        + juros_moratorios_inicial
        + selic_acumulada_inicial
    )
    fator_efetivo = (
        total_final / base_inicial if base_inicial > 0 else Decimal("1")
    )

    _ROTULO = {
        "selic": "SELIC (EC 113/2021)",
        "ec136": "IPCA + 2% a.a. capped SELIC mensal (EC 136/2025)",
        "graca": "IPCA-E período de graça (art. 100 §5º CF, SV 17 — SELIC parada)",
        "fase_tr": "TR + juros da poupança (fase precatório, art. 21-A XI Res. 303)",
        "fase_ipcae": "IPCA-E + juros da poupança (fase precatório, art. 21-A X/XII)",
    }
    componentes: list[ComponenteAtualizacao] = [
        ComponenteAtualizacao(
            regime=_ROTULO.get(tipo, tipo),
            # 1º componente preserva `data_origem` (exclusivo) como início.
            inicio=data_origem if i == 0 else _primeiro_dia_mes_local(ini),
            fim=fim,
            fator=fator,
            fator_juros=fator_j,
            cap_acionado=(tipo == "ec136" and cap_acionado_em_algum_mes),
            juros_novos=juros_novos.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            taxa_juros_novos=taxa,
        )
        for i, (tipo, ini, fim, fator, fator_j, juros_novos, taxa) in enumerate(segmentos)
    ]
    regime_legivel = (
        " + ".join(c.regime for c in componentes) if componentes else "SELIC (EC 113/2021)"
    )
    status_final: AtualizacaoStatus = "ok_ajustada_cobertura" if ajustada else "ok"
    msg_ajuste = (
        f" Data alvo solicitada {data_alvo.isoformat()} excede a cobertura "
        f"das séries — recuada para {data_alvo_efetiva.isoformat()}."
        if ajustada
        else ""
    )
    crescimento = (total_final - base_inicial).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    cap_txt = (
        f" (teto SELIC acionado em {meses_cap_ec136} de {meses_ec136} "
        f"{'mês' if meses_ec136 == 1 else 'meses'} da EC 136)"
        if meses_cap_ec136
        else ""
    )
    # Fase precatório (art. 21-A): explicita a escolha TR × IPCA-E do §7º — sem
    # data de expedição a TR NÃO é aplicada, e isso muda o número; o advogado
    # precisa saber para poder informar a expedição.
    fase_txt = ""
    if tem_fase_prec:
        if usou_tr:
            fase_txt = (
                " Fase precatório (art. 21-A): TR aplicada na janela "
                "dez/2009–mar/2015 (inciso XI; expedido até 25/03/2015, §7º)."
            )
        elif data_expedicao is None:
            fase_txt = (
                " Fase precatório (art. 21-A): corrigido por IPCA-E. A data de "
                "EXPEDIÇÃO não foi informada, então a TR do inciso XI não foi "
                "aplicada na janela dez/2009–mar/2015 (§7º: TR só para precatório "
                "expedido/pago até 25/03/2015). Se o precatório é anterior a "
                "25/03/2015, informe a expedição — o valor muda."
            )
        else:
            fase_txt = (
                " Fase precatório (art. 21-A): IPCA-E — expedido depois de "
                "25/03/2015, a modulação das ADIs 4357/4425 afasta a TR (§7º)."
            )
        if juros_pre_poupanca_ignorados:
            fase_txt += (
                " ATENÇÃO: meses anteriores a jul/2009 NÃO tiveram juros de mora "
                "acumulados — a taxa depende do regime do título (natureza), que "
                "esta atualização não conhece. Conferir."
            )
    mensagem = (
        f"Atualização encadeada de {data_origem.isoformat()} (excl) a "
        f"{data_alvo_efetiva.isoformat()} (incl): cada fase multiplica o valor "
        f"consolidado corrente pelo índice seguinte — SELIC simples dentro da "
        f"fase, correção encadeando entre fases. Crescimento total "
        f"R$ {crescimento} (fator efetivo {fator_efetivo}){cap_txt}. "
        f"Composição: {regime_legivel}.{msg_ajuste}{fase_txt}"
    )
    ressalva = _RESSALVA_ADI_7873 if tem_ec_136 else None

    return ResultadoSegregado(
        principal_corrigido_atualizado=principal.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        juros_moratorios_atualizado=juros.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        selic_acumulada_atualizada=selic_atualizada,
        atualizacao=Atualizacao(
            regime=regime_legivel,
            fator=fator_efetivo,
            data_origem=data_origem,
            data_alvo=data_alvo_efetiva,
            status=status_final,
            mensagem=mensagem,
            componentes=componentes,
            ressalva_adi=ressalva,
            data_alvo_solicitada=data_alvo if ajustada else None,
        ),
    )


def _projetar_bloco_oficio(
    oficio: OficioGroundTruthDict,
    data_alvo: date,
    data_apresentacao: date | None,
    pss_caso: Decimal | None = None,
    ir_caso: Decimal | None = None,
) -> BlocoOficio:
    """Projeta um único ofício elegível até `data_alvo`, montando `BlocoOficio`.

    Trata `valor_credor` como principal no `_atualizar_segregado` — juros e
    SELIC inicial = 0 (já consolidados no ofício). Resultado é o valor do
    líquido atualizado e a decomposição da projeção (regime composto SELIC
    EC 113 + IPCA+2% EC 136 + período de graça).

    PSS/IR vindos do caso (etapas 9/10) são aplicados APENAS quando
    `oficio["e_credor_exequente"] is True`. Ofícios de terceiros (advogado
    sucumbenciais) ficam com PSS/IR null e o líquido só é projetado quando
    a classificação já foi feita.
    """
    data_oficio = oficio["data_oficio"]
    valor_credor = oficio["valor_credor"]
    # Data de referência do bloco: a data de expedição quando há; senão a DATA
    # BASE. Em eproc federal (TRF) o requisitório eletrônico traz só a "Data
    # Base", não a data de expedição — sem este fallback o requisitório fica
    # inelegível e a oferta cai numa conta antiga (caso CASO/CASO/CASO).
    # A elegibilidade (construir_cenarios) aceita um dos dois; aqui consolidamos.
    data_base = oficio.get("data_base")
    data_ref = data_oficio or data_base
    assert data_ref is not None and valor_credor is not None, (
        "elegibilidade garantida em construir_cenarios"
    )

    # Origem da projeção é a DATA BASE (data até a qual o valor já está
    # corrigido no ofício), não a data de cadastro/expedição. A requisição
    # corrige o valor até a data base e só é expedida meses depois — ancorar
    # na expedição subestima a atualização (ou cai em cobertura_insuficiente
    # quando a expedição é recente). Fallback para data_oficio se ausente.
    data_origem_proj = oficio.get("data_base") or data_oficio

    # Período de graça (art. 100 §5º CF + SV 17) — DECISÃO SISTÊMICA 2026-06-01:
    # todo PRECATÓRIO recebe a janela de graça por default. Entre a apresentação
    # e o vencimento corre só IPCA-E (SELIC parada). RPV não recebe graça (pago
    # em 60 dias); modalidade NÃO detectada assume precatório (a maioria; só
    # RPV explícito é excluído). Override manual do revisor (`data_apresentacao`,
    # FieldReview) tem precedência. A âncora deixou de ser a data de expedição
    # (`data_oficio`) e passou a ser a data-limite constitucional de apresentação
    # (próximo 02/04) — ver `_apresentacao_cutoff`: a SELIC parava cedo demais
    # ancorando na expedição (divergência ~R$ 12k vs gabarito LBZ no caso
    # CASO, onde a modalidade nem era detectada e a graça não rodava).
    # RPV de valor baixo não recebe graça. A detecção de modalidade é frágil
    # (boilerplate "RPV/Pequeno Valor" no formulário → falso 'rpv'); por isso só
    # se exclui da graça o RPV cujo valor cabe no teto — crédito acima disso é
    # precatório, ainda que mal-rotulado (caso CASO: R$ 296k tido como rpv).
    e_rpv_real = (
        oficio.get("modalidade") == "rpv"
        and (valor_credor or Decimal("0")) <= _TETO_RPV_PRECATORIO
    )
    # Precedência da âncora do período de graça (art. 100 §5º CF + SV 17):
    #   1. override manual do revisor (FieldReview etapa 8/6) — sempre vence;
    #   2. data REAL de envio ao tribunal extraída do eproc (ground truth);
    #   3. proxy do próximo 02/04 (`_apresentacao_cutoff`, data-limite orçam.).
    # RPV real não recebe graça (pago em 60 dias) — fica None salvo override.
    fonte_apresentacao: str | None = None
    data_apres_efetiva = data_apresentacao
    if data_apres_efetiva is not None:
        fonte_apresentacao = "override_revisor"
    elif not e_rpv_real:
        envio_tribunal = oficio.get("data_envio_tribunal")
        if envio_tribunal is not None:
            data_apres_efetiva = envio_tribunal
            fonte_apresentacao = "envio_tribunal_eproc"
        else:
            data_apres_efetiva = _apresentacao_cutoff(data_ref)
            fonte_apresentacao = "proxy_cutoff_0204"

    seg = _atualizar_segregado(
        principal_corrigido_inicial=valor_credor,
        juros_moratorios_inicial=Decimal("0"),
        selic_acumulada_inicial=Decimal("0"),
        data_origem=data_origem_proj,
        data_alvo=data_alvo,
        data_apresentacao=data_apres_efetiva,
    )

    observacoes: list[str] = []
    # Observabilidade: sinaliza quando a graça foi ancorada na data REAL de
    # envio ao tribunal (eproc) em vez do proxy 02/04. SÓ emite quando a graça
    # de fato entrou na projeção (há um componente de graça no resultado) — se a
    # data de envio for posterior à data_alvo, a graça não roda e a observação
    # seria enganosa.
    _graca_aplicada = any(
        "graça" in (c.regime or "").lower() for c in seg.atualizacao.componentes
    )
    if fonte_apresentacao == "envio_tribunal_eproc" and _graca_aplicada:
        observacoes.append(
            "Período de graça ancorado na data REAL de envio ao tribunal "
            f"({data_apres_efetiva.strftime('%d/%m/%Y')}, separador eproc), não "
            "no proxy 02/04 — mais preciso (art. 100 §5º CF + SV 17)."
        )
    # Regra 5 (revisão humana vê a âncora mais fraca): quando o valor veio do
    # BRUTO da decisão homologatória (fallback `valor_de_bruto`, sem requisitório
    # formal — caso CASO/TJMG), sinaliza para o revisor conferir. A flag é
    # produzida em api.cases._oficios_ground_truth; antes morria no dict.
    if oficio.get("valor_de_bruto"):
        observacoes.append(
            "⚠ Valor ancorado no BRUTO da decisão homologatória (não há "
            "requisitório formal com líquido cedível) — âncora mais fraca; "
            "confira o destaque de honorários e a modalidade de pagamento."
        )
    if oficio["valor_oficial_oficio"] is None:
        observacoes.append(
            "valor_oficial_oficio ausente — valor_total exibido cai pra "
            "valor_credor (sem bruto declarado)."
        )
    if (
        oficio["valor_sucumbenciais"] is None
        and oficio["valor_contratuais"] is None
    ):
        observacoes.append(
            "Honorários sucumbenciais e contratuais não decompostos no "
            "ofício — decomposição ausente, líquido segue confiável."
        )
    if oficio.get("ancora_sem_citacao"):
        _campo_ancora = oficio.get("ancora_campo") or "valor"
        observacoes.append(
            f"⚠ Âncora sem citação verificável — o valor que sustenta a oferta "
            f"({_campo_ancora}) teve a citação ANULADA (regra 1); confirme o "
            f"valor diretamente no PDF/requisitório."
        )

    # PSS/IR e líquido por bloco — só os exequentes herdam o override do caso.
    e_credor_exequente = oficio.get("e_credor_exequente")
    valor_pss: Decimal | None = None
    valor_ir: Decimal | None = None
    valor_liquido: Decimal | None = None
    valor_liquido_atualizado: Decimal | None = None

    valor_credor_atualizado_dec = seg.valor_total_atualizado
    if e_credor_exequente is True:
        valor_pss = pss_caso if pss_caso is not None else None
        valor_ir = ir_caso if ir_caso is not None else None
        valor_liquido = valor_credor - (valor_pss or Decimal("0")) - (
            valor_ir or Decimal("0")
        )
        if valor_credor != 0:
            # O principal e o PSS (em moeda da DATA-BASE) escalam ao presente pelo
            # fator; o IR já vem em moeda do PRESENTE (etapa 10 com data_alvo) e é
            # abatido UMA vez, SEM re-escalar — senão seria multiplicado pelo fator
            # (caso CASO: IR 505,43 virava 542,98 no líquido).
            fator = valor_credor_atualizado_dec / valor_credor
            valor_liquido_atualizado = (
                valor_credor - (valor_pss or Decimal("0"))
            ) * fator - (valor_ir or Decimal("0"))
        else:
            valor_liquido_atualizado = valor_liquido
    elif e_credor_exequente is False:
        observacoes.append(
            "Crédito de terceiro (ex.: honorários sucumbenciais do advogado) — "
            "PSS/IR não tratados aqui; tributação tem regra própria do credor."
        )
    else:  # None — não classificado
        observacoes.append(
            "Beneficiário não classificado (e_credor_exequente=null) — "
            "marque via PUT /cases/{id}/documents/{doc_id}/credor para "
            "agregar este ofício na oferta do exequente."
        )

    return BlocoOficio(
        document_id=oficio["document_id"],
        document_nome=oficio["document_nome"],
        llm_call_id=oficio["llm_call_id"],
        data_oficio=data_ref,
        valor_oficial_oficio=oficio["valor_oficial_oficio"],
        valor_credor=_q(valor_credor),
        valor_sucumbenciais=_q(oficio["valor_sucumbenciais"]),
        valor_contratuais=_q(oficio["valor_contratuais"]),
        valor_credor_atualizado=_q(valor_credor_atualizado_dec),
        principal_corrigido_atualizado=seg.principal_corrigido_atualizado,
        juros_moratorios_atualizado=seg.juros_moratorios_atualizado,
        selic_acumulada_atualizada=seg.selic_acumulada_atualizada,
        valor_total_atualizado=_q(valor_credor_atualizado_dec),
        atualizacao=seg.atualizacao,
        e_credor_exequente=e_credor_exequente,
        natureza_requisicao=oficio.get("natureza_requisicao"),
        nome_credor=oficio.get("nome_credor"),
        cessao=oficio.get("cessao"),
        data_base=oficio.get("data_base"),
        valor_pss=_q(valor_pss),
        valor_ir=_q(valor_ir),
        valor_liquido=_q(valor_liquido),
        valor_liquido_atualizado=_q(valor_liquido_atualizado),
        observacoes=observacoes,
        ancora_sem_citacao=bool(oficio.get("ancora_sem_citacao")),
    )


def _construir_cenarios_oficio(
    oficios: list[OficioGroundTruthDict],
    etapa9_payload: dict | None,
    etapa10_payload: dict | None,
    reconciliacao_status: str | None,
    data_alvo: date,
    data_apresentacao: date | None,
    contratuais_pct: Decimal | None = None,
    agregar_exequente: bool = False,
    conta_total_ref: Decimal | None = None,
) -> ResultadoCenarios:
    """Caminho "ofício como ground truth" (etapa 5 v4+) — multi-ofício aware.

    `oficios` é a LISTA de ofícios elegíveis (cada um com `valor_credor` E
    `data_oficio` preenchidos) — filtro garantido pelo caller `construir_cenarios`.

    **N=1**: cenário homologado populado a partir do único bloco (comportamento
    pré-refactor preservado bit-a-bit). Cenário sentencial = convergente se
    reconciliação=conforme, indisponível caso contrário. `valor_oferta_base` =
    líquido atualizado.

    **N>1**: regra inviolável #6/#8 do CLAUDE.md proíbe agregação (cada ofício
    é pagamento independente; beneficiário/modalidade/base distintos). Ambos
    os cenários ficam `disponivel=False` com observação multi-ofício;
    `valor_oferta_base=None`; `multi_oficio=True`. Consumidores (UI/dossiê)
    devem renderizar `blocos_oficio` em vez de número único.
    """
    # PSS/IR do caso (etapas 9/10 com override). Aplicado por bloco apenas
    # nos com `e_credor_exequente=True`. Em N=1, o cenário homologado
    # continua agregando direto (compat); só o `bloco.valor_pss/valor_ir`
    # depende da classificação.
    pss_caso = (
        _to_decimal((etapa9_payload or {}).get("valor_pss"))
        if etapa9_payload
        else None
    )
    ir_caso = (
        _to_decimal((etapa10_payload or {}).get("valor_ir"))
        if etapa10_payload
        else None
    )

    # Projeta cada ofício individualmente. PSS/IR do caso (etapas 9/10) são
    # replicados por bloco do exequente — necessário p/ exibir créditos DISTINTOS
    # (herdeiros: cada um abate seu próprio PSS/IR, caso CASO). O "contar uma
    # vez" é feito SÓ na agregação do MESMO crédito (recebível-único, F4/F6).
    blocos = [
        _projetar_bloco_oficio(o, data_alvo, data_apresentacao, pss_caso, ir_caso)
        for o in oficios
    ]

    if len(blocos) > 1:
        return _resultado_multi_oficio(blocos, pss_caso, ir_caso, agregar=agregar_exequente)

    # N=1: caminho single-ofício preservado.
    bloco = blocos[0]

    # Regra 8 (iii): se o ÚNICO ofício é crédito de TERCEIRO (advogado —
    # `e_credor_exequente=False` explícito), NÃO ancorar a oferta nele. O
    # crédito do exequente (principal) não foi detectado/classificado — sinaliza
    # em vez de ofertar o honorário de terceiro. Bloqueia só em `is False`
    # (classificação explícita "advogado"); `None` (não-classificado) e `True`
    # seguem o caminho normal — preserva CASO/CASO/CASO (flag None).
    # Espelha a guarda do path N>1 (`_resultado_multi_oficio`, `if not exequentes`).
    # Caso CASO: principal R$ 950.315,74 perdido no slicing; só o sucumbencial
    # do advogado virou ofício e ancorava a oferta em R$ 162.924,27.
    if bloco.e_credor_exequente is False:
        return _resultado_sem_exequente(
            [bloco],
            observacao_homologado=(
                "Crédito do exequente não detectado: o único ofício analisado é "
                "honorário de TERCEIRO (advogado). A oferta do exequente exige o "
                "requisitório do PRINCIPAL, que não foi extraído/classificado. "
                "Verifique a etapa 5 (o principal pode ter sido perdido no "
                "slicing) ou classifique via PUT /cases/{id}/documents/{doc_id}/credor."
            ),
        )

    valor_oficial = bloco.valor_oficial_oficio
    valor_credor = bloco.valor_credor
    valor_credor_atualizado = bloco.valor_credor_atualizado
    valor_credor_bruto = bloco.valor_credor  # preservado para exibir o bruto

    # Honorários contratuais por PERCENTUAL (art. 22 §4º Lei 8.906 — destaque).
    # Quando o despacho/ofício NÃO discrimina o VALOR do contratual mas há um
    # percentual extraído (etapa 5/6), o `valor_credor` é o principal BRUTO e os
    # contratuais saem dele — abate-se o % para chegar ao líquido do exequente
    # (caso MAURA eproc: principal R$ 360.209,55 com destaque de 30%). Quando há
    # valor explícito (caso CASO), `valor_credor` já é o líquido — não abate.
    # Espelha a regra do caminho legado (conta) em `construir_cenarios`.
    contr_carve: Decimal | None = bloco.valor_contratuais
    contr_pct_aplicado: Decimal | None = None
    contr_obs: str | None = None
    if (
        bloco.valor_contratuais is None
        and contratuais_pct is not None
        and contratuais_pct > 0
        and valor_credor is not None
    ):
        # ANTI-DUPLA-CONTAGEM (eproc federal): se o `valor_credor` do ofício já é
        # o LÍQUIDO do autor — i.e., bate com `total_da_conta × (1 − pct)` — o
        # destaque de honorários já foi feito numa requisição SEPARADA do
        # advogado; carvear de novo desconta duas vezes (caso CASO/TRF2:
        # requisitório 130.753,25 = conta 186.790,37 × 0,70). Tolerância 2% do
        # total da conta. Quando o valor é o BRUTO (caso MAURA), não bate → carve
        # normal. Sem conta de referência, mantém o comportamento atual.
        fator_pct = Decimal("1") - contratuais_pct / Decimal("100")
        # O carve do % contratual só é seguro quando `valor_credor` é o BRUTO —
        # a integralidade do crédito, ≈ total da conta. Em requisitório federal
        # eproc o principal do exequente JÁ vem líquido (os honorários
        # contratuais são destacados numa requisição PRÓPRIA do advogado) e fica
        # ABAIXO do total da conta; carvear de novo dobraria o desconto (caso
        # CASO: 73.576,98 já é 70% do total do ofício 105.109,98 — não bate
        # com a conta 98.540,59 nem com conta×70%; 2º carve levaria a 51.503).
        # Regra: só carva quando o crédito BATE com o total da conta (≈ bruto);
        # materialmente abaixo = já-líquido → surfaça o % como observação, sem
        # deduzir. Sem conta de referência, mantém o carve (conservador para o
        # comprador; caso MAURA, cujo valor_credor É o bruto declarado).
        # Referência de BRUTO = o maior entre o total da conta (etapa 8) e o
        # "Total Requisitado" do próprio ofício (`valor_oficial_oficio`). Em
        # requisitório multi-requisição (eproc) o total do ofício SOMA principal
        # + honorários + sucumbência; se `valor_credor` fica abaixo dele, o
        # principal já é líquido. Usar o ofício como referência cobre o caso em
        # que a etapa 8 (conta) falhou (valor_total nulo) mas o total do ofício
        # foi extraído. Sem nenhuma referência (>0), mantém o carve.
        gross_ref = max(
            conta_total_ref or Decimal("0"),
            valor_oficial or Decimal("0"),
        )
        e_bruto = gross_ref <= 0 or valor_credor >= gross_ref * (
            Decimal("1") - Decimal("0.02")
        )
        if not e_bruto:
            contr_obs = (
                f"Honorários contratuais de {contratuais_pct}% NÃO descontados "
                "novamente: o valor do requisitório já está abaixo do total da "
                f"conta ({conta_total_ref}) — é o líquido do exequente (honorários "
                "destacados em requisição própria do advogado, eproc). Carve "
                "suprimido para não duplicar — confira a decomposição."
            )
        else:
            contr_carve = _q(valor_credor * contratuais_pct / Decimal("100"))
            valor_credor = _q(valor_credor * fator_pct)
            if valor_credor_atualizado is not None:
                valor_credor_atualizado = _q(valor_credor_atualizado * fator_pct)
            contr_pct_aplicado = contratuais_pct
            contr_obs = (
                f"Honorários contratuais de {contratuais_pct}% destacados do principal "
                f"(art. 22 §4º Lei 8.906) — líquido do exequente = bruto − contratual."
            )

    # ── PSS e IR do crédito — ABATIDOS do líquido (exibido == deduzido) ─────
    # No single-ofício o `valor_credor` é o líquido CEDÍVEL declarado, já
    # líquido do destaque contratual. PSS e IR são abatidos dele para compor o
    # líquido/oferta — antes eram exibidos mas NÃO deduzidos (números órfãos).
    #
    # PSS (decisão do dono 2026-06-08): override/conta declarada → usa o valor;
    #   INCIDE e SEM conta (fonte=estimado) → estima a alíquota padrão (14%)
    #   sobre o crédito atualizado e DESCONTA, com PONTO DE ATENÇÃO (a conta
    #   diria o valor exato; estimativa conservadora a favor de oferta menor);
    #   não incide → 0; misto/indefinido → None ("a apurar pelo advogado").
    # IR-RRA: override → usa o valor; não incide → 0; sem natureza OU sem nº de
    #   meses confiável (fonte=fallback_1) → None ("a apurar" — meses=1 inflaria
    #   a verba acumulada); senão recalcula sobre o crédito atualizado e DESCONTA.
    obs_descontos: list[str] = []
    base_desconto = (
        valor_credor_atualizado if valor_credor_atualizado is not None else valor_credor
    )

    incide_pss = (etapa9_payload or {}).get("incide")
    fonte_pss = (etapa9_payload or {}).get("fonte_pss")
    pss_override = bool((etapa9_payload or {}).get("override_aplicado"))
    if pss_override or fonte_pss == "conta_homologada":
        pss = pss_caso
    elif incide_pss is True:
        # Alíquota: a do CONTRACHEQUE do servidor (etapa 9 fonte=contracheque)
        # quando disponível, senão o flat padrão (14%). A etapa 9 já expõe a
        # `aliquota_pct` resolvida pela hierarquia.
        aliq_pss = _to_decimal((etapa9_payload or {}).get("aliquota_pct"))
        if aliq_pss is None or aliq_pss <= 0:
            aliq_pss = calculo_pss.ALIQUOTA_PSS_PADRAO
        pss = _q((base_desconto or Decimal("0")) * aliq_pss / Decimal("100"))
        if fonte_pss == "contracheque":
            obs_descontos.append(
                f"PSS estimado em {aliq_pss}% — alíquota previdenciária do "
                "contracheque do servidor (sem teto p/ RPPS); valor a confirmar."
            )
        else:
            obs_descontos.append(
                f"⚠ PSS estimado pela alíquota padrão ({aliq_pss}%) sobre o "
                "crédito atualizado — a conta de liquidação não foi analisada. "
                "Valor exato a confirmar pelo advogado; estimativa conservadora "
                "(reduz a oferta)."
            )
    elif incide_pss is False:
        pss = Decimal("0.00")
    else:
        pss = None
        obs_descontos.append(
            "PSS a apurar pelo advogado — natureza tributária 'misto'/indeterminada."
        )

    ir_override = bool((etapa10_payload or {}).get("override_aplicado"))
    incide_ir_pay = (etapa10_payload or {}).get("incide_ir")
    natureza_ir = (etapa10_payload or {}).get("natureza_tributaria")
    fonte_meses = (etapa10_payload or {}).get("fonte_meses_competencia")
    if ir_override:
        ir = ir_caso
    elif incide_ir_pay is False:
        ir = Decimal("0.00")
    elif not natureza_ir:
        ir = None
        obs_descontos.append("IR-RRA a apurar — natureza tributária ausente.")
    elif fonte_meses == "fallback_1":
        ir = None
        obs_descontos.append(
            "⚠ IR-RRA a apurar pelo advogado — sem a conta de liquidação não há "
            "número de meses (RRA) confiável; estimar 1 mês inflaria o imposto."
        )
    elif base_desconto is not None:
        try:
            meses_ir = int((etapa10_payload or {}).get("meses_competencia") or 1)
        except (TypeError, ValueError):
            meses_ir = 1
        ir_recalc = calculo_ir.calcular_ir_rra(
            natureza_ir,
            base_desconto,
            meses_ir,
            pss if pss is not None else Decimal("0"),
        )
        if ir_recalc.incide_ir:
            ir = _q(ir_recalc.valor_ir)
        elif ir_recalc.incide_ir is False:
            ir = Decimal("0.00")
        else:
            ir = None
    else:
        ir = ir_caso

    # Líquido = crédito − PSS − IR. PSS/IR são montantes ÚNICOS (estimados/
    # calculados), abatidos IGUAIS nas duas colunas — moeda da conta e moeda
    # atualizada. Só os totais (bruto/líquido) variam pela atualização. Assim as
    # DUAS tabelas FECHAM aritmeticamente: bruto − PSS − IR − sucumb − contr =
    # líquido (antes o líquido da coluna "data do cálculo" era proporcional e a
    # tabela não somava — o PSS estimado vive na moeda atualizada).
    desconto_atual = (pss or Decimal("0")) + (ir or Decimal("0"))
    valor_liquido_final = _q(valor_credor - desconto_atual)
    valor_liquido_atual = (
        _q(valor_credor_atualizado - desconto_atual)
        if valor_credor_atualizado is not None
        else None
    )

    cenario_homologado = Cenario(
        nome="homologado",
        disponivel=True,
        valor_total=_q(valor_oficial or valor_credor_bruto),
        valor_pss=_q(pss) if pss is not None else None,
        valor_ir=_q(ir) if ir is not None else None,
        honorarios_sucumbenciais_pct=None,  # decomposição é absoluta no ofício
        valor_honorarios_sucumbenciais=bloco.valor_sucumbenciais,
        honorarios_contratuais_pct=contr_pct_aplicado,
        valor_honorarios_contratuais=contr_carve,
        valor_liquido=valor_liquido_final,
        valor_liquido_atualizado=valor_liquido_atual,
        atualizacao=bloco.atualizacao,
        observacoes=(
            list(bloco.observacoes)
            + ([contr_obs] if contr_obs else [])
            + obs_descontos
        ),
        principal_corrigido_atualizado=bloco.principal_corrigido_atualizado,
        juros_moratorios_atualizado=bloco.juros_moratorios_atualizado,
        selic_acumulada_atualizada=bloco.selic_acumulada_atualizada,
        valor_total_atualizado=valor_credor_atualizado,
        fonte="oficio",
    )

    # Sentencial — v1 simplificado: convergente se reconciliação ok, senão
    # indisponível. Não tenta recalcular sentencial sobre o líquido do
    # ofício (não temos regime sentencial pra liquido — só pra principal).
    if reconciliacao_status == "conforme":
        cenario_sentencial = Cenario(
            nome="sentencial",
            disponivel=True,
            valor_total=cenario_homologado.valor_total,
            valor_pss=cenario_homologado.valor_pss,
            valor_ir=cenario_homologado.valor_ir,
            honorarios_sucumbenciais_pct=cenario_homologado.honorarios_sucumbenciais_pct,
            valor_honorarios_sucumbenciais=cenario_homologado.valor_honorarios_sucumbenciais,
            honorarios_contratuais_pct=cenario_homologado.honorarios_contratuais_pct,
            valor_honorarios_contratuais=cenario_homologado.valor_honorarios_contratuais,
            valor_liquido=cenario_homologado.valor_liquido,
            valor_liquido_atualizado=cenario_homologado.valor_liquido_atualizado,
            atualizacao=cenario_homologado.atualizacao,
            observacoes=[],
            status_sentencial="convergente",
            principal_corrigido_atualizado=cenario_homologado.principal_corrigido_atualizado,
            juros_moratorios_atualizado=cenario_homologado.juros_moratorios_atualizado,
            selic_acumulada_atualizada=cenario_homologado.selic_acumulada_atualizada,
            valor_total_atualizado=cenario_homologado.valor_total_atualizado,
            fonte="oficio",
        )
    else:
        cenario_sentencial = Cenario(
            nome="sentencial",
            disponivel=False,
            valor_total=None,
            valor_pss=None,
            valor_ir=None,
            honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None,
            honorarios_contratuais_pct=None,
            valor_honorarios_contratuais=None,
            valor_liquido=None,
            observacoes=[
                "Cenário sentencial não recalculado quando ofício é ground "
                "truth — v1 só projeta líquido, sem regime sentencial."
            ],
            status_sentencial="indisponivel",
            fonte="oficio",
        )

    return ResultadoCenarios(
        cenario_homologado=cenario_homologado,
        cenario_sentencial=cenario_sentencial,
        pior_cenario="homologado",
        valor_oferta_base=cenario_homologado.valor_liquido_atualizado
        or cenario_homologado.valor_liquido,
        blocos_oficio=blocos,
        multi_oficio=False,
    )


def _resultado_sem_exequente(
    blocos: list[BlocoOficio],
    observacao_homologado: str,
) -> ResultadoCenarios:
    """Resultado quando o(s) ofício(s) NÃO incluem crédito do exequente.

    Ambos os cenários ficam `disponivel=False` e `valor_oferta_base=None`: a
    oferta do exequente nunca ancora em honorário de terceiro (regra 8 iii).
    `multi_oficio` reflete a contagem de blocos. Usado pelo caminho N=1 quando
    o único ofício é de advogado (`e_credor_exequente=False`).
    """
    cenario_homologado = Cenario(
        nome="homologado",
        disponivel=False,
        valor_total=None,
        valor_pss=None,
        valor_ir=None,
        honorarios_sucumbenciais_pct=None,
        valor_honorarios_sucumbenciais=None,
        honorarios_contratuais_pct=None,
        valor_honorarios_contratuais=None,
        valor_liquido=None,
        observacoes=[observacao_homologado],
        fonte="oficio",
    )
    cenario_sentencial = Cenario(
        nome="sentencial",
        disponivel=False,
        valor_total=None,
        valor_pss=None,
        valor_ir=None,
        honorarios_sucumbenciais_pct=None,
        valor_honorarios_sucumbenciais=None,
        honorarios_contratuais_pct=None,
        valor_honorarios_contratuais=None,
        valor_liquido=None,
        observacoes=[
            "Sentencial indisponível sem crédito de exequente — agregação "
            "de regimes por ofício não definida."
        ],
        status_sentencial="indisponivel",
        fonte="oficio",
    )
    return ResultadoCenarios(
        cenario_homologado=cenario_homologado,
        cenario_sentencial=cenario_sentencial,
        pior_cenario=None,
        valor_oferta_base=None,
        blocos_oficio=blocos,
        multi_oficio=len(blocos) > 1,
    )


def _chave_recebivel(b: BlocoOficio) -> tuple[str, str, date] | None:
    """Identidade do RECEBÍVEL de um bloco do exequente, para F4/F6: dois ofícios
    com a MESMA chave são requisições do MESMO crédito (precatório fracionado),
    não créditos distintos. Exige SINAL POSITIVO: `nome_credor` (normalizado)
    não-nulo + `natureza_requisicao` + `data_base`. `None` (qualquer campo
    ausente) → o bloco é um recebível próprio (singleton) — NUNCA agregado por
    coincidência (anti-FP: dois exequentes anônimos não somam)."""
    nome = credor_advogado._normalizar_nome(b.nome_credor or "") or None
    if nome is None or b.natureza_requisicao is None or b.data_base is None:
        return None
    return (nome, b.natureza_requisicao, b.data_base)


def _particionar_recebiveis(exequentes: list[BlocoOficio]) -> list[list[BlocoOficio]]:
    """Particiona os blocos do exequente em RECEBÍVEIS: blocos com a mesma chave
    (`_chave_recebivel`) são o mesmo crédito; chave `None` vira singleton. Ordem
    determinística (preserva a ordem de chegada do 1º membro de cada grupo)."""
    grupos: dict[tuple[str, str, date], list[BlocoOficio]] = {}
    ordem: list[tuple[str, str, date]] = []
    singletons: list[list[BlocoOficio]] = []
    for b in exequentes:
        k = _chave_recebivel(b)
        if k is None:
            singletons.append([b])
            continue
        if k not in grupos:
            grupos[k] = []
            ordem.append(k)
        grupos[k].append(b)
    return [grupos[k] for k in ordem] + singletons


def _resultado_recebivel_unico(
    grupo: list[BlocoOficio],
    blocos: list[BlocoOficio],
    terceiros: list[BlocoOficio],
    nao_classificados: list[BlocoOficio],
    pss_caso: Decimal | None,
    ir_caso: Decimal | None,
) -> ResultadoCenarios:
    """N requisições do MESMO crédito (recebível-único, F4/F6) agregadas como UMA
    oferta. PSS/IR do caso (etapas 9/10, calculados sobre a base AGREGADA) entram
    UMA vez — NÃO somados por bloco (que os replica para exibição de herdeiros).
    O líquido deriva do BRUTO agregado das requisições."""
    def _soma(vals: list[Decimal | None]) -> Decimal:
        return sum((v for v in vals if v is not None), Decimal("0"))

    pss0 = pss_caso if pss_caso is not None else Decimal("0")
    ir0 = ir_caso if ir_caso is not None else Decimal("0")
    total_db = _soma([(b.valor_oficial_oficio or b.valor_credor) for b in grupo])
    credor_db = _soma([b.valor_credor for b in grupo])
    credor_atu = _soma([b.valor_credor_atualizado for b in grupo])
    # PSS está em moeda da data-base (escala pelo fator agregado); IR já vem em
    # moeda do presente (abatido uma vez, sem re-escalar) — espelha _projetar_bloco.
    fator_agg = (credor_atu / credor_db) if credor_db else Decimal("1")
    valor_liquido = credor_db - pss0 - ir0
    valor_liquido_atualizado = credor_atu - (pss0 * fator_agg) - ir0

    obs = [
        f"{len(grupo)} requisições do MESMO crédito (mesmo credor, natureza e "
        "data-base) agregadas como UM recebível do exequente — precatório "
        "FRACIONADO, não créditos distintos (regra 8 não exige ?agregar aqui). "
        "PSS/IR contados uma vez. Cada requisição mantém seu próprio cronograma."
    ]
    if terceiros:
        obs.append(
            f"{len(terceiros)} ofício(s) de terceiros (advogado) à parte — não entram."
        )
    if nao_classificados:
        obs.append(
            f"{len(nao_classificados)} ofício(s) sem classificação — não entram "
            "até serem marcados via PUT /cases/{id}/documents/{doc_id}/credor."
        )

    cenario_homologado = Cenario(
        nome="homologado", disponivel=True,
        valor_total=_q(total_db),
        valor_pss=_q(pss_caso) if pss_caso is not None else None,
        valor_ir=_q(ir_caso) if ir_caso is not None else None,
        honorarios_sucumbenciais_pct=None, valor_honorarios_sucumbenciais=None,
        honorarios_contratuais_pct=None, valor_honorarios_contratuais=None,
        valor_liquido=_q(valor_liquido),
        valor_liquido_atualizado=_q(valor_liquido_atualizado),
        atualizacao=None, observacoes=obs,
        principal_corrigido_atualizado=None, juros_moratorios_atualizado=None,
        selic_acumulada_atualizada=None, valor_total_atualizado=_q(credor_atu),
        fonte="recebivel_unico_exequente",
    )
    cenario_sentencial = Cenario(
        nome="sentencial", disponivel=False, valor_total=None, valor_pss=None,
        valor_ir=None, honorarios_sucumbenciais_pct=None,
        valor_honorarios_sucumbenciais=None, honorarios_contratuais_pct=None,
        valor_honorarios_contratuais=None, valor_liquido=None,
        observacoes=["Sentencial indisponível em multi-ofício na v1."],
        status_sentencial="indisponivel", fonte="oficio",
    )
    return ResultadoCenarios(
        cenario_homologado=cenario_homologado,
        cenario_sentencial=cenario_sentencial,
        pior_cenario="homologado",
        valor_oferta_base=_q(valor_liquido_atualizado),
        blocos_oficio=blocos,
        multi_oficio=True,
    )


def _resultado_multi_oficio(
    blocos: list[BlocoOficio],
    pss_caso: Decimal | None = None,
    ir_caso: Decimal | None = None,
    agregar: bool = False,
) -> ResultadoCenarios:
    """Cenário multi-ofício (N>1).

    Regra 8 (i) do CLAUDE.md = default lista independente: blocos_oficio
    é sempre exposto e ofícios NÃO são somados. Mesmo dois ofícios do MESMO
    exequente são créditos distintos (precatório vs RPV, naturezas e filas de
    pagamento próprias) — somá-los num único valor implica pagamento único,
    juridicamente inválido.

    Regra 8 (ii) = agregado OPCIONAL "recebível pelo exequente", só quando o
    advogado pede proposta global (`agregar=True`): soma os líquidos dos blocos
    `e_credor_exequente=True`. EXCEÇÃO: um ÚNICO ofício do exequente não é "soma"
    — é a oferta daquele crédito; aí `valor_oferta_base` é populado mesmo sem
    `agregar` (caso CASO: 1 precatório + 1 RPV da advogada).

    Quando nenhum bloco está classificado como exequente, ambos os
    cenários ficam `disponivel=False` — `valor_oferta_base=None`.
    """
    exequentes = [b for b in blocos if b.e_credor_exequente is True]
    terceiros = [b for b in blocos if b.e_credor_exequente is False]
    nao_classificados = [b for b in blocos if b.e_credor_exequente is None]

    if not exequentes:
        # Caminho legado preservado: sem classificação manual, mantém
        # bloqueio observado pelo checklist + observação multi-ofício.
        partes = [
            f"Caso multi-ofício: {len(blocos)} ofícios independentes — "
            "agregação opcional (regra 8 ii) bloqueada porque nenhum "
            "ofício foi marcado como `e_credor_exequente=true`. "
            "Use PUT /cases/{id}/documents/{doc_id}/credor para classificar."
        ]
        cenario_homologado = Cenario(
            nome="homologado",
            disponivel=False,
            valor_total=None,
            valor_pss=None,
            valor_ir=None,
            honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None,
            honorarios_contratuais_pct=None,
            valor_honorarios_contratuais=None,
            valor_liquido=None,
            observacoes=partes,
            fonte="oficio",
        )
        cenario_sentencial = Cenario(
            nome="sentencial",
            disponivel=False,
            valor_total=None,
            valor_pss=None,
            valor_ir=None,
            honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None,
            honorarios_contratuais_pct=None,
            valor_honorarios_contratuais=None,
            valor_liquido=None,
            observacoes=[
                "Sentencial indisponível em multi-ofício na v1 — agregação "
                "de regimes por ofício não definida."
            ],
            status_sentencial="indisponivel",
            fonte="oficio",
        )
        return ResultadoCenarios(
            cenario_homologado=cenario_homologado,
            cenario_sentencial=cenario_sentencial,
            pior_cenario=None,
            valor_oferta_base=None,
            blocos_oficio=blocos,
            multi_oficio=True,
        )

    # Regra 8 (i): 2+ ofícios do exequente são créditos DISTINTOS — não somar
    # por default. Só agrega sob pedido (`agregar=True`, regra 8 ii). Um único
    # ofício do exequente NÃO é soma (cai na agregação abaixo, valor_oferta_base
    # = aquele crédito) — preserva CASO (1 precatório + RPV advogada).

    # F4/F6: 2+ requisições do MESMO crédito (mesmo credor + natureza + data_base)
    # são UM crédito FRACIONADO, não créditos distintos — agregam por DEFAULT (sem
    # exigir ?agregar). A regra 8 (i) "créditos distintos não somam" passa a operar
    # sobre RECEBÍVEIS, não ofícios soltos: só 2+ recebíveis DISTINTOS bloqueiam.
    # Caso CASO: precatório 93.192,10 expedido em 75.182,34 + 18.009,76.
    recebiveis = _particionar_recebiveis(exequentes)
    # UM único recebível (mesmo crédito fracionado) → conta PSS/IR uma vez,
    # INDEPENDENTE de `agregar`: pedir o agregado global de um crédito que já é
    # único não pode dobrar o desconto (M1) — a agregação per-bloco (abaixo) só
    # vale para recebíveis DISTINTOS (herdeiros).
    if len(exequentes) >= 2 and len(recebiveis) == 1:
        return _resultado_recebivel_unico(
            recebiveis[0], blocos, terceiros, nao_classificados, pss_caso, ir_caso
        )

    # Ofício PRINCIPAL: quando há exatamente um ofício do exequente com
    # natureza_requisicao="principal" (e mais de um ofício do exequente), a
    # análise/oferta roda sobre ELE e os demais (multa/astreintes, honorários)
    # ficam apenas listados (caso CASO: principal pp244 vira a oferta; multa
    # pp245 e honorários pp246 só aparecem). Não é "soma" — respeita a regra 8.
    principais = [b for b in exequentes if b.natureza_requisicao == "principal"]
    if len(exequentes) >= 2 and not agregar and len(principais) == 1:
        principal = principais[0]
        outros = [b for b in blocos if b is not principal]
        def _rotulo(b: BlocoOficio) -> str:
            nat = b.natureza_requisicao or ("honorários" if b.e_credor_exequente is False else "outro")
            val = b.valor_liquido_atualizado or b.valor_credor_atualizado
            return f"{nat}=R$ {val}"
        obs = [
            "Análise e oferta sobre o ofício PRINCIPAL do exequente "
            f"(natureza=principal, líquido atualizado R$ "
            f"{principal.valor_liquido_atualizado or principal.valor_credor_atualizado}).",
        ]
        if outros:
            obs.append(
                "Outros ofícios do caso (listados à parte, NÃO somados — regra 8): "
                + "; ".join(_rotulo(b) for b in outros) + "."
            )
        if principal.ancora_sem_citacao:
            obs.append(
                "⚠ Âncora sem citação verificável — o valor do ofício principal "
                "que sustenta a oferta teve a citação ANULADA (regra 1); confirme "
                "no PDF/requisitório."
            )
        cenario_homologado = Cenario(
            nome="homologado", disponivel=True,
            valor_total=_q(principal.valor_oficial_oficio or principal.valor_credor),
            valor_pss=_q(principal.valor_pss) if principal.valor_pss is not None else None,
            valor_ir=_q(principal.valor_ir) if principal.valor_ir is not None else None,
            honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=principal.valor_sucumbenciais,
            honorarios_contratuais_pct=None,
            valor_honorarios_contratuais=principal.valor_contratuais,
            valor_liquido=_q(principal.valor_liquido if principal.valor_liquido is not None else principal.valor_credor),
            valor_liquido_atualizado=_q(principal.valor_liquido_atualizado if principal.valor_liquido_atualizado is not None else principal.valor_credor_atualizado),
            atualizacao=principal.atualizacao,
            observacoes=obs,
            principal_corrigido_atualizado=principal.principal_corrigido_atualizado,
            juros_moratorios_atualizado=principal.juros_moratorios_atualizado,
            selic_acumulada_atualizada=principal.selic_acumulada_atualizada,
            valor_total_atualizado=principal.valor_credor_atualizado,
            fonte="oficio_principal",
        )
        cenario_sentencial = Cenario(
            nome="sentencial", disponivel=False, valor_total=None, valor_pss=None,
            valor_ir=None, honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None, honorarios_contratuais_pct=None,
            valor_honorarios_contratuais=None, valor_liquido=None,
            observacoes=["Sentencial indisponível em multi-ofício na v1."],
            status_sentencial="indisponivel", fonte="oficio",
        )
        return ResultadoCenarios(
            cenario_homologado=cenario_homologado,
            cenario_sentencial=cenario_sentencial,
            pior_cenario="homologado",
            valor_oferta_base=_q(
                principal.valor_liquido_atualizado or principal.valor_credor_atualizado
            ),
            blocos_oficio=blocos,
            multi_oficio=True,
        )

    if len(recebiveis) >= 2 and not agregar:
        refs = "; ".join(
            f"R$ {b.valor_liquido_atualizado or b.valor_credor_atualizado}"
            for b in exequentes
            if (b.valor_liquido_atualizado or b.valor_credor_atualizado) is not None
        )
        partes = [
            f"{len(exequentes)} ofícios do EXEQUENTE são créditos DISTINTOS "
            "(precatório/RPV, naturezas e filas de pagamento próprias) — NÃO "
            "somados por padrão (regra 8 i). Cada um está em blocos_oficio com "
            f"seu valor atualizado ({refs}). Para uma proposta global única, "
            "use ?agregar=true (regra 8 ii)."
        ]
        if terceiros:
            partes.append(
                f"{len(terceiros)} ofício(s) de terceiros (advogado) listados à "
                "parte — não entram na oferta do exequente."
            )
        cenario_homologado = Cenario(
            nome="homologado", disponivel=False, valor_total=None, valor_pss=None,
            valor_ir=None, honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None, honorarios_contratuais_pct=None,
            valor_honorarios_contratuais=None, valor_liquido=None,
            observacoes=partes, fonte="oficio",
        )
        cenario_sentencial = Cenario(
            nome="sentencial", disponivel=False, valor_total=None, valor_pss=None,
            valor_ir=None, honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None, honorarios_contratuais_pct=None,
            valor_honorarios_contratuais=None, valor_liquido=None,
            observacoes=["Sentencial indisponível em multi-ofício na v1."],
            status_sentencial="indisponivel", fonte="oficio",
        )
        return ResultadoCenarios(
            cenario_homologado=cenario_homologado,
            cenario_sentencial=cenario_sentencial,
            pior_cenario=None,
            valor_oferta_base=None,
            blocos_oficio=blocos,
            multi_oficio=True,
        )

    # Agregado "recebível pelo exequente" — soma de líquidos dos exequentes.
    # (1 exequente = oferta daquele crédito; 2+ só chega aqui com `agregar=True`.)
    def _soma(vals: list[Decimal | None]) -> Decimal:
        total = Decimal("0")
        for v in vals:
            if v is not None:
                total += v
        return total

    valor_total_agg = _soma([b.valor_credor for b in exequentes])
    valor_pss_agg = _soma([b.valor_pss for b in exequentes])
    valor_ir_agg = _soma([b.valor_ir for b in exequentes])
    valor_liquido_agg = _soma([b.valor_liquido for b in exequentes])
    valor_liquido_atualizado_agg = _soma(
        [b.valor_liquido_atualizado for b in exequentes]
    )
    valor_credor_atualizado_agg = _soma(
        [b.valor_credor_atualizado for b in exequentes]
    )

    if len(exequentes) == 1:
        observacoes_agg = [
            "Oferta do único ofício do exequente (os demais ofícios, de "
            "terceiros, ficam à parte)."
        ]
    else:
        observacoes_agg = [
            f"Agregado 'recebível pelo exequente' A PEDIDO (regra 8 ii): "
            f"{len(exequentes)} ofícios do exequente somados. Atenção: são "
            "créditos distintos, pagos em cronogramas próprios — a soma é uma "
            "proposta global, não um pagamento único."
        ]
    if terceiros:
        observacoes_agg.append(
            f"{len(terceiros)} ofício(s) de terceiros (advogado sucumbenciais) "
            "listados separado em blocos_oficio — não entram na oferta."
        )
    if nao_classificados:
        observacoes_agg.append(
            f"{len(nao_classificados)} ofício(s) sem classificação "
            "(e_credor_exequente=null) — não entram na oferta até serem "
            "marcados via PUT /cases/{id}/documents/{doc_id}/credor."
        )

    cenario_homologado = Cenario(
        nome="homologado",
        disponivel=True,
        valor_total=_q(valor_total_agg),
        valor_pss=_q(valor_pss_agg) if pss_caso is not None else None,
        valor_ir=_q(valor_ir_agg) if ir_caso is not None else None,
        honorarios_sucumbenciais_pct=None,
        valor_honorarios_sucumbenciais=None,
        honorarios_contratuais_pct=None,
        valor_honorarios_contratuais=None,
        valor_liquido=_q(valor_liquido_agg),
        valor_liquido_atualizado=_q(valor_liquido_atualizado_agg),
        atualizacao=None,  # composto por N ofícios — sem atualização única
        observacoes=observacoes_agg,
        principal_corrigido_atualizado=None,
        juros_moratorios_atualizado=None,
        selic_acumulada_atualizada=None,
        valor_total_atualizado=_q(valor_credor_atualizado_agg),
        fonte="agregado_exequente",
    )
    cenario_sentencial = Cenario(
        nome="sentencial",
        disponivel=False,
        valor_total=None,
        valor_pss=None,
        valor_ir=None,
        honorarios_sucumbenciais_pct=None,
        valor_honorarios_sucumbenciais=None,
        honorarios_contratuais_pct=None,
        valor_honorarios_contratuais=None,
        valor_liquido=None,
        observacoes=[
            "Sentencial indisponível em multi-ofício na v1 — agregação "
            "de regimes por ofício não definida."
        ],
        status_sentencial="indisponivel",
        fonte="oficio",
    )
    return ResultadoCenarios(
        cenario_homologado=cenario_homologado,
        cenario_sentencial=cenario_sentencial,
        pior_cenario="homologado",
        valor_oferta_base=_q(valor_liquido_atualizado_agg),
        blocos_oficio=blocos,
        multi_oficio=True,
    )


def construir_cenarios(
    etapa8_response: dict | None,
    etapa9_payload: dict | None,
    etapa10_payload: dict | None,
    reconciliacao_status: str | None,
    regime_etapa7: list[dict] | None = None,
    natureza_tributaria: str | None = None,
    data_alvo: date | None = None,
    honorarios_contratuais_pct: Decimal | None = None,
    data_apresentacao: date | None = None,
    oficios_ground_truth: list[OficioGroundTruthDict] | None = None,
    agregar_exequente: bool = False,
    esfera: str | None = None,
    data_expedicao: date | None = None,
    valor_superpreferencia: Decimal | None = None,
    data_pagamento_superpreferencia: date | None = None,
) -> ResultadoCenarios:
    """Constrói cenários a partir dos payloads das etapas 8/9/10 e do
    status da reconciliação.

    Quando `reconciliacao_status == "divergente"` e `regime_etapa7` está
    disponível, tenta recalcular o principal aplicando o regime
    sentencial sobre o `valor_originario` da conta (v2 — séries
    versionadas de IPCA-E/SELIC/INPC). PSS/IR do cenário sentencial são
    refeitos sobre o novo principal usando `natureza_tributaria`. Se o
    recalc falhar (índice não suportado, marco inválido), cai para
    `sob_revisao` declarativo.

    `data_alvo` controla a atualização ao presente: o valor_liquido de cada
    cenário, calculado em moeda da `data_calculo` da conta, é atualizado
    para a moeda de `data_alvo` aplicando SELIC (regime padrão pós-EC 113).
    Default = `date.today()`. O `valor_oferta_base` usa o atualizado quando
    disponível; fallback para o líquido em moeda da conta.

    Não chama o DB — recebe tudo pronto pelo caller (api.cases). Mantém
    a função pura e testável.
    """
    if data_alvo is None:
        data_alvo = date.today()

    # Caminho "ofício como ground truth" — quando há ≥1 ofício elegível
    # (`valor_credor` + uma data de ancoragem: `data_oficio` OU `data_base`),
    # parte do líquido do ofício e projeta. Bypassa o cálculo determinístico de
    # descontos (PSS/IR/sucumb/contr são exibidos como decomposição informativa,
    # não recalculados). Cobre o cenário típico de trabalhista pré-precatório,
    # onde o ofício consolida o regime IPCA-E + Lei 9.494/97 e o pipeline só
    # precisa projetar dali — E o eproc federal (TRF), cujo requisitório
    # eletrônico traz só a "Data Base" (sem data de expedição): aceitar
    # `data_base` como fallback evita que a oferta caia numa conta antiga.
    #
    # Multi-ofício: quando ≥2 blocos elegíveis, agregação é proibida (regra
    # 8 do CLAUDE.md) — `_construir_cenarios_oficio` devolve cenários
    # `disponivel=False` + `blocos_oficio` listando cada ofício individual.
    oficios_elegiveis = [
        o for o in (oficios_ground_truth or [])
        if o.get("valor_credor") is not None
        and (o.get("data_oficio") is not None or o.get("data_base") is not None)
    ]
    # Fallback de âncora na CONTA (padrão TJES/planilha do tribunal): quando há
    # ≥1 ofício de TERCEIRO (advogado, `e_credor_exequente is False`) e NENHUM
    # classificado como exequente (`is True`), o requisitório do PRINCIPAL não
    # virou ofício — mas seu valor vive na conta homologada (etapa 8). Em vez de
    # dead-endar a oferta (`_resultado_sem_exequente`/`_resultado_multi_oficio`
    # sem exequente), ancora o principal do exequente na conta e lista o(s)
    # ofício(s) não-ancorado(s) à parte (regra 8 i: honorário não entra na oferta).
    # Caso CASO (TJES Juizado): precatório 62/2024 (líquido ~R$37.401,18 na
    # planilha homologada) + RPV honorário R$603,55 do advogado — o único ofício
    # extraído era o honorário. Cobre também a lista MISTA (honorário `False` +
    # peça `None` não-classificada): a presença de um terceiro confirmado + nenhum
    # exequente ainda justifica ancorar na conta. NÃO dispara quando todos os
    # ofícios são `None` (nenhum terceiro confirmado): aí o próprio ofício é a
    # âncora provável do exequente (CASO/CASO). Só dispara com conta POSITIVA
    # utilizável; sem conta (ou conta ≤ 0), mantém o bloqueio (regra 8 iii, caso
    # CASO: principal perdido no slicing e sem conta de respaldo).
    tem_terceiro = any(
        o.get("e_credor_exequente") is False for o in oficios_elegiveis
    )
    sem_exequente = not any(
        o.get("e_credor_exequente") is True for o in oficios_elegiveis
    )
    # Ofícios não-ancorados (terceiro `False` + não-classificado `None`) — listados
    # à parte como informativos; nunca somados à oferta (regra 8 i).
    oficios_terceiro = [
        o for o in oficios_elegiveis if o.get("e_credor_exequente") is not True
    ]
    _conta_vt = _extrair_campo(etapa8_response, "valor_total")
    _conta_vbr = _extrair_campo(etapa8_response, "valor_bruto_reclamante")
    # Exige conta POSITIVA — uma conta degenerada (valor 0/negativo) ancoraria uma
    # oferta R$0/negativa com checklist limpo, mascarando o crédito de terceiro.
    tem_conta_exequente = (_conta_vt is not None and _conta_vt > 0) or (
        _conta_vbr is not None and _conta_vbr > 0
    )
    ancora_conta_com_terceiros = (
        bool(oficios_elegiveis) and tem_terceiro and sem_exequente and tem_conta_exequente
    )

    if oficios_elegiveis and not ancora_conta_com_terceiros:
        # Total da conta (etapa 8) — referência p/ detectar requisitório eproc
        # já-líquido (valor_credor ≈ conta × (1−pct) → não carvear de novo).
        conta_total_ref = _extrair_campo(etapa8_response, "valor_total")
        return _construir_cenarios_oficio(
            oficios=oficios_elegiveis,
            etapa9_payload=etapa9_payload,
            etapa10_payload=etapa10_payload,
            reconciliacao_status=reconciliacao_status,
            data_alvo=data_alvo,
            data_apresentacao=data_apresentacao,
            contratuais_pct=honorarios_contratuais_pct,
            agregar_exequente=agregar_exequente,
            conta_total_ref=conta_total_ref,
        )
    # else: sem ofícios elegíveis OU (terceiro(s) + conta disponível, sem
    # exequente) → segue para o caminho da CONTA abaixo. No 2º caso
    # (`ancora_conta_com_terceiros`), os blocos não-ancorados são anexados como
    # informativos ao final.
    if ancora_conta_com_terceiros:
        # O `honorarios_contratuais_pct` do caso vem do ÚNICO ofício presente —
        # que aqui é de terceiro (advogado). Esse % é o destaque contratual DO
        # ADVOGADO, não do principal do exequente: carveá-lo da conta encolheria
        # a oferta com base num documento que a conta não comporta. Neutraliza o
        # carve nesse path; o advogado revisa contratuais à parte (observação).
        honorarios_contratuais_pct = None

    data_calculo = _parse_data(
        (etapa8_response or {}).get("data_calculo", {}).get("valor")
        if isinstance(etapa8_response, dict)
        else None
    )

    # Cenário homologado — a conta da etapa 8 é a fonte primária.
    #
    # Crédito-base do CREDOR. Em conta trabalhista (Súmula 368 TST) o campo
    # `valor_total` pode ter capturado "Total Devido pelo Reclamado", que SOMA a
    # cota patronal ("CONTRIBUIÇÃO SOCIAL SOBRE SALÁRIOS DEVIDOS" — INSS do
    # empregador, NÃO é crédito do credor) e infla a oferta. O campo
    # `valor_bruto_reclamante` (schema v5+) isola o "Bruto Devido ao Reclamante",
    # a base correta. Prefere-o quando presente; caso contrário usa `valor_total`
    # (Projef/SICAR, cujo total já é o crédito do credor — sem patronal).
    # Caso CASO: 69.776,95 (c/ patronal) → 57.894,48 (bruto reclamante).
    valor_total_conta = _extrair_campo(etapa8_response, "valor_total")
    valor_bruto_reclamante = _extrair_campo(etapa8_response, "valor_bruto_reclamante")
    usou_bruto_reclamante = (
        valor_bruto_reclamante is not None
        and valor_bruto_reclamante != valor_total_conta
    )
    valor_total = (
        valor_bruto_reclamante
        if valor_bruto_reclamante is not None
        else valor_total_conta
    )
    principal_corrigido_conta = _extrair_campo(
        etapa8_response, "valor_principal_corrigido"
    )
    juros_conta = _extrair_campo(etapa8_response, "valor_juros")
    selic_inicial = _extrair_campo(etapa8_response, "valor_selic") or Decimal("0")

    pss = (
        _to_decimal(etapa9_payload.get("valor_pss"))
        if etapa9_payload
        else None
    )
    ir = (
        _to_decimal(etapa10_payload.get("valor_ir"))
        if etapa10_payload
        else None
    )
    honor_pct = _extrair_campo(etapa8_response, "honorarios_sucumbenciais_pct")
    honor_valor = None
    if valor_total is not None and honor_pct is not None:
        honor_valor = _q(valor_total * honor_pct / Decimal("100"))

    # Honorários contratuais (vêm do ofício, não da conta). Quando o credor
    # tem destaque contratual (ex.: 30% pro advogado RONALDO no CASO),
    # esses % são abatidos do líquido — só o saldo do credor entra na oferta.
    contr_valor = None
    if valor_total is not None and honorarios_contratuais_pct is not None:
        contr_valor = _q(
            valor_total * honorarios_contratuais_pct / Decimal("100")
        )

    observacoes_homologado: list[str] = []
    if usou_bruto_reclamante:
        observacoes_homologado.append(
            "Crédito ancorado no 'Bruto Devido ao Reclamante' (Súmula 368 TST), "
            "não no 'Total Devido pelo Reclamado' — exclui a cota patronal "
            "(CONTRIBUIÇÃO SOCIAL SOBRE SALÁRIOS), que não é crédito do credor."
        )
    # (Observações de PSS/IR "a apurar" ficam APÓS o recalc de metodologia —
    # keyadas no valor FINAL, não no pré-recalc do payload; ver abaixo.)
    if honor_pct is None:
        observacoes_homologado.append(
            "Honorários sucumbenciais não destacados na conta — não descontados do líquido."
        )
    if honorarios_contratuais_pct is None:
        observacoes_homologado.append(
            "Honorários contratuais não declarados no ofício — não descontados do líquido."
        )
    if ancora_conta_com_terceiros:
        nomes_terceiro = ", ".join(
            (o.get("nome_credor") or "não identificado") for o in oficios_terceiro
        )
        observacoes_homologado.insert(
            0,
            "Principal do exequente ancorado na CONTA homologada (etapa 8): o "
            "requisitório do principal não foi extraído como ofício próprio "
            "(só a capa de encaminhamento / planilha do tribunal). O(s) ofício(s) "
            f"não-ancorado(s) ({nomes_terceiro} — honorário de terceiro e/ou peça "
            "não-classificada) está(ão) listado(s) à parte em blocos_oficio e NÃO "
            "entra(m) na oferta (regra 8 i). Honorários contratuais (se houver) "
            "são do advogado, não descontados do principal — revisar à parte.",
        )

    liquido_homologado: Decimal | None = None
    if valor_total is not None:
        liquido_homologado = valor_total
        for desconto in (pss, ir, honor_valor, contr_valor):
            if desconto is not None:
                liquido_homologado = liquido_homologado - desconto
        liquido_homologado = _q(liquido_homologado)

    # Atualização segregada (modelo Projef Web). Base do overlay SELIC:
    # `valor_principal_corrigido` quando extraído; fallback para `valor_total`
    # (cobre o caso comum onde a conta não destaca principal/juros).
    base_principal = principal_corrigido_conta or valor_total or Decimal("0")
    juros_atualizar = juros_conta or Decimal("0")

    # Superpreferência (idoso 80+/doença grave/PcD, RCL/EC 114): pagamento
    # BRUTO antecipado, abatido NA DATA em que ocorreu — não no final sobre o
    # valor cheio. Corrige o saldo até a data do pagamento (perna 1), subtrai
    # o valor PROPORCIONALMENTE dos 3 componentes segregados (nenhum é
    # blindado — não há regra jurídica que priorize principal/juros/SELIC), e
    # segue corrigindo o restante até data_alvo (perna 2). PSS/IR/honorários
    # abaixo partem de `seg`, então herdam automaticamente o saldo já
    # reduzido — não precisam de nenhum ajuste próprio.
    valor_corrigido_pre_superpreferencia: Decimal | None = None
    superpreferencia_detalhe: dict | None = None
    if (
        valor_superpreferencia is not None
        and data_pagamento_superpreferencia is not None
        and data_calculo is not None
    ):
        leg1 = _atualizar_segregado(
            base_principal,
            juros_atualizar,
            selic_inicial,
            data_calculo,
            data_pagamento_superpreferencia,
            data_apresentacao=data_apresentacao,
            esfera=esfera,
            data_expedicao=data_expedicao,
        )
        valor_corrigido_pre_superpreferencia = leg1.valor_total_atualizado
        if leg1.valor_total_atualizado > 0:
            fator_restante = max(
                Decimal("0"),
                (leg1.valor_total_atualizado - valor_superpreferencia)
                / leg1.valor_total_atualizado,
            )
        else:
            fator_restante = Decimal("0")
        # Valores PLENOS (não quantizados) que alimentam a perna 2 — evita
        # arredondar antes de continuar corrigindo. `superpreferencia_detalhe`
        # guarda a memória de cálculo (estilo pss_detalhe/ir_detalhe): quanto
        # cada componente tinha ANTES, quanto foi abatido e quanto sobrou —
        # consumida pelo memorial para render a "fase" do abatimento.
        principal_pos = leg1.principal_corrigido_atualizado * fator_restante
        juros_pos = leg1.juros_moratorios_atualizado * fator_restante
        selic_pos = leg1.selic_acumulada_atualizada * fator_restante
        superpreferencia_detalhe = {
            "data_pagamento": data_pagamento_superpreferencia.isoformat(),
            # Quantos componentes (fases) a perna 1 gerou — o memorial usa
            # isso pra saber ONDE na lista concatenada inserir o bloco do
            # abatimento (o `fim` de fase não é confiável como marcador: a
            # varredura mês a mês de `_atualizar_segregado` fecha segmentos
            # em fronteira de MÊS, não no dia exato do pagamento).
            "n_componentes_pre": len(leg1.atualizacao.componentes),
            "principal_pre": str(_q(leg1.principal_corrigido_atualizado)),
            "juros_pre": str(_q(leg1.juros_moratorios_atualizado)),
            "selic_pre": str(_q(leg1.selic_acumulada_atualizada)),
            "total_pre": str(leg1.valor_total_atualizado),
            "principal_abatido": str(_q(leg1.principal_corrigido_atualizado - principal_pos)),
            "juros_abatido": str(_q(leg1.juros_moratorios_atualizado - juros_pos)),
            "selic_abatido": str(_q(leg1.selic_acumulada_atualizada - selic_pos)),
            "valor_abatido": str(_q(valor_superpreferencia)),
            "principal_pos": str(_q(principal_pos)),
            "juros_pos": str(_q(juros_pos)),
            "selic_pos": str(_q(selic_pos)),
            # Fração do crédito que sobra após o abatimento — mesma base usada
            # pelo CEPREC para ratear o NM do IR-RRA entre as parcelas pagas
            # (evento 39 do 2005527-85.2025.8.13.0000/TJMG: 34 meses viram
            # 17,4 e 16,6, proporcionais ao valor de cada parcela). Aplicada
            # mais abaixo, onde `meses_competencia` é lido.
            "fracao_remanescente": str(
                fator_restante.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            ),
        }
        leg2 = _atualizar_segregado(
            principal_pos,
            juros_pos,
            selic_pos,
            data_pagamento_superpreferencia,
            data_alvo,
            data_apresentacao=data_apresentacao,
            esfera=esfera,
            data_expedicao=data_expedicao,
        )
        seg = ResultadoSegregado(
            principal_corrigido_atualizado=leg2.principal_corrigido_atualizado,
            juros_moratorios_atualizado=leg2.juros_moratorios_atualizado,
            selic_acumulada_atualizada=leg2.selic_acumulada_atualizada,
            atualizacao=replace(
                leg2.atualizacao,
                data_origem=leg1.atualizacao.data_origem,
                componentes=leg1.atualizacao.componentes + leg2.atualizacao.componentes,
            ),
        )
    else:
        seg = _atualizar_segregado(
            base_principal,
            juros_atualizar,
            selic_inicial,
            data_calculo,
            data_alvo,
            data_apresentacao=data_apresentacao,
            esfera=esfera,
            data_expedicao=data_expedicao,
        )

    # Quando a atualização ao presente está disponível e temos natureza +
    # meses de competência, recalcula PSS/IR/honorários sobre os números
    # atualizados (espelha planilha do advogado / metodologia USS):
    # 1. honor_contratuais = pct × valor_total_atualizado (não sobre conta original).
    # 2. PSS = ALIQUOTA_PSS_PADRAO (14% default) × (principal_atualizado +
    #    selic_atualizado) × (1 - contr_pct). Inclui SELIC e exclui destaque
    #    do advogado. (Só estima quando não veio da conta nem de override.)
    # 3. IR-RRA tem base = (principal + selic) × (1 - contr_pct) - PSS.
    #    Exclui juros moratórios e segue art. 12-A §4º (deduz PSS).
    # Esses 3 ajustes só rodam quando inputs suficientes; caso contrário cai
    # no caminho legado (PSS/IR da etapa 9/10 + honorários sobre valor_total).
    # Override do revisor (FieldReview na etapa 8) tem precedência: quando
    # etapa9_payload/etapa10_payload sinalizam `override_aplicado=True`, o
    # recalc de PSS/IR é pulado e o valor do payload sai como final — a
    # decisão jurídica do revisor não é sobrescrita pela metodologia.
    pss_recalc: Decimal | None = None
    ir_recalc: Decimal | None = None
    contr_recalc: Decimal | None = None
    honor_recalc: Decimal | None = None
    # Memória de cálculo dos descontos estimados (→ Cenario.pss_detalhe/
    # ir_detalhe): só preenchida quando o recalc de metodologia roda.
    pss_detalhe: dict | None = None
    ir_detalhe: dict | None = None
    # Total atualizado EXIBIDO. Por padrão = o do segregado (principal+juros+SELIC
    # já corrigidos). No caminho da metodologia vira o PROPORCIONAL — a MESMA base
    # de que o líquido é derivado (valor_total escalado pelo crescimento dos
    # componentes). Sem isso, quando a conta tem total ≠ principal+juros+SELIC, a
    # cascata (total − PSS − IR − honorários) não fecha e o líquido saía MAIOR que
    # o total exibido.
    total_atualizado_proporcional: Decimal = seg.valor_total_atualizado
    pode_recalc_metodologia = (
        valor_total is not None
        and seg.atualizacao.status
        not in {"sem_data_origem", "cobertura_insuficiente", "sem_valor"}
    )
    pss_override = bool((etapa9_payload or {}).get("override_aplicado"))
    ir_override = bool((etapa10_payload or {}).get("override_aplicado"))

    if pode_recalc_metodologia:
        total_atualizado = seg.valor_total_atualizado
        # Preserva proporção quando principal+juros+selic ≠ valor_total
        # (contas com 'outros descontos' ou destaque).
        base_total_inicial = base_principal + juros_atualizar + selic_inicial
        if base_total_inicial > 0:
            razao = total_atualizado / base_total_inicial
            total_atualizado_proporcional = (valor_total * razao).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            total_atualizado_proporcional = total_atualizado

        # Base do PSS/IR é remuneratória: exclui os juros de mora (natureza
        # indenizatória — não compõem a contribuição; ver calculo_pss). A SELIC
        # já acumulada entra INTEIRA na base (espelha o gabarito Projef: "Valor
        # Final sem Juros de Mora" = principal + SELIC), sem fracionar.
        selic_base_pss_ir = seg.selic_acumulada_atualizada

        # Sucumbenciais sobre total atualizado.
        if honor_pct is not None:
            honor_recalc = _q(
                total_atualizado_proporcional * honor_pct / Decimal("100")
            )

        # Contratuais sobre total atualizado (espelha planilha).
        contr_pct_frac = (
            honorarios_contratuais_pct / Decimal("100")
            if honorarios_contratuais_pct is not None
            else Decimal("0")
        )
        if honorarios_contratuais_pct is not None:
            contr_recalc = _q(total_atualizado_proporcional * contr_pct_frac)

        # PSS sobre principal_atualizado + SELIC, líquido do destaque
        # contratual. Só recalcula se natureza disponível — caso contrário
        # cai no PSS da etapa 9 (que respeita override do FieldReview).
        # Quando há override (`pss_override`), pula o recalc pra preservar
        # a decisão jurídica do revisor.
        if natureza_tributaria and not pss_override:
            base_pss_metodologia = (
                seg.principal_corrigido_atualizado + selic_base_pss_ir
            ) * (Decimal("1") - contr_pct_frac)
            # Alíquota: a do contracheque (etapa 9 fonte=contracheque) quando
            # disponível; senão o flat padrão (14%). A etapa 9 expõe a
            # `aliquota_pct` resolvida pela hierarquia.
            aliq_pss_conta = _to_decimal((etapa9_payload or {}).get("aliquota_pct"))
            if aliq_pss_conta is None or aliq_pss_conta <= 0:
                aliq_pss_conta = calculo_pss.ALIQUOTA_PSS_PADRAO
            try:
                pss_calc = calculo_pss.calcular_pss(
                    natureza_tributaria, base_pss_metodologia, aliq_pss_conta
                )
                if pss_calc.incide:
                    pss_recalc = _q(pss_calc.valor_pss)
                    # Memória p/ o memorial (estilo gabarito): base decomposta,
                    # alíquota e valor — display, nada é recalculado com isso.
                    pss_detalhe = {
                        "principal_atualizado": str(
                            _q(seg.principal_corrigido_atualizado)
                        ),
                        "selic_atualizada": str(_q(selic_base_pss_ir)),
                        "contratuais_pct": _decimal_str(honorarios_contratuais_pct),
                        "base": str(_q(base_pss_metodologia)),
                        "aliquota_pct": str(aliq_pss_conta),
                        "valor": str(pss_recalc),
                    }
                elif pss_calc.incide is False:
                    pss_recalc = Decimal("0.00")
                # incide is None → misto/ausente, mantém None
            except Exception:
                pss_recalc = None

        # IR-RRA com base (principal + selic) líquida do destaque, sem
        # juros, deduzindo o PSS final (override ou recalc) — art. 12-A §4º.
        # Quando há override de IR (`ir_override`), pula o recalc.
        if natureza_tributaria and not ir_override:
            meses_str = (
                (etapa10_payload or {}).get("meses_competencia")
                if etapa10_payload
                else None
            )
            try:
                # str() antes do Decimal: evita o ruído de precisão binária de
                # Decimal(float) caso o payload traga um float (ex.: 33.0).
                meses = (
                    Decimal(str(meses_str)) if meses_str is not None else Decimal("1")
                )
            except (InvalidOperation, TypeError, ValueError):
                meses = Decimal("1")
            if meses < 1:
                meses = Decimal("1")
            # Quitação parcial (superpreferência): o NM total é declarado para
            # o crédito INTEIRO, mas o saldo que chega até aqui já é só a
            # fração que sobrou do abatimento. O CEPREC rateia o NM na mesma
            # proporção — 34 meses viram 17,4 (parcela paga) e 16,6 (saldo) no
            # evento 39 do 2005527-85.2025.8.13.0000/TJMG — porque isso
            # preserva a base mensal do RRA (e portanto a faixa/alíquota)
            # idêntica à de um pagamento único; aplicar o NM cheio sobre um
            # saldo parcial dilui demais a base e subestima o imposto. O
            # arredondamento a 1 casa decimal espelha o que o CEPREC exibe.
            meses_total = meses
            if superpreferencia_detalhe is not None:
                fracao = Decimal(superpreferencia_detalhe["fracao_remanescente"])
                # Sem piso de 1 mês aqui: uma parcela pequena pode ratear pra
                # bem menos que 1 mês (ex.: 0,3) e é isso mesmo que preserva a
                # base mensal correta. `calcular_ir_rra` tem seu próprio piso
                # (0,1) só pra evitar divisão por zero no caso degenerado.
                meses = (meses_total * fracao).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
                superpreferencia_detalhe["meses_competencia_total"] = str(meses_total)
                superpreferencia_detalhe["meses_competencia_rateado"] = str(meses)
            base_ir_metodologia = (
                seg.principal_corrigido_atualizado + selic_base_pss_ir
            ) * (Decimal("1") - contr_pct_frac)
            # PSS pra dedução: usa o final (override etapa 9 OU recalc).
            pss_para_deduzir = (
                pss if pss_override and pss is not None
                else (pss_recalc if pss_recalc is not None else Decimal("0"))
            )
            try:
                ir_calc = calculo_ir.calcular_ir_rra(
                    natureza_tributaria,
                    base_ir_metodologia,
                    meses,
                    pss_deduzir=pss_para_deduzir,
                )
                if ir_calc.incide_ir:
                    ir_recalc = _q(ir_calc.valor_ir)
                    # Memória completa do RRA (base → PSS deduzido → base mensal
                    # → faixa/parcela dedutível → valor) p/ o memorial.
                    ir_detalhe = ir_calc.to_dict()
                elif ir_calc.incide_ir is False:
                    ir_recalc = Decimal("0.00")
            except Exception:
                ir_recalc = None

    # Decide quais valores finais usar no cenário (recalc preferido se
    # disponível; caso contrário caminho legado).
    pss_final = pss_recalc if pss_recalc is not None else pss
    ir_final = ir_recalc if ir_recalc is not None else ir
    contr_final = contr_recalc if contr_recalc is not None else contr_valor
    honor_final = honor_recalc if honor_recalc is not None else honor_valor

    # Observações de PSS/IR "a apurar" são keyadas no valor FINAL (pós-recalc de
    # metodologia), não no pré-recalc do payload: o IR estimável chega sem
    # `valor_ir` (só `meses_competencia`) e é recalculado aqui — sinalizar "não
    # calculado" olhando o pré-recalc seria falso-negativo (o valor SAI na cascata).
    if pss_final is None:
        observacoes_homologado.append(
            "PSS não calculado (etapa 9 ausente ou natureza indeterminada)."
        )
    if ir_final is None:
        observacoes_homologado.append(
            "IR não calculado (etapa 10 ausente ou natureza indeterminada)."
        )

    liquido_homologado_atualizado: Decimal | None = None
    if pode_recalc_metodologia:
        # Líquido do cedente em moeda atualizada.
        base_liquido = total_atualizado_proporcional
        for desconto in (pss_final, ir_final, honor_final, contr_final):
            if desconto is not None:
                base_liquido = base_liquido - desconto
        liquido_homologado_atualizado = _q(base_liquido)

    cenario_homologado = Cenario(
        nome="homologado",
        disponivel=valor_total is not None,
        valor_total=_q(valor_total),
        valor_pss=_q(pss_final) if pss_final is not None else None,
        valor_ir=_q(ir_final) if ir_final is not None else None,
        pss_detalhe=pss_detalhe,
        ir_detalhe=ir_detalhe,
        honorarios_sucumbenciais_pct=honor_pct,
        valor_honorarios_sucumbenciais=honor_final,
        honorarios_contratuais_pct=honorarios_contratuais_pct,
        valor_honorarios_contratuais=contr_final,
        valor_liquido=liquido_homologado,
        valor_liquido_atualizado=liquido_homologado_atualizado,
        atualizacao=seg.atualizacao,
        observacoes=observacoes_homologado,
        principal_corrigido_atualizado=seg.principal_corrigido_atualizado,
        juros_moratorios_atualizado=seg.juros_moratorios_atualizado,
        selic_acumulada_atualizada=seg.selic_acumulada_atualizada,
        valor_total_atualizado=total_atualizado_proporcional if valor_total is not None else None,
        valor_superpreferencia=valor_superpreferencia,
        data_pagamento_superpreferencia=data_pagamento_superpreferencia,
        valor_corrigido_pre_superpreferencia=valor_corrigido_pre_superpreferencia,
        superpreferencia_detalhe=superpreferencia_detalhe,
    )

    # Cenário sentencial — v1 declarativo.
    if reconciliacao_status == "conforme":
        cenario_sentencial = Cenario(
            nome="sentencial",
            disponivel=cenario_homologado.disponivel,
            valor_total=cenario_homologado.valor_total,
            valor_pss=cenario_homologado.valor_pss,
            valor_ir=cenario_homologado.valor_ir,
            pss_detalhe=cenario_homologado.pss_detalhe,
            ir_detalhe=cenario_homologado.ir_detalhe,
            honorarios_sucumbenciais_pct=cenario_homologado.honorarios_sucumbenciais_pct,
            valor_honorarios_sucumbenciais=cenario_homologado.valor_honorarios_sucumbenciais,
            honorarios_contratuais_pct=cenario_homologado.honorarios_contratuais_pct,
            valor_honorarios_contratuais=cenario_homologado.valor_honorarios_contratuais,
            valor_liquido=cenario_homologado.valor_liquido,
            valor_liquido_atualizado=cenario_homologado.valor_liquido_atualizado,
            atualizacao=cenario_homologado.atualizacao,
            observacoes=[
                "Reconciliação conforme — cenário sentencial converge com o homologado."
            ],
            status_sentencial="convergente",
            principal_corrigido_atualizado=cenario_homologado.principal_corrigido_atualizado,
            juros_moratorios_atualizado=cenario_homologado.juros_moratorios_atualizado,
            selic_acumulada_atualizada=cenario_homologado.selic_acumulada_atualizada,
            valor_total_atualizado=cenario_homologado.valor_total_atualizado,
            valor_superpreferencia=cenario_homologado.valor_superpreferencia,
            data_pagamento_superpreferencia=cenario_homologado.data_pagamento_superpreferencia,
            valor_corrigido_pre_superpreferencia=cenario_homologado.valor_corrigido_pre_superpreferencia,
            superpreferencia_detalhe=cenario_homologado.superpreferencia_detalhe,
        )
    elif reconciliacao_status == "divergente":
        cenario_sentencial = _construir_sentencial_recalc(
            etapa8_response=etapa8_response,
            regime_etapa7=regime_etapa7,
            natureza_tributaria=natureza_tributaria,
            etapa10_payload=etapa10_payload,
            honor_pct=honor_pct,
            contratuais_pct=honorarios_contratuais_pct,
            cenario_homologado=cenario_homologado,
            data_calculo=data_calculo,
            data_alvo=data_alvo,
            data_apresentacao=data_apresentacao,
            esfera=esfera,
            data_expedicao=data_expedicao,
        )
    else:
        # decisao_silente | etapa7_nao_rodada | nao_comparado | None
        motivo = {
            "decisao_silente": "Decisão silente sobre regime — nada a comparar.",
            "etapa7_nao_rodada": "Etapa 7 não foi rodada — sem regime sentencial para comparar.",
            "nao_comparado": "Etapa 8 não extraiu períodos de correção — reconciliação não realizada.",
        }.get(reconciliacao_status or "", "Cenário sentencial indisponível.")
        cenario_sentencial = Cenario(
            nome="sentencial",
            disponivel=False,
            valor_total=None,
            valor_pss=None,
            valor_ir=None,
            honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None,
            valor_liquido=None,
            observacoes=[motivo],
            status_sentencial="indisponivel",
        )

    # Pior cenário = menor valor_liquido (em moeda da conta — atualização
    # é monotônica entre cenários, então ordenar por liquido bruto preserva
    # o ranking). `valor_oferta_base` reflete o atualizado quando disponível.
    candidatos = [c for c in (cenario_homologado, cenario_sentencial) if c.valor_liquido is not None]
    if not candidatos:
        pior = None
        valor_oferta = None
    else:
        pior_c = min(candidatos, key=lambda c: c.valor_liquido)
        pior = pior_c.nome
        valor_oferta = pior_c.valor_liquido_atualizado or pior_c.valor_liquido

    # Fallback de âncora na conta: o principal saiu da conta (acima); o(s)
    # ofício(s) de terceiro (honorário) ficam listados à parte, projetados
    # individualmente — informativos, fora da oferta do exequente (regra 8 i).
    blocos_terceiro_informativos: list[BlocoOficio] = []
    if ancora_conta_com_terceiros:
        blocos_terceiro_informativos = [
            _projetar_bloco_oficio(o, data_alvo, data_apresentacao, pss, ir)
            for o in oficios_terceiro
        ]

    return ResultadoCenarios(
        cenario_homologado=cenario_homologado,
        cenario_sentencial=cenario_sentencial,
        pior_cenario=pior,
        valor_oferta_base=valor_oferta,
        blocos_oficio=blocos_terceiro_informativos,
    )


def _construir_sentencial_recalc(
    *,
    etapa8_response: dict | None,
    regime_etapa7: list[dict] | None,
    natureza_tributaria: str | None,
    etapa10_payload: dict | None,
    honor_pct: Decimal | None,
    contratuais_pct: Decimal | None,
    cenario_homologado: Cenario,
    data_calculo: date | None,
    data_alvo: date,
    data_apresentacao: date | None = None,
    esfera: str | None = None,
    data_expedicao: date | None = None,
) -> Cenario:
    """v2 do cenário sentencial: aplica regime da etapa 7 sobre o
    valor_originario da conta. Cai pra `sob_revisao` se faltar input ou
    recalc não for suportado.

    `esfera`/`data_expedicao` seguem para a atualização segregada (cutover da
    EC 136 por esfera; janela TR do art. 21-A §7º). NOTA: `esfera` era usada no
    corpo sem estar na assinatura — NameError que derrubava todo este caminho
    (coberto agora por teste).
    """
    obs_falha = (
        "Conta diverge do regime decidido. Cenário sentencial exige "
        "recalcular o principal aplicando o regime da etapa 7 — "
        "advogado avalia manualmente o impacto antes da oferta."
    )

    valor_originario = _extrair_campo(etapa8_response, "valor_originario")
    data_base = _parse_data(
        (etapa8_response or {}).get("data_base", {}).get("valor")
        if isinstance(etapa8_response, dict)
        else None
    )
    data_calc = _parse_data(
        (etapa8_response or {}).get("data_calculo", {}).get("valor")
        if isinstance(etapa8_response, dict)
        else None
    )

    if (
        valor_originario is None
        or data_base is None
        or data_calc is None
        or not regime_etapa7
    ):
        return Cenario(
            nome="sentencial",
            disponivel=False,
            valor_total=None,
            valor_pss=None,
            valor_ir=None,
            honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None,
            valor_liquido=None,
            observacoes=[
                obs_falha,
                "Recalc indisponível: valor_originario, data_base/data_calculo "
                "ou regime_correcao da etapa 7 ausentes.",
            ],
            status_sentencial="sob_revisao",
        )

    try:
        resultado = aplicar_regime(
            valor_originario, data_base, regime_etapa7, data_calc
        )
    except IndiceNaoSuportado as e:
        return Cenario(
            nome="sentencial",
            disponivel=False,
            valor_total=None,
            valor_pss=None,
            valor_ir=None,
            honorarios_sucumbenciais_pct=None,
            valor_honorarios_sucumbenciais=None,
            valor_liquido=None,
            observacoes=[
                obs_falha,
                f"Recalc indisponível: {e.motivo}",
            ],
            status_sentencial="sob_revisao",
        )

    # Principal corrigido pelo regime sentencial.
    principal_sentencial = resultado.valor_corrigido
    # Juros: mantemos os juros declarados na conta (recalcular juros exige
    # tratamento próprio por período, fora do escopo da v1).
    juros = _extrair_campo(etapa8_response, "valor_juros") or Decimal("0")
    total_sentencial = (principal_sentencial + juros).quantize(Decimal("0.01"))

    # PSS/IR refeitos sobre o novo principal (mesmas regras das etapas 9/10).
    pss_resultado = calculo_pss.calcular_pss(natureza_tributaria, principal_sentencial)
    meses = (
        (etapa10_payload or {}).get("meses_competencia", 1)
        if etapa10_payload
        else 1
    )
    try:
        meses = int(meses)
    except (TypeError, ValueError):
        meses = 1
    # IR-RRA deduz o PSS recalculado (art. 12-A §4º Lei 7.713/88).
    ir_resultado = calculo_ir.calcular_ir_rra(
        natureza_tributaria,
        principal_sentencial,
        meses,
        pss_resultado.valor_pss if pss_resultado.incide else Decimal("0"),
    )

    pss_sentencial = pss_resultado.valor_pss
    ir_sentencial = ir_resultado.valor_ir
    honor_sentencial = None
    if honor_pct is not None:
        honor_sentencial = _q(total_sentencial * honor_pct / Decimal("100"))
    contr_sentencial = None
    if contratuais_pct is not None:
        contr_sentencial = _q(total_sentencial * contratuais_pct / Decimal("100"))

    liquido = total_sentencial
    for desconto in (pss_sentencial, ir_sentencial, honor_sentencial, contr_sentencial):
        if desconto is not None:
            liquido = liquido - desconto
    liquido = _q(liquido)

    obs = [
        f"Recalc com regime sentencial: principal R$ {principal_sentencial} "
        f"(vs R$ {cenario_homologado.valor_total} declarado).",
        "Juros mantidos como na conta (recalc de juros é v2.5).",
    ]
    if pss_resultado.incide is None:
        obs.append("PSS sentencial indeterminado (natureza ausente ou 'misto').")
    if ir_resultado.incide_ir is None:
        obs.append("IR sentencial indeterminado (natureza ausente ou 'misto').")

    # Atualização segregada do cenário recalculado (mesmo modelo Projef).
    seg_sent = _atualizar_segregado(
        principal_sentencial,
        juros,
        Decimal("0"),
        data_calculo,
        data_alvo,
        data_apresentacao=data_apresentacao,
        esfera=esfera,
        data_expedicao=data_expedicao,
    )
    if seg_sent.atualizacao.status in {
        "sem_data_origem",
        "cobertura_insuficiente",
        "sem_valor",
    }:
        liquido_atualizado = None
    else:
        total_atualizado_sent = seg_sent.valor_total_atualizado
        base_total_sent = principal_sentencial + juros
        if base_total_sent > 0:
            razao_sent = total_atualizado_sent / base_total_sent
            total_atualizado_proporcional_sent = (
                total_sentencial * razao_sent
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            total_atualizado_proporcional_sent = total_atualizado_sent
        honor_atual_sent = None
        if honor_pct is not None:
            honor_atual_sent = _q(
                total_atualizado_proporcional_sent * honor_pct / Decimal("100")
            )
        contr_atual_sent = None
        if contratuais_pct is not None:
            contr_atual_sent = _q(
                total_atualizado_proporcional_sent
                * contratuais_pct
                / Decimal("100")
            )
        liquido_atualizado = total_atualizado_proporcional_sent
        for desconto in (pss_sentencial, ir_sentencial, honor_atual_sent, contr_atual_sent):
            if desconto is not None:
                liquido_atualizado = liquido_atualizado - desconto
        liquido_atualizado = _q(liquido_atualizado)

    return Cenario(
        nome="sentencial",
        disponivel=True,
        valor_total=total_sentencial,
        valor_pss=_q(pss_sentencial),
        valor_ir=_q(ir_sentencial),
        honorarios_sucumbenciais_pct=honor_pct,
        valor_honorarios_sucumbenciais=honor_sentencial,
        honorarios_contratuais_pct=contratuais_pct,
        valor_honorarios_contratuais=contr_sentencial,
        valor_liquido=liquido,
        valor_liquido_atualizado=liquido_atualizado,
        atualizacao=seg_sent.atualizacao,
        observacoes=obs,
        status_sentencial="recalculado",
        principal_corrigido_atualizado=seg_sent.principal_corrigido_atualizado,
        juros_moratorios_atualizado=seg_sent.juros_moratorios_atualizado,
        selic_acumulada_atualizada=seg_sent.selic_acumulada_atualizada,
        valor_total_atualizado=seg_sent.valor_total_atualizado,
    )
