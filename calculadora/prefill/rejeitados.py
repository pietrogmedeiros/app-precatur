"""Valores RECUSADOS pelo prefill: o que a tela mostra, o que viaja, o que o ledger guarda.

`_montar_resultado` tira da proposta todo vt/vp/vj/vs que não existe na conta
(a trava da agregação — ver `deterministico.valor_presente`) e os devolve em
`res["rejeitados"]`. Este módulo é a metade de cá: as TRÊS telas que mostram o
resultado do prefill (pré-análise, assistente de corte e o "Anexar processo"
da calculadora) usam as mesmas funções, para o aviso, o "usar mesmo assim" e o
registro não divergirem entre elas.

Leve de propósito — só `json`. A calculadora importa isto mesmo com
PREFILL_ENABLED desligado (é ela que lê `rej` no envio ao ledger), e não pode
arrastar pymupdf/numpy/httpx junto.

O que viaja na query string (`rej`): JSON compacto, uma entrada por campo
recusado — p (param), v (valor recusado), u (1 = advogado usou mesmo assim),
t (início do trecho citado). Vai no link porque as telas e a calculadora são
aplicações separadas: a query string é o único transporte entre elas.
"""
from __future__ import annotations

import json

ROTULO = {"valor_total": "Valor total", "valor_principal": "Principal",
          "valor_juros": "Juros", "valor_selic": "SELIC"}
_MAX_TRECHO = 160


def _trecho(r: dict) -> str:
    return ((r.get("citacao") or {}).get("trecho") or "").strip()


def mensagem(r: dict) -> str:
    """Texto do aviso. Diz o que foi feito (campo VAZIO), por quê, e o que fazer.

    ⚠ Não afirma QUE tipo de soma é (a regra rejeita toda ausência da conta,
    não só a mistura com honorário/sucumbência — medido: separar por
    vocabulário perde 21 de 55 agregações conhecidas para ganhar pouco). Dizer
    "quase sempre partes + sucumbências" induziria desconfiança errada nas
    somas LEGÍTIMAS que também caem aqui (dois períodos do mesmo credor, duas
    parcelas iguais) — ver casos_eval_ledger/somas_aceitas_para_matheus.md.
    """
    rot = ROTULO.get(r.get("campo"), r.get("campo"))
    msg = (f"🚫 **{rot}**: a IA propôs `{r.get('valor')}`, mas esse número **não existe em "
           f"nenhuma página da conta** — o campo foi deixado **vazio**. Pode ser a soma de "
           f"linhas: **legítima** quando são verbas ou períodos do mesmo credor, **indevida** "
           f"quando entra honorário ou sucumbência. Confira antes de usar.")
    tr = _trecho(r)
    if tr:
        msg += f"\n\nTrecho citado pela IA: _{tr}_"
    msg += "\n\nConfira na conta e digite o valor certo na calculadora."
    if r.get("conta_por_ocr"):
        msg += (" ⚠️ A conta foi lida por **OCR**: se o número estiver na página com algum "
                "dígito ilegível, este aviso pode ser falso.")
    return msg


def codificar(rejeitados: list[dict] | None, usados: set[str] | None = None) -> str | None:
    if not rejeitados:
        return None
    usados = usados or set()
    return json.dumps([{"p": r.get("param"), "v": r.get("valor"),
                        "u": 1 if r.get("param") in usados else 0,
                        "t": _trecho(r)[:_MAX_TRECHO]} for r in rejeitados],
                      ensure_ascii=False, separators=(",", ":"))


def decodificar(s) -> list[dict]:
    """Tolerante: `rej` ausente, lista (AppTest) ou lixo viram lista vazia."""
    if isinstance(s, list):
        s = s[0] if s else None
    if not s:
        return []
    try:
        dados = json.loads(s)
    except (TypeError, ValueError):
        return []
    return [d for d in dados if isinstance(d, dict) and d.get("p")] if isinstance(dados, list) else []


def aplicar(query: dict, rejeitados: list[dict] | None, usados: set[str] | None = None) -> dict:
    """Query do link: devolve os valores que o advogado mandou usar e anexa `rej`."""
    q = dict(query)
    usados = usados or set()
    for r in rejeitados or []:
        if r.get("param") in usados:
            q[r["param"]] = str(r.get("valor"))
    rej = codificar(rejeitados, usados)
    if rej:
        q["rej"] = rej
    return q


def observacao(rej: list[dict]) -> str | None:
    """Texto para `observacao` do ledger. JSON, para o eval conseguir ler de volta.

    Vai na observação, e não como chave extra em `proposto`, porque o `_diff` do
    hub compara pela UNIÃO das chaves: `vp_rejeitado` viraria uma "correção".
    """
    if not rej:
        return None
    return json.dumps({"prefill_rejeitados": [
        {"campo": d.get("p"), "valor": d.get("v"), "usado_mesmo_assim": bool(d.get("u")),
         "trecho": d.get("t") or ""} for d in rej]}, ensure_ascii=False)


def mostrar(st, rejeitados: list[dict] | None, prefixo: str) -> set[str]:
    """Um `st.error` por campo recusado + a opção "usar mesmo assim".

    Devolve os params que o advogado mandou usar. `st` é injetado para este
    módulo não importar streamlit (é importado pela calculadora no envio).
    """
    usados: set[str] = set()
    for r in rejeitados or []:
        st.error(mensagem(r))
        if st.checkbox(f"Usar `{r.get('valor')}` mesmo assim ({ROTULO.get(r.get('campo'), r.get('campo'))})",
                       key=f"{prefixo}_usar_{r.get('param')}"):
            usados.add(r.get("param"))
    return usados
