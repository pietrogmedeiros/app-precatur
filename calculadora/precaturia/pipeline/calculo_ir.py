"""Etapa 10 — cálculo determinístico de IR/RRA + ITCMD.

Python puro com `decimal.Decimal` — sem LLM. Aplica o regime de tributação
exclusiva de **Rendimentos Recebidos Acumuladamente (RRA)** previsto no
art. 12-A da Lei 7.713/88 (regulado pela IN RFB 1500/2014).

Algoritmo IR-RRA:
1. `base_apos_pss = max(base_total - pss_deduzir, 0)` (art. 12-A §4º — a
   contribuição previdenciária paga é dedutível da base de IR-RRA;
   IN RFB 1500/2014 art. 36 §3º consolida o entendimento).
2. `base_apos_deducoes = max(base_apos_pss - honorarios_deduzir, 0)` — os
   honorários advocatícios contratuais pagos pelo contribuinte são despesa
   necessária ao recebimento e deduzem a base do RRA, na proporção da
   parcela tributável (IN RFB 1500/2014 art. 8º, II e art. 36 §1º;
   pacífico no STJ). O caller passa o valor proporcional já calculado.
3. `base_mensal = base_apos_deducoes / meses_competencia`
4. Aplica a tabela progressiva MENSAL do IRPF sobre `base_mensal` →
   `ir_mensal = base_mensal × alíquota - parcela_dedutível`
5. `valor_ir = ir_mensal × meses_competencia`

A vantagem do regime RRA é diluir o valor acumulado nos meses a que se
refere, evitando que o contribuinte caia na faixa máxima (27,5%) apenas
porque recebeu de uma vez. Sem esse regime, um precatório de R$ 200k
seria tributado integralmente a 27,5%.

Regras de incidência (v1):
- `remuneratorio` → IR incide (verba salarial é renda tributável)
- `previdenciario` → IR incide (benefício previdenciário é renda
  tributável; isenções específicas — moléstia grave, idade ≥65 com
  parcela isenta — ficam para revisão manual em v2)
- `indenizatorio` → IR NÃO incide (indenização não tem natureza de renda)
- `misto` → revisão manual

ITCMD (Imposto sobre Transmissão Causa Mortis e Doação):
- Estado/DF; alíquota varia 4-8% por ente.
- **Não se aplica a cessão onerosa de precatório** (a Precatur compra
  pagando preço, não recebe por sucessão/doação). v1: `valor_itcmd = 0`
  sempre, com nota. Cessão onerosa pode gerar IR de ganho de capital
  para o cedente — escopo separado da etapa 10.

Limitações conhecidas (v2):
- Tabela progressiva fixa (IRPF vigente desde maio/2025, isenção
  R$ 2.428,80). Anos anteriores tinham faixas diferentes; o IR-RRA
  tecnicamente segue a tabela vigente na data de PAGAMENTO × NM (art.
  12-A). Como os precatórios em análise pagam de 2025 em diante, usa-se
  2025. Não é data-aware — quando houver pagamentos sob a tabela de 2026
  (isenção ~R$ 5.000), versionar por data.
- Sem deduções de dependentes ou pensão alimentícia. A dedução de
  previdência oficial (PSS calculado na etapa 9) entra via parâmetro
  `pss_deduzir` — o caller é responsável por passar o valor.
- Sem tratamento de isenção previdenciária por moléstia grave / idade.
- `meses_competencia` inferido de `data_calculo - data_base`; flag de
  baixa confiança porque essas datas nem sempre são as datas de
  competência reais (data_base pode ser a data do fato gerador, mas a
  conta atualizada cobre apenas até data_calculo — não o período que
  gerou a dívida).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


# Tabela progressiva mensal do IRPF (vigente desde maio/2025 — MP 1.294/2025:
# faixa de isenção elevada para R$ 2.428,80). Cada faixa é
# `(limite_superior, aliquota_pct, parcela_dedutivel)`. Última faixa tem
# limite=None (aberta). A parcela dedutível de cada faixa é a acumulação que
# torna o imposto contínuo nos limites (ex.: faixa 15% → 394,16).
# NOTA: o IR-RRA usa, a rigor, a tabela vigente no mês do PAGAMENTO (art. 12-A
# × NM). Como os precatórios em análise pagam de 2025 em diante, usa-se a tabela
# de 2025. Tabela única (não data-aware) é simplificação da v1 — quando o ente
# começar a pagar sob a tabela de 2026 (isenção ~R$ 5.000), versionar por data.
_TABELA_IRPF_MENSAL: list[tuple[Decimal | None, Decimal, Decimal]] = [
    (Decimal("2428.80"), Decimal("0"), Decimal("0.00")),
    (Decimal("2826.65"), Decimal("7.5"), Decimal("182.16")),
    (Decimal("3751.05"), Decimal("15"), Decimal("394.16")),
    (Decimal("4664.68"), Decimal("22.5"), Decimal("675.49")),
    (None, Decimal("27.5"), Decimal("908.73")),
]


# Mapping `natureza_tributaria` → incide IR. None = caso "misto" ou
# natureza ausente (revisão manual).
_INCIDE_IR: dict[str, bool | None] = {
    "remuneratorio": True,
    "previdenciario": True,
    "indenizatorio": False,
    "misto": None,
}


@dataclass(frozen=True)
class ResultadoIR:
    natureza_tributaria: str | None
    base_total: Decimal
    pss_deduzido: Decimal  # contribuição previdenciária deduzida da base (art. 12-A §4º)
    base_apos_pss: Decimal  # base_total - pss_deduzido (clamped a >=0)
    # Decimal, não int: quando há quitação parcial (superpreferência), o caller
    # rateia o NM total pela fração do crédito de cada parcela (mesmo critério
    # do CEPREC — ver cenarios.py) e o resultado é fracionário (ex.: 16,6).
    meses_competencia: Decimal
    # honorarios_deduzido / base_apos_deducoes ficam no fim (com default) por
    # ordenação de dataclass — declarados após `override_aplicado`.
    base_mensal: Decimal
    aliquota_efetiva_pct: Decimal  # aliquota da faixa (mensal), não taxa efetiva
    parcela_dedutivel: Decimal
    valor_ir: Decimal
    valor_itcmd: Decimal  # sempre 0 na v1 — ver módulo docstring
    incide_ir: bool | None  # None = caso misto ou natureza ausente
    justificativa: str
    # True quando o valor_ir veio de FieldReview na etapa 8 (decisão
    # jurídica do revisor), e o pipeline determinístico foi bypassado.
    # Sinaliza ao cenário (etapa 12) que esse valor é final e não deve
    # ser recalculado sobre a base atualizada.
    override_aplicado: bool = False
    # Honorários advocatícios contratuais deduzidos da base de IR-RRA
    # (IN RFB 1500/2014 art. 8º/36 — despesa com a ação paga pelo
    # contribuinte, dedutível na proporção da parcela tributável). Default
    # 0 preserva compatibilidade com callers que não informam o percentual.
    honorarios_deduzido: Decimal = Decimal("0.00")
    # Base efetiva do cálculo mensal (base_total − PSS − honorários).
    base_apos_deducoes: Decimal = Decimal("0.00")

    def to_dict(self) -> dict:
        return {
            "natureza_tributaria": self.natureza_tributaria,
            "base_total": str(self.base_total),
            "pss_deduzido": str(self.pss_deduzido),
            "base_apos_pss": str(self.base_apos_pss),
            "honorarios_deduzido": str(self.honorarios_deduzido),
            "base_apos_deducoes": str(self.base_apos_deducoes),
            "meses_competencia": str(self.meses_competencia),
            "base_mensal": str(self.base_mensal),
            "aliquota_efetiva_pct": str(self.aliquota_efetiva_pct),
            "parcela_dedutivel": str(self.parcela_dedutivel),
            "valor_ir": str(self.valor_ir),
            "valor_itcmd": str(self.valor_itcmd),
            "incide_ir": self.incide_ir,
            "justificativa": self.justificativa,
            "override_aplicado": self.override_aplicado,
        }


def meses_entre(data_base: date, data_calculo: date) -> int:
    """Conta meses de competência entre duas datas (inclusivo nos dois
    extremos). Mínimo 1.

    Exemplos:
    - 12/2017 → 12/2017: 1 mês (mesmo mês)
    - 12/2017 → 01/2018: 2 meses
    - 09/2006 → 12/2021: 184 meses (15 anos × 12 + 4 meses + inclusivo)
    """
    if data_calculo < data_base:
        return 1
    meses = (
        (data_calculo.year - data_base.year) * 12
        + (data_calculo.month - data_base.month)
        + 1
    )
    return max(1, meses)


def _aliquota_e_dedutivel(base_mensal: Decimal) -> tuple[Decimal, Decimal]:
    """Retorna `(aliquota_pct, parcela_dedutivel)` da faixa da tabela
    progressiva que cobre `base_mensal`.
    """
    for limite, aliquota, parcela in _TABELA_IRPF_MENSAL:
        if limite is None or base_mensal <= limite:
            return aliquota, parcela
    # Inalcançável — a última faixa tem limite=None.
    raise RuntimeError("tabela IRPF inconsistente")


def calcular_ir_rra(
    natureza_tributaria: str | None,
    base_total: Decimal,
    meses_competencia: Decimal | int,
    pss_deduzir: Decimal = Decimal("0"),
    honorarios_deduzir: Decimal = Decimal("0"),
) -> ResultadoIR:
    """Calcula IR-RRA conforme art. 12-A Lei 7.713/88.

    `base_total` é o principal corrigido sem juros (decisão de design v1,
    coerente com a base do PSS).

    `pss_deduzir` é o valor de contribuição previdenciária retido sobre o
    mesmo crédito (etapa 9), deduzido da base de IR-RRA na forma do art.
    12-A §4º Lei 7.713/88 e IN RFB 1500/2014 art. 36 §3º. Default 0
    preserva compatibilidade com callers antigos / cenários onde o PSS
    não é apurado.

    `honorarios_deduzir` é o valor de honorários advocatícios contratuais
    pagos pelo contribuinte, atribuível à parcela tributável, deduzido da
    base do RRA (IN RFB 1500/2014 art. 8º, II e art. 36 §1º — despesa com
    a ação judicial necessária ao recebimento; pacífico no STJ). O caller é
    responsável por passar o valor proporcional (tipicamente
    `base_total × %_contratual`). Deduzido APÓS o PSS. Default 0 preserva
    compatibilidade.

    `meses_competencia` é inferido de `data_calculo - data_base` no caller.
    Aceita fração (ex.: 16,6): quando o crédito foi pago em mais de uma
    parcela (superpreferência + saldo), o NM total é rateado entre as
    parcelas pela proporção de cada uma no crédito — mesmo critério do
    CEPREC (evento 39 do precatório 2005527-85.2025.8.13.0000/TJMG rateia
    34 meses em 17,4 e 16,6). O rateio é responsabilidade do caller; aqui só
    se normaliza para Decimal. Piso de 0,1 (não 1 mês inteiro): uma parcela
    pequena pode ratear pra bem menos que 1 mês, e forçar o piso pra 1
    diluiria demais a base mensal — o piso existe só pra evitar divisão por
    zero no caso degenerado (fração de rateio nula).
    """
    if not isinstance(meses_competencia, Decimal):
        meses_competencia = Decimal(meses_competencia)
    if meses_competencia < Decimal("0.1"):
        meses_competencia = Decimal("0.1")
    if pss_deduzir < 0:
        pss_deduzir = Decimal("0")
    if honorarios_deduzir < 0:
        honorarios_deduzir = Decimal("0")

    if natureza_tributaria is None:
        return ResultadoIR(
            natureza_tributaria=None,
            base_total=base_total,
            pss_deduzido=Decimal("0.00"),
            base_apos_pss=base_total,
            honorarios_deduzido=Decimal("0.00"),
            base_apos_deducoes=base_total,
            meses_competencia=meses_competencia,
            base_mensal=Decimal("0.00"),
            aliquota_efetiva_pct=Decimal("0"),
            parcela_dedutivel=Decimal("0.00"),
            valor_ir=Decimal("0.00"),
            valor_itcmd=Decimal("0.00"),
            incide_ir=None,
            justificativa=(
                "natureza_tributaria não disponível na etapa 6; "
                "rode a etapa 6 sobre a petição inicial para classificar"
            ),
        )

    incide = _INCIDE_IR.get(natureza_tributaria)
    if incide is False:
        return ResultadoIR(
            natureza_tributaria=natureza_tributaria,
            base_total=base_total,
            pss_deduzido=Decimal("0.00"),
            base_apos_pss=base_total,
            honorarios_deduzido=Decimal("0.00"),
            base_apos_deducoes=base_total,
            meses_competencia=meses_competencia,
            base_mensal=Decimal("0.00"),
            aliquota_efetiva_pct=Decimal("0"),
            parcela_dedutivel=Decimal("0.00"),
            valor_ir=Decimal("0.00"),
            valor_itcmd=Decimal("0.00"),
            incide_ir=False,
            justificativa=(
                f"natureza_tributaria='{natureza_tributaria}' — não incide IR "
                "(verba não tem natureza de renda)"
            ),
        )
    if incide is None:
        return ResultadoIR(
            natureza_tributaria=natureza_tributaria,
            base_total=base_total,
            pss_deduzido=Decimal("0.00"),
            base_apos_pss=base_total,
            honorarios_deduzido=Decimal("0.00"),
            base_apos_deducoes=base_total,
            meses_competencia=meses_competencia,
            base_mensal=Decimal("0.00"),
            aliquota_efetiva_pct=Decimal("0"),
            parcela_dedutivel=Decimal("0.00"),
            valor_ir=Decimal("0.00"),
            valor_itcmd=Decimal("0.00"),
            incide_ir=None,
            justificativa=(
                f"natureza_tributaria='{natureza_tributaria}' — requer revisão "
                "manual: IR incide apenas sobre a parcela com natureza de renda, "
                "que precisa ser segregada pelo advogado"
            ),
        )

    # Incide: deduz PSS e honorários contratuais da base e aplica RRA.
    # Clampa cada dedução pra não exceder o saldo da base (mantém
    # transparência: os campos `*_deduzido` refletem o que efetivamente
    # entrou na conta). Ordem: PSS primeiro, honorários sobre o saldo.
    pss_aplicado = pss_deduzir if pss_deduzir <= base_total else base_total
    base_apos_pss = base_total - pss_aplicado

    hon_aplicado = (
        honorarios_deduzir if honorarios_deduzir <= base_apos_pss else base_apos_pss
    )
    base_apos_deducoes = base_apos_pss - hon_aplicado

    base_mensal = (base_apos_deducoes / meses_competencia).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    aliquota_pct, parcela_dedutivel = _aliquota_e_dedutivel(base_mensal)

    ir_mensal = (
        (base_mensal * aliquota_pct / Decimal("100")) - parcela_dedutivel
    )
    if ir_mensal < 0:
        ir_mensal = Decimal("0")

    valor_ir = (ir_mensal * meses_competencia).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    pss_msg = (
        f", PSS deduzido R$ {pss_aplicado} (art. 12-A §4º)"
        if pss_aplicado > 0
        else ""
    )
    hon_msg = (
        f", honorários contratuais deduzidos R$ {hon_aplicado} "
        "(IN RFB 1500/2014 art. 8º/36)"
        if hon_aplicado > 0
        else ""
    )
    return ResultadoIR(
        natureza_tributaria=natureza_tributaria,
        base_total=base_total,
        pss_deduzido=pss_aplicado,
        base_apos_pss=base_apos_pss,
        honorarios_deduzido=hon_aplicado,
        base_apos_deducoes=base_apos_deducoes,
        meses_competencia=meses_competencia,
        base_mensal=base_mensal,
        aliquota_efetiva_pct=aliquota_pct,
        parcela_dedutivel=parcela_dedutivel,
        valor_ir=valor_ir,
        valor_itcmd=Decimal("0.00"),
        incide_ir=True,
        justificativa=(
            f"natureza_tributaria='{natureza_tributaria}' — IR-RRA art. 12-A "
            f"Lei 7.713/88: base_mensal={base_mensal} (= {base_apos_deducoes} / "
            f"{meses_competencia} meses{pss_msg}{hon_msg}), faixa {aliquota_pct}% com "
            f"parcela dedutível {parcela_dedutivel}. ITCMD não se aplica a "
            "cessão onerosa (v1: valor_itcmd=0)."
        ),
    )
