"""Etapa 9 — cálculo determinístico de PSS (previdência).

Python puro com `decimal.Decimal` — sem LLM. Recebe a natureza tributária
extraída na etapa 6 e a base de cálculo (principal corrigido sem juros)
e devolve o valor de PSS retido.

Regras:
- `remuneratorio` → PSS = 14% × base (default da empresa — ver constante)
- `previdenciario` | `indenizatorio` → PSS = 0 (não incide)
- `misto` → incide=None + flag para revisão manual (parcela remuneratória
  precisa ser segregada pelo advogado)

Notas sobre a alíquota default (14%):
- É um FALLBACK conservador, usado SÓ quando a conta não declara o PSS e
  não há override do revisor. O PSS extraído da conta (regra 2) e o
  override do FieldReview prevalecem — ver `calcular_etapa_9`.
- 14% = alíquota marginal máxima do RGPS / maioria dos RPPS. Aplica sobre
  toda a base, sem teto: superestima o PSS de propósito (dedução maior →
  líquido menor → oferta conservadora quando o valor real é desconhecido).
- Decisão de produto 2026-06-05 (substituiu o 11% anterior). A alíquota
  efetiva real de uma conta costuma ser ~4-6% (teto/tabela do INSS); por
  isso a conta, quando existe, SEMPRE prevalece sobre esta estimativa.

Base de cálculo: `valor_principal_corrigido` da etapa 8 (sem juros, sem
honorários). Decisão de design conservadora favorável ao contribuinte:
juros moratórios têm natureza indenizatória (jurisprudência consolidada
em verbas pagas em atraso por condenação contra a Fazenda) e não
compõem a remuneração para fins de contribuição previdenciária. Por
isso `valor_juros` da conta (categoria separada) NÃO entra na base —
mesmo quando regime composto IPCA-E+SELIC pós-EC 113 agrupa
correção+juros no campo "Selic" do Projef. O endpoint /etapas/9 expõe
`valor_juros_excluido_da_base` para o advogado auditar quanto foi
propositalmente excluído.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


# Alíquota default da empresa para o fallback estimado (decisão de produto
# 2026-06-05, substituiu 11%): 14% = pior-caso conservador (marginal máxima
# do RGPS / maioria dos RPPS). Usada SÓ quando a conta não traz o PSS e não
# há override; conta (regra 2) e override do revisor prevalecem. Superestimar
# a dedução quando o valor real é desconhecido é conservador p/ a oferta.
ALIQUOTA_PSS_PADRAO = Decimal("14")

# Mapping `natureza_tributaria` → incide PSS. None = exige revisão manual.
_INCIDE_PSS: dict[str, bool | None] = {
    "remuneratorio": True,
    "previdenciario": False,
    "indenizatorio": False,
    "misto": None,
}


@dataclass(frozen=True)
class ResultadoPSS:
    natureza_tributaria: str | None
    base: Decimal
    aliquota_pct: Decimal
    valor_pss: Decimal
    incide: bool | None  # None = caso "misto" ou natureza ausente
    justificativa: str
    # True quando o valor_pss veio de FieldReview na etapa 8 (decisão
    # jurídica do revisor), e o pipeline determinístico foi bypassado.
    # Sinaliza ao cenário (etapa 12) que esse valor é final e não deve
    # ser recalculado sobre a base atualizada.
    override_aplicado: bool = False

    def to_dict(self) -> dict:
        return {
            "natureza_tributaria": self.natureza_tributaria,
            "base": str(self.base),
            "aliquota_pct": str(self.aliquota_pct),
            "valor_pss": str(self.valor_pss),
            "incide": self.incide,
            "justificativa": self.justificativa,
            "override_aplicado": self.override_aplicado,
        }


def calcular_pss(
    natureza_tributaria: str | None,
    base: Decimal,
    aliquota_pct: Decimal = ALIQUOTA_PSS_PADRAO,
) -> ResultadoPSS:
    """Calcula PSS conforme natureza tributária (etapa 6) e base (etapa 8).

    `base` é o principal corrigido sem juros (decisão de design v1,
    posição conservadora pro contribuinte). Não inclui honorários
    sucumbenciais.

    Retorna ResultadoPSS com valor_pss arredondado para 2 casas (centavos)
    usando ROUND_HALF_UP — convenção fiscal brasileira.
    """
    if natureza_tributaria is None:
        return ResultadoPSS(
            natureza_tributaria=None,
            base=base,
            aliquota_pct=aliquota_pct,
            valor_pss=Decimal("0.00"),
            incide=None,
            justificativa=(
                "natureza_tributaria não disponível na etapa 6; "
                "rode a etapa 6 sobre a petição inicial para classificar"
            ),
        )

    incide = _INCIDE_PSS.get(natureza_tributaria)
    if incide is True:
        valor = (base * aliquota_pct / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return ResultadoPSS(
            natureza_tributaria=natureza_tributaria,
            base=base,
            aliquota_pct=aliquota_pct,
            valor_pss=valor,
            incide=True,
            justificativa=(
                f"natureza_tributaria='{natureza_tributaria}' (remuneratório) — "
                f"incide PSS à alíquota default de {aliquota_pct}% sobre o "
                "principal corrigido (estimativa conservadora da empresa quando "
                "a conta não declara o PSS; sem teto do RGPS, superestima de "
                "propósito a favor da oferta. Conta/override prevalecem)"
            ),
        )
    if incide is False:
        return ResultadoPSS(
            natureza_tributaria=natureza_tributaria,
            base=base,
            aliquota_pct=aliquota_pct,
            valor_pss=Decimal("0.00"),
            incide=False,
            justificativa=(
                f"natureza_tributaria='{natureza_tributaria}' — não incide PSS "
                "(verba não-remuneratória)"
            ),
        )
    return ResultadoPSS(
        natureza_tributaria=natureza_tributaria,
        base=base,
        aliquota_pct=aliquota_pct,
        valor_pss=Decimal("0.00"),
        incide=None,
        justificativa=(
            f"natureza_tributaria='{natureza_tributaria}' — requer revisão manual: "
            "PSS incide apenas sobre a parcela remuneratória, que precisa ser "
            "segregada pelo advogado"
        ),
    )


# Faixa plausível de alíquota previdenciária (servidor): RPPS 11–14%,
# RGPS 7,5–14%. Fora disso o número (geralmente uma base errada extraída do
# contracheque) é descartado para não contaminar o PSS — cai no flat default.
_ALIQUOTA_CONTRACHEQUE_MIN = Decimal("4")
_ALIQUOTA_CONTRACHEQUE_MAX = Decimal("25")


def aliquota_contracheque(
    previdencia_valor: Decimal | None,
    base: Decimal | None,
    aliquota_declarada: Decimal | None = None,
) -> Decimal | None:
    """Alíquota previdenciária efetiva a partir do contracheque (determinístico).

    Preferência: alíquota DECLARADA (impressa na folha) > efetiva
    (desconto ÷ base × 100). Retorna ``None`` quando não dá para computar com
    segurança OU quando o resultado cai fora da faixa plausível
    (`[4%, 25%]`) — nesse caso o chamador usa o flat default. A faixa evita
    propagar uma base errada (ex.: total bruto em vez da base de contribuição)
    para a estimativa do PSS.
    """
    if aliquota_declarada is not None and aliquota_declarada > 0:
        aliq = aliquota_declarada.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif previdencia_valor and base and base > 0:
        aliq = (previdencia_valor / base * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        return None
    if aliq < _ALIQUOTA_CONTRACHEQUE_MIN or aliq > _ALIQUOTA_CONTRACHEQUE_MAX:
        return None
    return aliq
