"""Calculadora manual de precatórios — "modo manual" sobre o motor de cálculo.

Reusa o motor determinístico de PRODUÇÃO (`construir_cenarios`, `calcular_pss`)
SEM tocar no banco nem na IA. O advogado informa os valores que a IA normalmente
extrai; o MESMO código de cenários roda → **número idêntico ao do sistema**
(paridade estrutural, não "best effort"). Ver `docs/calculadora_campos.md`.

Por que isto é uma camada FINA, não um recálculo: `construir_cenarios` já é puro
("Não chama o DB ... pura e testável", docstring em `cenarios.py`). A única coisa
que falta no uso manual é montar os mesmos dicts de payload que o `api/cases.py`
monta a partir da extração da IA — é o que este módulo faz.

**MODO CONTA**: o advogado digita os valores já corrigidos da conta homologada
(Projef/SICAR/eproc) + PSS/IR declarados (ou estima PSS e IR-RRA por natureza),
e a calculadora produz os dois cenários + atualização ao presente + graça.

Estimativa de IR-RRA (art. 12-A Lei 7.713) — decisões deliberadas:
- Base a valor presente pela MESMA `_atualizar_segregado` da oferta, ancorada
  em `data_calculo` (onde o principal corrigido está em moeda); deduz o PSS
  apurado (art. 12-A §4º). É **congelada com `override_aplicado=True`** para não
  ser re-inflada pelo recompute do cenário (e para o histórico e o atualizado
  usarem o MESMO IR).
- **Honorários contratuais: dedução no FINAL.** O crédito é atualizado
  INTEIRO e o % contratual sai como linha própria da cascata (igual PSS/IR):
  o motor calcula `pct × valor_total_atualizado` (`contr_recalc` em
  `construir_cenarios`) e expõe o valor exato em
  `valor_honorarios_contratuais`. A base dos PSS/IR **estimados** continua
  sendo a parte do credor (70%/80%): o recalc do motor aplica × (1 − pct) e o
  IR congelado daqui aplica o MESMO fator (`_fator_credor`) — paridade com a
  metodologia. Valores DECLARADOS não são ajustados (já são do credor). NÃO se
  usa o `honorarios_deduzir` de `calcular_ir_rra` (armadilha #1 da auditoria:
  nenhum caller de cenário o passa) — a redução vem do fator sobre a base.
- Sem os meses do RRA (e sem datas para inferi-los) o IR fica **"a apurar"**
  (None, congelado) em vez de inflar com meses=1 (failure mode F05).

Deixado para o incremento 3:
- **MODO ORIGINÁRIO** (corrigir do zero via `aplicar_regime`). O regime já é
  aceito aqui (vai para `regime_etapa7`/`periodos_correcao`), mas a ancoragem
  pelo originário ganha teste próprio.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from precaturia.pipeline import calculo_ir, calculo_pss
from precaturia.pipeline import cenarios as cenarios_pipeline
from precaturia.pipeline import regime_historico
from precaturia.pipeline.cenarios import ResultadoCenarios
from precaturia.pipeline.regime_historico import ResultadoRegime

# Alíquota flat de PSS quando se ESTIMA (sem valor declarado). Espelha o clamp
# que o caller `cenarios.py` aplica (auditoria #3): a função pura `calcular_pss`
# NÃO clampa — chamá-la com 0 zeraria o PSS. Replicamos o clamp aqui.
ALIQUOTA_PSS_PADRAO = Decimal("14")


@dataclass
class EntradaCalculadora:
    """Inputs do formulário manual (um crédito). Ver `docs/calculadora_campos.md`.

    Tudo em `Decimal` (regra 2 — nunca `float` para dinheiro). Campos None
    são simplesmente omitidos do payload, espelhando uma extração silente.
    """

    # ── Valores da conta (modo conta) ────────────────────────────────────
    valor_total: Decimal | None = None
    valor_bruto_reclamante: Decimal | None = None  # Súmula 368 TST; vence se ≠ total
    valor_principal_corrigido: Decimal | None = None  # base do overlay/PSS/IR
    valor_juros: Decimal = Decimal("0")  # fora da base PSS/IR
    valor_selic: Decimal = Decimal("0")  # SELIC já acumulada (entra no overlay)
    valor_originario: Decimal | None = None  # co-requisito do recalc sentencial
    data_base: date | None = None
    data_calculo: date | None = None  # vira data_origem da atualização

    # ── Regime de correção (recalc sentencial declarativo, SGS) ──────────
    regime: list[dict] | None = None  # list[PeriodoIndice em dict]

    # ── Modo ORIGINÁRIO (corrige do ZERO por natureza + data-base) ────────
    natureza: str | None = None  # comum|servidor|previdenciario|tributario|desapropriacao|assistencial
    assistencial_indice: str | None = None  # BPC/LOAS: 'INPC'|'IPCA-E' (§5 do doc)

    # ── Natureza / tributação (PSS/IR) ───────────────────────────────────
    natureza_tributaria: str | None = None  # remuneratorio|previdenciario|indenizatorio|misto
    valor_pss: Decimal | None = None  # declarado na conta (precede a estimativa)
    estimar_pss: bool = False  # estima por natureza quando não declarado
    aliquota_pss_pct: Decimal | None = None  # só na estimativa; clamp ≤0→14
    valor_ir: Decimal | None = None  # declarado na conta (precede a estimativa)
    estimar_ir: bool = False  # estima IR-RRA por natureza quando não declarado
    meses_competencia: int | None = None  # meses do RRA (art. 12-A)

    # ── Honorários ───────────────────────────────────────────────────────
    honorarios_sucumbenciais_pct: Decimal | None = None
    honorarios_contratuais_pct: Decimal | None = None

    # ── Precatório & período de graça ────────────────────────────────────
    modalidade: str | None = None  # precatorio|rpv
    data_apresentacao: date | None = None  # âncora da graça (art. 100 §5º + SV 17)
    # Pagamento antecipado por superpreferência (idoso 80+/doença grave/PcD,
    # RCL/EC 114): abate BRUTO do saldo na data do pagamento (corrige até lá,
    # subtrai proporcionalmente de principal/juros/SELIC, segue corrigindo o
    # resto). Ver `cenarios.construir_cenarios`.
    valor_superpreferencia: Decimal | None = None
    data_pagamento_superpreferencia: date | None = None
    # Data de EXPEDIÇÃO do precatório — decide a janela TR do art. 21-A §7º (TR
    # de dez/2009 a mar/2015 SÓ para expedido/pago até 25/03/2015; senão IPCA-E).
    # Só importa para conta anterior a dez/2021. Vazio = não aplica TR.
    data_expedicao: date | None = None
    # Esfera do ente devedor: 'federal' migra p/ EC 136 (IPCA+2%) só em set/2025;
    # 'estadual'/'municipal'/None → ago/2025 (Provimento CNJ 207/2025). Ver
    # docs/regimes_historicos.md §0 achado 1.
    esfera: str | None = None

    # ── Atualização ao presente ──────────────────────────────────────────
    data_alvo: date | None = None  # default = hoje (em construir_cenarios)
    reconciliacao_status: str | None = None  # divergente → recalc sentencial


def _campo(valor: Decimal | None) -> dict | None:
    """Embrulha um valor no formato `{valor}` que `_extrair_campo` espera."""
    return {"valor": str(valor)} if valor is not None else None


def _fator_credor(entrada: EntradaCalculadora) -> Decimal:
    """Fração do crédito que fica com o credor após o destaque contratual
    (1 − pct/100). Base dos PSS/IR ESTIMADOS — espelha o recalc de metodologia
    do motor (base × (1 − contr_pct)); valores DECLARADOS não são ajustados
    (já são do credor)."""
    pct = entrada.honorarios_contratuais_pct
    if pct is None or pct <= 0:
        return Decimal("1")
    return Decimal("1") - pct / Decimal("100")


def _resolver_pss(entrada: EntradaCalculadora) -> Decimal | None:
    """PSS na precedência: declarado > estimado (por natureza) > None.

    None significa "não apurado" — `construir_cenarios` não deduz e anota a
    observação (não confundir com 0 explícito, que deduz 0).
    """
    if entrada.valor_pss is not None:
        return entrada.valor_pss
    if entrada.estimar_pss and entrada.natureza_tributaria:
        base = entrada.valor_principal_corrigido or entrada.valor_total
        if base is None:
            return None
        base = base * _fator_credor(entrada)
        aliq = entrada.aliquota_pss_pct
        if aliq is None or aliq <= 0:  # replica o clamp do caller (auditoria #3)
            aliq = ALIQUOTA_PSS_PADRAO
        res = calculo_pss.calcular_pss(entrada.natureza_tributaria, base, aliq)
        # misto (incide=None) → "a apurar": não estimamos um flat sobre base
        # mista; espelha o IR (a parcela remuneratória precisa ser segregada).
        return res.valor_pss if res.incide is not None else None
    return None


def _resolver_meses(entrada: EntradaCalculadora) -> int | None:
    """Meses do RRA: informado > inferido das datas (data_base→data_calculo) >
    None ("a apurar"). `meses_entre` já garante mínimo 1."""
    if entrada.meses_competencia is not None and entrada.meses_competencia >= 1:
        return entrada.meses_competencia
    if entrada.data_base is not None and entrada.data_calculo is not None:
        return calculo_ir.meses_entre(entrada.data_base, entrada.data_calculo)
    return None


def _resolver_ir(entrada: EntradaCalculadora) -> dict | None:
    """Monta o `etapa10_payload` do IR-RRA (precedência declarado > estimado).

    - **Declarado** (`valor_ir`): congela com `override_aplicado=True` — o motor
      não recalcula; preserva o valor exato do advogado.
    - **Estimável e tributável, com meses**: passa só `meses_competencia`, SEM
      override. `construir_cenarios` recalcula o IR sobre a base ATUALIZADA
      (principal corrigido, sem juros) deduzindo o PSS FINAL — na MESMA base do
      PSS (art. 12-A §4º). Antes o wrapper congelava um IR próprio que (i)
      deduzia um PSS defasado (apurado na data-base, não atualizado) e (ii)
      incluía os 2% de mora da EC 136 (juros, não tributáveis) na base —
      inflando o IR e divergindo da plataforma. Deixar o motor recalcular fecha
      os dois furos e mantém calculadora ≡ plataforma.
    - **Tributável sem meses**: `override_aplicado=True` sem valor ("a apurar") —
      não deixa o motor inferir meses=1 e inflar (F05).
    - **Indenizatório** (não tributável): IR 0 congelado.
    - **Misto / natureza desconhecida**: "a apurar" congelado (o advogado
      segrega a parcela tributável).
    - **Não estima e não declara**: repassa `meses_competencia` se informado
      (evita meses=1 no recompute), senão None.
    """
    if entrada.valor_ir is not None:
        return {"valor_ir": str(entrada.valor_ir), "override_aplicado": True}
    if not (entrada.estimar_ir and entrada.natureza_tributaria):
        if entrada.meses_competencia is not None:
            return {"meses_competencia": str(entrada.meses_competencia)}
        return None
    incide = calculo_ir._INCIDE_IR.get(entrada.natureza_tributaria)
    if incide is False:  # indenizatório → não incide
        return {"valor_ir": "0.00", "override_aplicado": True}
    if incide is None:  # misto / natureza desconhecida → a apurar
        return {"override_aplicado": True}
    base = entrada.valor_principal_corrigido or entrada.valor_total
    if base is None or base <= 0:
        return {"override_aplicado": True}  # base ausente → a apurar (não inflar)
    meses = _resolver_meses(entrada)
    if meses is None:
        return {"override_aplicado": True}  # taxável sem meses → a apurar (F05)
    # Tributável com meses: o motor recalcula o IR na base atualizada + PSS final.
    return {"meses_competencia": str(meses)}


def montar_payloads(
    entrada: EntradaCalculadora,
) -> tuple[dict, dict | None, dict | None]:
    """Constrói `(etapa8_response, etapa9_payload, etapa10_payload)`.

    Exposto à parte do `calcular` para o teste de paridade poder confrontar o
    payload montado contra uma chamada direta a `construir_cenarios`.
    """
    etapa8_response: dict = {}
    # `valor_total`/`valor_bruto_reclamante` definem a FACE do crédito: um 0
    # perdido neles (ex.: campo deixado em zero no formulário/Swagger) zeraria a
    # base e produziria líquido negativo — `valor_bruto_reclamante=0` ainda
    # dispararia a Súmula 368 e venceria um `valor_total` real. Tratamos ≤0 como
    # "não informado" (não existe crédito de face 0). `valor_juros`/`valor_selic`
    # = 0 são legítimos e passam.
    monetarios = [
        ("valor_total", entrada.valor_total, True),
        ("valor_bruto_reclamante", entrada.valor_bruto_reclamante, True),
        ("valor_principal_corrigido", entrada.valor_principal_corrigido, True),
        ("valor_juros", entrada.valor_juros, False),
        ("valor_selic", entrada.valor_selic, False),
        ("valor_originario", entrada.valor_originario, True),
        ("honorarios_sucumbenciais_pct", entrada.honorarios_sucumbenciais_pct, False),
    ]
    for campo, valor, exige_positivo in monetarios:
        if exige_positivo and (valor is None or valor <= 0):
            continue
        embrulho = _campo(valor)
        if embrulho is not None:
            etapa8_response[campo] = embrulho
    if entrada.data_base is not None:
        etapa8_response["data_base"] = {"valor": entrada.data_base.isoformat()}
    if entrada.data_calculo is not None:
        etapa8_response["data_calculo"] = {"valor": entrada.data_calculo.isoformat()}
    if entrada.regime is not None:
        etapa8_response["periodos_correcao"] = entrada.regime

    # PSS. Declarado (conta/override) carrega `override_aplicado=True` —
    # espelha `calcular_etapa_9` no ramo `conta_homologada`: sem essa flag, a
    # linha ATUALIZADA do cenário re-estima o PSS a 14% sobre a base corrigida
    # ao presente (e ignora o valor da conta). Estimado vai SEM override + com
    # a alíquota usada, para o recompute reproduzir a estimativa sobre a base
    # atualizada (fonte=estimado).
    pss = _resolver_pss(entrada)
    if entrada.valor_pss is not None:
        etapa9_payload: dict | None = {
            "valor_pss": str(entrada.valor_pss),
            "override_aplicado": True,
        }
    elif pss is not None:
        aliq = entrada.aliquota_pss_pct
        if aliq is None or aliq <= 0:
            aliq = ALIQUOTA_PSS_PADRAO
        etapa9_payload = {"valor_pss": str(pss), "aliquota_pct": str(aliq)}
    else:
        etapa9_payload = None

    # IR. Ver `_resolver_ir`: declarado congela com override; estimável tributável
    # COM meses é recalculado pelo motor sobre a base atualizada deduzindo o PSS
    # final (art. 12-A §4º) — sem congelar; sem meses / misto → "a apurar";
    # indenizatório → 0. Mantém IR e PSS na MESMA base (calculadora ≡ plataforma).
    etapa10_payload: dict | None = _resolver_ir(entrada)
    return etapa8_response, etapa9_payload, etapa10_payload


def _regime_originario(entrada: EntradaCalculadora) -> ResultadoRegime | None:
    """Se em MODO ORIGINÁRIO (natureza histórica + valor_originario + data_base +
    data_calculo), corrige o originário da data-base até a data do cálculo pela
    fase de condenação (`regime_historico`). Senão, None."""
    if not (
        entrada.natureza
        and entrada.valor_originario is not None
        and entrada.data_base is not None
        and entrada.data_calculo is not None
    ):
        return None
    regime = regime_historico.construir_regime(
        entrada.natureza,
        entrada.data_base,
        entrada.data_calculo,
        assistencial_indice=entrada.assistencial_indice,
    )
    return regime_historico.aplicar_regime_historico(entrada.valor_originario, regime)


def _com_originario(entrada: EntradaCalculadora) -> EntradaCalculadora:
    """Injeta o principal corrigido + juros do motor histórico como se fossem a
    conta (modo originário). No-op se não estiver em modo originário."""
    res = _regime_originario(entrada)
    if res is None:
        return entrada
    return replace(
        entrada,
        valor_principal_corrigido=res.principal_corrigido,
        valor_juros=res.juros,
        valor_total=res.total,
        valor_selic=Decimal("0"),
    )


def calcular(entrada: EntradaCalculadora) -> ResultadoCenarios:
    """Roda o motor de cenários sobre os inputs manuais (sem banco, sem IA).

    **Modo conta**: usa os valores da conta. **Modo originário** (`natureza` +
    `valor_originario` + `data_base` + `data_calculo`): corrige o originário do
    zero pela fase de condenação (`regime_historico`) e injeta como conta.

    O crédito é atualizado INTEIRO; os honorários contratuais são deduzidos no
    FINAL, sobre o valor atualizado (`valor_honorarios_contratuais`). Roda o
    MESMO `ResultadoCenarios` do sistema: homologado × sentencial, atualização ao
    presente segregada (SELIC/EC 113 + IPCA/EC 136), graça e `valor_oferta_base`.
    """
    entrada = _com_originario(entrada)
    etapa8_response, etapa9_payload, etapa10_payload = montar_payloads(entrada)
    return cenarios_pipeline.construir_cenarios(
        etapa8_response=etapa8_response,
        etapa9_payload=etapa9_payload,
        etapa10_payload=etapa10_payload,
        reconciliacao_status=entrada.reconciliacao_status,
        regime_etapa7=entrada.regime,
        natureza_tributaria=entrada.natureza_tributaria,
        data_alvo=entrada.data_alvo,
        honorarios_contratuais_pct=entrada.honorarios_contratuais_pct,
        data_apresentacao=entrada.data_apresentacao,
        oficios_ground_truth=None,  # calculadora é por crédito; sem multi-ofício
        agregar_exequente=False,
        esfera=entrada.esfera,
        data_expedicao=entrada.data_expedicao,
        valor_superpreferencia=entrada.valor_superpreferencia,
        data_pagamento_superpreferencia=entrada.data_pagamento_superpreferencia,
    )


def calcular_dict(entrada: EntradaCalculadora) -> dict:
    """Resultado serializado. Em modo originário, adiciona a chave `originario`
    com o memorial da correção (fatores por período + juros)."""
    d = calcular(entrada).to_dict()
    res = _regime_originario(entrada)
    if res is not None:
        d["originario"] = {
            "valor_originario": str(res.valor_originario),
            "principal_corrigido": str(res.principal_corrigido),
            "juros": str(res.juros),
            "total": str(res.total),
            "fator_correcao": str(res.fator_correcao),
            "percentual_juros": str(res.percentual_juros),
            "componentes_correcao": [
                {
                    "indice": c.indice,
                    "inicio": c.inicio_excl.isoformat(),
                    "fim": c.fim_incl.isoformat(),
                    "fator": str(c.fator),
                }
                for c in res.componentes_correcao
            ],
            "componentes_juros": [
                {
                    "modo": j.modo,
                    "inicio": j.inicio_excl.isoformat(),
                    "fim": j.fim_incl.isoformat(),
                    "percentual": str(j.percentual),
                    "valor": str(j.valor),
                }
                for j in res.componentes_juros
            ],
            "avisos": list(res.avisos),
        }
        # A atualização ao presente modela a fase precatório do art. 21-A
        # (IPCA-E/TR + poupança até nov/2021) e avisa sobre a janela TR/§7º na
        # própria mensagem — não precisa mais de ressalva aqui.
    return d


# Grade default dos cenários de honorário contratual (memorial provisório):
# cobre a faixa praticada nos contratos vistos no CRM (10–30%), de 5 em 5.
GRADE_HONORARIOS_PCT = (
    Decimal("0"), Decimal("10"), Decimal("15"), Decimal("20"), Decimal("25"),
    Decimal("30"),
)


def cenarios_honorarios_contratuais(
    entrada: EntradaCalculadora,
    grade: tuple[Decimal, ...] = GRADE_HONORARIOS_PCT,
) -> list[dict]:
    """Líquido por % de honorário contratual — cada linha é o MOTOR inteiro.

    Descontar o percentual "por fora" do líquido pronto é errado: nos PSS/IR
    ESTIMADOS o percentual entra na base dos dois (× (1 − pct), `_fator_credor`)
    e ainda pode mudar a faixa do IR-RRA — o efeito não é linear. Por isso cada
    linha refaz `calcular_dict` variando SÓ `honorarios_contratuais_pct`.

    O % informado na `entrada` (se houver) entra na grade e a linha dele sai com
    `atual=True`; sem % informado, a linha de 0% é o cálculo atual. Linha cujo
    cálculo falhe ou não produza líquido é omitida, nunca aproximada.
    """
    pcts: list[Decimal] = []
    for pct in grade:
        if pct not in pcts:
            pcts.append(pct)
    atual = entrada.honorarios_contratuais_pct
    if atual is not None and atual not in pcts:
        pcts.append(atual)
    pcts.sort()

    linhas: list[dict] = []
    for pct in pcts:
        variante = replace(
            entrada,
            # 0% e "sem honorário" são o mesmo cálculo; None evita uma linha
            # de R$ 0,00 de contratuais na cascata do cenário.
            honorarios_contratuais_pct=pct if pct > 0 else None,
        )
        try:
            r = calcular_dict(variante)
        except Exception:  # noqa: BLE001 — linha ausente é melhor que grade quebrada
            continue
        liquido = (r.get("cenario_homologado") or {}).get("valor_liquido_atualizado")
        if liquido is None:
            continue
        linhas.append({
            "pct": str(pct),
            "liquido": str(liquido),
            "atual": (atual == pct) if atual is not None else (pct == 0),
        })
    return linhas
