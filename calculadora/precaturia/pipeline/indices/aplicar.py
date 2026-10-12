"""Aplicação de regime composto sobre valor originário.

Convenção do Manual de Cálculos da Justiça Federal:

- O **mês da data-base é excluído** (o valor já está nesse mês).
- O **mês da data alvo é incluído** (correção até o cálculo).
- Para regime composto (ex.: IPCA-E até 12/2021, SELIC depois), o
  primeiro período corre de `data_base+1` até o `fim_data` ou marco
  qualitativo do período; o segundo começa no mês seguinte do fim do
  primeiro.

Para precatórios pós-EC 113/2021, a convenção mais comum é:
- IPCA-E até 09/12/2021 (data da EC) — para correção monetária.
- SELIC a partir de 10/12/2021 — correção monetária + juros (substitui
  tudo).

O eval da v1 usa **SELIC do mês completo** (4390 = % a.m. acumulada),
não taxa diária. Isso introduz pequeno erro em casos onde o marco é
mid-mês, aceitável para o MVP. Em produção real, usar Selic over diária
(série 11) e compor dia a dia.

Cada `PeriodoIndice` tem início/fim que podem ser:
- `data` + `inicio_data`/`fim_data` — datas explícitas.
- âncoras qualitativas: `data_base`, `ajuizamento`, `citacao`,
  `transito_julgado`, `vencimento`, `pagamento`, `expedicao_precatorio`,
  `data_calculo`, `vigente`.

A v1 só sabe mapear `data_base` → data_base do cálculo, `data` →
inicio_data/fim_data explícitos, e `pagamento`/`vigente`/`data_calculo`
→ a data alvo. Outras âncoras (`ajuizamento`, `citacao`,
`transito_julgado`, `vencimento`, `expedicao_precatorio`) viram
`IndiceNaoSuportado` — o caller decide se cai para revisão manual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from precaturia.pipeline.indices.series import INDICES_SUPORTADOS, load_serie


class IndiceNaoSuportado(Exception):
    """Levantado quando o regime usa índice/marco que a v1 não cobre.

    Os campos `motivo` e `detalhes` permitem mensagem clara para a UI.
    """

    def __init__(self, motivo: str, detalhes: dict | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.detalhes = detalhes or {}


_ANCORAS_DATA_BASE = {"data_base"}
_ANCORAS_DATA_ALVO = {"pagamento", "vigente", "data_calculo"}
_ANCORAS_NAO_SUPORTADAS = {
    "ajuizamento",
    "citacao",
    "transito_julgado",
    "vencimento",
    "expedicao_precatorio",
}


def _proximo_mes(d: date) -> date:
    """Primeiro dia do mês seguinte."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _primeiro_dia_mes(d: date) -> date:
    return date(d.year, d.month, 1)


def _mes_iso(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _parse_data_periodo(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


def _resolver_marco(
    tipo: str, data_str: str | None, data_base: date, data_alvo: date
) -> date:
    if tipo == "data":
        d = _parse_data_periodo(data_str)
        if d is None:
            raise IndiceNaoSuportado(
                "marco 'data' sem inicio_data/fim_data válida",
                {"tipo": tipo, "data": data_str},
            )
        return d
    if tipo in _ANCORAS_DATA_BASE:
        return data_base
    if tipo in _ANCORAS_DATA_ALVO:
        return data_alvo
    if tipo in _ANCORAS_NAO_SUPORTADAS:
        raise IndiceNaoSuportado(
            f"marco temporal {tipo!r} não suportado na v1 (recalc usa só "
            "data_base, datas explícitas e pagamento/vigente/data_calculo)",
            {"tipo": tipo},
        )
    raise IndiceNaoSuportado(
        f"marco temporal desconhecido: {tipo!r}",
        {"tipo": tipo},
    )


def _iterar_meses(de_exclusivo: date, ate_inclusivo: date):
    """Itera por meses YYYY-MM entre de (exclusivo) e ate (inclusivo).

    Convenção do Manual JF: o mês da data-base/início do período não
    entra; o mês alvo entra. Para regimes compostos, o "fim" de um
    período corresponde ao "início" do próximo (não há gap, não há
    overlap).
    """
    cursor = _proximo_mes(_primeiro_dia_mes(de_exclusivo))
    fim = _primeiro_dia_mes(ate_inclusivo)
    while cursor <= fim:
        yield _mes_iso(cursor)
        cursor = _proximo_mes(cursor)


def fator_periodo(indice: str, de_exclusivo: date, ate_inclusivo: date) -> Decimal:
    """Fator multiplicativo acumulado entre duas datas.

    Convenção: meses entre `de_exclusivo` (excluído) e `ate_inclusivo`
    (incluído). Retorna `Decimal("1")` se o intervalo não cobre nenhum
    mês completo.

    Levanta `IndiceNaoSuportado` se algum mês do intervalo está fora da
    cobertura da série (data alvo no futuro além do publicado).
    """
    if indice not in INDICES_SUPORTADOS:
        raise IndiceNaoSuportado(
            f"índice {indice!r} não tem série versionada na v1",
            {"indice": indice, "suportados": sorted(INDICES_SUPORTADOS)},
        )
    serie = load_serie(indice)
    fator = Decimal("1")
    for mes in _iterar_meses(de_exclusivo, ate_inclusivo):
        valor = serie.get(mes)
        if valor is None:
            raise IndiceNaoSuportado(
                f"mês {mes} fora da cobertura da série {indice!r}",
                {"indice": indice, "mes": mes},
            )
        fator *= Decimal("1") + valor / Decimal("100")
    return fator


def fator_ipca_e(de_exclusivo: date, ate_inclusivo: date) -> Decimal:
    """Fator IPCA-E acumulado entre duas datas (wrapper de `fator_periodo`).

    Helper nominado para o updater segregado (cenário V2 espelhando o
    Projef Web): IPCA-E corrige o principal e os juros moratórios
    congelados, enquanto SELIC entra linearmente sobre o principal_corrigido.
    Manter `fator_periodo` genérico para outros usos (regimes compostos).
    """
    return fator_periodo("IPCA-E", de_exclusivo, ate_inclusivo)


@dataclass
class FatorPeriodo:
    indice: str
    inicio: date
    fim: date
    fator: Decimal


@dataclass
class ResultadoRecalc:
    valor_originario: Decimal
    valor_corrigido: Decimal
    data_base: date
    data_alvo: date
    fatores: list[FatorPeriodo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valor_originario": str(self.valor_originario),
            "valor_corrigido": str(self.valor_corrigido),
            "data_base": self.data_base.isoformat(),
            "data_alvo": self.data_alvo.isoformat(),
            "fatores": [
                {
                    "indice": f.indice,
                    "inicio": f.inicio.isoformat(),
                    "fim": f.fim.isoformat(),
                    "fator": str(f.fator),
                }
                for f in self.fatores
            ],
        }


def aplicar_regime(
    valor_originario: Decimal,
    data_base: date,
    regime: list[dict],
    data_alvo: date,
) -> ResultadoRecalc:
    """Aplica um regime composto ao valor.

    `regime` é uma lista de `PeriodoIndice` em formato dict (como vem
    do response_json — não exige Pydantic). Períodos são aplicados na
    ordem em que aparecem; o `fim` de um deve coincidir com o `inicio`
    do próximo para evitar gap/overlap, mas a função não força isso
    (deixa pro caller decidir se quer reordenar).

    Levanta `IndiceNaoSuportado` quando:
    - regime vazio
    - algum período usa índice fora de INDICES_SUPORTADOS
    - algum período usa marco temporal não-resolvível
    - algum mês do intervalo está fora da cobertura da série
    """
    if not regime:
        raise IndiceNaoSuportado("regime vazio — nada a aplicar")

    valor = valor_originario
    fatores: list[FatorPeriodo] = []
    for p in regime:
        indice = p.get("indice")
        if indice not in INDICES_SUPORTADOS:
            raise IndiceNaoSuportado(
                f"índice {indice!r} não tem série versionada na v1",
                {"indice": indice, "suportados": sorted(INDICES_SUPORTADOS)},
            )
        inicio = _resolver_marco(
            p.get("inicio_tipo"), p.get("inicio_data"), data_base, data_alvo
        )
        fim = _resolver_marco(
            p.get("fim_tipo"), p.get("fim_data"), data_base, data_alvo
        )
        if fim < inicio:
            raise IndiceNaoSuportado(
                f"período com fim ({fim}) anterior ao início ({inicio})",
                {"indice": indice, "inicio": inicio.isoformat(), "fim": fim.isoformat()},
            )
        fator = fator_periodo(indice, inicio, fim)
        valor = valor * fator
        fatores.append(FatorPeriodo(indice=indice, inicio=inicio, fim=fim, fator=fator))

    # Arredondamento final — 2 casas (centavos).
    from decimal import ROUND_HALF_UP

    valor = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return ResultadoRecalc(
        valor_originario=valor_originario,
        valor_corrigido=valor,
        data_base=data_base,
        data_alvo=data_alvo,
        fatores=fatores,
    )
