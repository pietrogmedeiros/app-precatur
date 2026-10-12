"""Extração dos campos da CALCULADORA (self-contained, sem prompts do backend).

Diferente do v2 (que reusa `calculo_v6` do backend), aqui o alvo é DIRETO: os ~10
campos que o formulário da calculadora pede. Cada campo vem com citação {página,
trecho} para o advogado conferir. A tabela reconstruída + prova aritmética
(camada substrato) vão no prompt para o modelo não adivinhar a coluna.
"""
from __future__ import annotations

import re

from .llm import salvage_json

# campos → descrição no prompt (chave = key do param da calculadora)
CAMPOS = {
    "valor_total": "TOTAL da conta homologada (crédito do credor, já sem cota patronal)",
    "valor_principal": "PRINCIPAL corrigido, SEM juros (base do PSS/IR/atualização)",
    "valor_juros": "JUROS moratórios (linha de juros da conta, se destacada; senão 0)",
    "valor_selic": "SELIC já acumulada, se a conta traz num campo próprio (senão 0)",
    "valor_pss": "PSS/contribuição previdenciária descontada na conta (senão nulo)",
    "valor_ir": "IR / imposto de renda retido na conta (senão nulo)",
    "honorarios_contratuais_pct": "% de honorários CONTRATUAIS destacado (ex.: 30), senão nulo",
    "honorarios_sucumbenciais_pct": "% de honorários SUCUMBENCIAIS (ex.: 10), senão nulo",
    "data_calculo": "DATA do cálculo (AAAA-MM-DD): data em que os valores estão expressos",
    "natureza_tributaria": "natureza p/ PSS/IR: remuneratorio | previdenciario | indenizatorio | misto",
}

MAX_CHARS = 6000
MAX_LINHAS_TAB = 40


def _recortar(t: str, lim: int = MAX_CHARS) -> str:
    """Cabeça + cauda: o TOTAL fica no RODAPÉ da página; cortar só o início o perde."""
    t = t or ""
    if len(t) <= lim:
        return t
    k = int(lim * 0.45)
    return t[:k] + "\n[...corte...]\n" + t[-(lim - k):]


def _enriquecer(p: dict) -> str:
    partes = [_recortar(p.get("texto") or "")]
    orc, tab = p.get("oraculo"), p.get("tabela")
    if tab:
        if orc and orc.get("identidade") and orc.get("linhas_ok", 0) >= 2:
            ident = orc["identidade"]
            cols = " + ".join(f"col{c}" for c in ident["parcelas"])
            partes.append(f"\n[PROVA: tabela reconstruída por geometria do PDF (texto literal). "
                          f"Identidade {cols} = col{ident['col_total']} vale em "
                          f"{orc['linhas_ok']}/{orc['linhas']} linhas.]")
        else:
            partes.append("\n[TABELA reconstruída por geometria do PDF (texto literal).]")
        partes.append("[TABELA] col0=rótulo, col1..N=valores")
        for row in tab[:MAX_LINHAS_TAB]:
            partes.append("  " + " | ".join(c or "-" for c in row))
    return "\n".join(partes)


def _prompt(paginas: list[dict], a: int, b: int) -> str:
    idx = {p["pagina"]: p for p in paginas}
    trechos = []
    for pg in range(a, b + 1):
        p = idx.get(pg)
        if p:
            trechos.append(f"=== PÁGINA {pg} ===\n{_enriquecer(p)}")
    campos_txt = "\n".join(f'  "{k}": {v}' for k, v in CAMPOS.items())
    return (
        "Você extrai os campos de UMA conta de liquidação de precatório (BR) para preencher "
        "uma calculadora. Leia o trecho e devolva CADA campo abaixo. Valores em formato BR "
        "(1.234.567,89). Use a TABELA reconstruída para saber qual coluna é Principal/Juros/"
        "Selic/Total — NÃO adivinhe pela ordem do texto corrido. NÃO invente número: se o "
        "campo não estiver no trecho, use null.\n\n"
        f"CAMPOS:\n{campos_txt}\n\n"
        'Responda SOMENTE com JSON, cada campo como {"valor": <valor ou null>, '
        '"citacao_pagina": <n>, "citacao_trecho": "<trecho literal ou vazio>"}:\n'
        '{"' + '": {...}, "'.join(CAMPOS) + '": {...}}\n\n'
        "TRECHO:\n\n" + "\n\n".join(trechos)
    )


# campos do OFÍCIO REQUISITÓRIO (seções 4 e 5 da calculadora)
CAMPOS_OFICIO = {
    "honorarios_contratuais_pct": "% de honorários CONTRATUAIS destacado (ex.: 30), senão null",
    "honorarios_sucumbenciais_pct": "% de honorários SUCUMBENCIAIS (ex.: 10), senão null",
    "modalidade": "modalidade da requisição: 'precatorio' ou 'rpv'",
    "ente_devedor": "nome do ENTE devedor (quem paga: União, INSS, Estado do X, Município de Y...)",
    "data_apresentacao": "DATA de apresentação/envio do requisitório ao tribunal (AAAA-MM-DD), senão null",
    "beneficiario": "nome do BENEFICIÁRIO/credor do requisitório",
    # ⚠ DOIS números diferentes, e confundi-los é o erro fácil: o ofício tem
    # número PRÓPRIO (N/AAAA, o que o time digita em "Número Ofício" — amostra
    # real: 1453/2022, 057/2025) e cita o número CNJ do precatório.
    "numero_oficio": (
        "número do OFÍCIO REQUISITÓRIO no formato N/AAAA (ex.: 1453/2022), "
        "como aparece no cabeçalho do documento. NÃO é o número CNJ do processo"
    ),
    # 89% dos ofícios do corpus trazem um CNJ; só 23% o rotulam como "precatório
    # nº" — daí o campo dizer o que NÃO é (o originário aparece na mesma página).
    "numero_precatorio": (
        "número do PRECATÓRIO/RPV no formato CNJ (0000000-00.0000.0.00.0000). "
        "NÃO é o número do processo ORIGINÁRIO/de conhecimento, que costuma "
        "aparecer no mesmo documento. Se só houver o originário, use null"
    ),
}


def _normaliza(bruto: dict, campos_def: dict) -> dict:
    """Aceita {campo:{valor,citacao...}} ou {campo: valor}; descarta null/vazio."""
    out = {}
    for k in campos_def:
        v = bruto.get(k)
        if isinstance(v, dict):
            val = v.get("valor")
            cit = {"pagina": v.get("citacao_pagina"), "trecho": v.get("citacao_trecho")}
        else:
            val, cit = v, None
        if val not in (None, "", "null", "None"):
            out[k] = {"valor": val, "citacao": cit}
    return out


def extrair(paginas: list[dict], ref: tuple[int, int], llm) -> dict:
    """Extrai os campos da CONTA (seção 1 + natureza)."""
    a, b = ref
    txt, meta = llm.responder(_prompt(paginas, a, b))
    bruto = salvage_json(txt)
    if not bruto:
        return {"ok": False, "erro": "json inválido", "raw": (txt or "")[:300]}
    return {"ok": True, "campos": _normaliza(bruto, CAMPOS), "meta": meta}


def _prompt_oficio(paginas: list[dict], a: int, b: int) -> str:
    idx = {p["pagina"]: p for p in paginas}
    trechos = [f"=== PÁGINA {pg} ===\n{_recortar((idx[pg] or {}).get('texto') or '')}"
               for pg in range(a, b + 1) if pg in idx]
    campos_txt = "\n".join(f'  "{k}": {v}' for k, v in CAMPOS_OFICIO.items())
    return (
        "Você extrai dados de um OFÍCIO REQUISITÓRIO de precatório/RPV (BR) para uma "
        "calculadora. Percentuais em pontos (30 = 30%). NÃO invente: campo ausente = null.\n\n"
        f"CAMPOS:\n{campos_txt}\n\n"
        'Responda SOMENTE com JSON, cada campo {"valor": <v ou null>, "citacao_pagina": <n>, '
        '"citacao_trecho": "<literal ou vazio>"}:\n'
        '{"' + '": {...}, "'.join(CAMPOS_OFICIO) + '": {...}}\n\n'
        "TRECHO:\n\n" + "\n\n".join(trechos)
    )


def extrair_oficio(paginas: list[dict], ref: tuple[int, int], llm) -> dict:
    """Extrai os campos do OFÍCIO (seções 4 e 5)."""
    a, b = ref
    txt, meta = llm.responder(_prompt_oficio(paginas, a, b))
    bruto = salvage_json(txt)
    if not bruto:
        return {"ok": False, "erro": "json inválido"}
    return {"ok": True, "campos": _normaliza(bruto, CAMPOS_OFICIO), "meta": meta}


# A natureza do crédito no eixo TRIBUTÁRIO (quem decide se incide PSS e IR) não
# está na conta em 1/3 dos casos — a conta traz números, não a origem da dívida.
# Quem descreve a origem é a SENTENÇA/ACÓRDÃO. Só este campo sai daqui: pedir
# valores a uma decisão seria convidar o modelo a ler o valor errado (o da
# condenação original, não o da conta homologada).
CAMPOS_SENTENCA = {
    "natureza_tributaria": (
        "natureza do crédito no eixo tributário, UMA de: remuneratorio "
        "(salários, vencimentos, gratificações, verbas trabalhistas de ativo) | "
        "previdenciario (aposentadoria, pensão, benefício do INSS) | "
        "indenizatorio (dano moral/material, desapropriação, verba indenizatória, "
        "licença-prêmio não gozada) | misto (a condenação junta parcelas de "
        "naturezas diferentes). Se a decisão não permitir afirmar, use null"
    ),
}
# Ementa e dispositivo — começo e fim. É onde a decisão diz o que está pagando;
# o miolo é fundamentação e só encareceria o prompt (acórdãos vão a 59 páginas).
BORDA_PAGINAS = 3


def _faixa_borda(a: int, b: int, n: int = BORDA_PAGINAS) -> list[int]:
    if b - a + 1 <= 2 * n:
        return list(range(a, b + 1))
    return list(range(a, a + n)) + list(range(b - n + 1, b + 1))


def extrair_natureza(paginas: list[dict], ref: tuple[int, int], llm) -> dict:
    """Natureza tributária a partir da SENTENÇA/ACÓRDÃO (só quando a conta calou)."""
    idx = {p["pagina"]: p for p in paginas}
    trechos = [f"=== PÁGINA {pg} ===\n{_recortar((idx[pg] or {}).get('texto') or '', 4000)}"
               for pg in _faixa_borda(*ref) if pg in idx]
    if not trechos:
        return {"ok": False, "erro": "sem páginas"}
    campos_txt = "\n".join(f'  "{k}": {v}' for k, v in CAMPOS_SENTENCA.items())
    prompt = (
        "Você lê uma SENTENÇA ou ACÓRDÃO brasileiro e classifica a natureza do crédito "
        "reconhecido, para definir se incidem PSS e imposto de renda. Olhe o que a decisão "
        "MANDA PAGAR (dispositivo/ementa), não o rito. NÃO invente: em dúvida, null.\n\n"
        f"CAMPOS:\n{campos_txt}\n\n"
        'Responda SOMENTE com JSON: {"natureza_tributaria": {"valor": "<...ou null>", '
        '"citacao_pagina": <n>, "citacao_trecho": "<literal ou vazio>"}}\n\n'
        "TRECHO:\n\n" + "\n\n".join(trechos)
    )
    txt, meta = llm.responder(prompt)
    bruto = salvage_json(txt)
    if not bruto:
        return {"ok": False, "erro": "json inválido"}
    return {"ok": True, "campos": _normaliza(bruto, CAMPOS_SENTENCA), "meta": meta}
