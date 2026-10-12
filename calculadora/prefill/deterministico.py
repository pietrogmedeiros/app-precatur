"""Extração DETERMINÍSTICA de campos com padrão textual confiável (regex, 0 LLM).

Princípio da investigação: campo estruturado (rótulo + valor) = regex, não LLM.
O LLM oscila (num run pega os 20% do honorário contratual, no outro não); o regex
sobre "Percentual dos honorários contratuais (%): 20" acerta 100% das vezes.

Roda como REDE DE SEGURANÇA: preenche o que o LLM deixou passar; onde os dois acham
e DIVERGEM, o chamador sinaliza (nunca aceite silencioso).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_PCT = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%")
_CHAVES = {
    # "honorários contratuais", "honorários advocatícios contratuais"
    "honorarios_contratuais_pct": re.compile(r"honor\w*(?:\s+advocat\w+)?\s+contratu", re.I),
    "honorarios_sucumbenciais_pct": re.compile(r"honor\w*(?:\s+advocat\w+)?\s+sucumb|\bsucumb[êe]nci", re.I),
}


# Número CNJ: 7 dígitos-2 dígitos.ano.J.TR.4 dígitos. Formato FECHADO — é o caso
# limite do princípio acima, e o LLM erra por excesso de cautela: no 1653 o
# número estava três vezes no ofício e ele devolveu null, porque o documento não
# o rotula como "precatório nº".
_CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")


def numero_cnj(paginas: list[str]) -> dict:
    """Número CNJ do requisitório — SÓ quando é inequívoco.

    O ofício costuma citar o processo de ORIGEM junto com o do precatório, e
    distinguir os dois pelo texto é justamente o julgamento que o regex não sabe
    fazer. Então a regra é dura: **um único número distinto no documento** vira
    campo; dois ou mais = abstenção, e a decisão fica com o LLM/advogado.
    """
    achados: dict[str, tuple[int, str]] = {}
    for i, texto in enumerate(paginas, start=1):
        t = texto or ""
        for m in _CNJ.finditer(t):
            achados.setdefault(m.group(0), (i, re.sub(r"\s+", " ", t[max(0, m.start() - 45): m.end()]).strip()[:90]))
    if len(achados) != 1:
        return {}
    num, (pag, trecho) = next(iter(achados.items()))
    return {"numero_precatorio": {"valor": num, "citacao": {"pagina": pag, "trecho": trecho},
                                  "fonte": "regex"}}


def honorarios(paginas: list[str]) -> dict:
    """{campo: {valor, citacao{pagina,trecho}, fonte:'regex'}} p/ honorários %."""
    out: dict = {}
    for i, texto in enumerate(paginas, start=1):
        t = texto or ""
        for campo, chave in _CHAVES.items():
            if campo in out:
                continue
            for m in chave.finditer(t):
                # o valor costuma vir logo APÓS o rótulo (inclui o "(%):\n20 %")
                seg = t[m.end(): m.end() + 120]
                pm = _PCT.search(seg)
                if not pm:
                    continue
                try:
                    v = float(pm.group(1).replace(".", "").replace(",", "."))
                except ValueError:
                    continue
                if 0 < v <= 100:
                    trecho = re.sub(r"\s+", " ", t[m.start(): m.end() + 40]).strip()[:90]
                    out[campo] = {"valor": pm.group(1),
                                  "citacao": {"pagina": i, "trecho": trecho},
                                  "fonte": "regex"}
                    break
    return out


# ── PRESENÇA LITERAL do valor na conta: a trava da AGREGAÇÃO ─────────────
# O extrator às vezes SOMA duas células reais e devolve um número que não está
# no documento — quase sempre "Total Partes" + "Total de Sucumbências" (medido
# no ledger, set/2026: 19 campos, ~23 com os latentes). A citação reescrita
# denuncia a soma ("Total Partes -> X; Total de Sucumbências -> Y"), e a prova
# P+J+S=T FECHA, porque todas as parcelas vêm somadas do mesmo jeito: a tela
# mostrava "✅ A conta fecha" num valor que não existe.
#
# ⚠ O que separa esses casos NÃO é a literalidade do TRECHO citado (39% das
# citações de valores CORRETOS também vêm reescritas), e sim o VALOR final não
# aparecer em página nenhuma da conta. Por isso a regra olha o valor, não a
# citação — e é também por isso que o `citation_validator` do PrecaturIA não
# serve aqui: ele valida o trecho e, ao falhar, anula só a citação.
#
# Formatos aceitos, todos vistos em conta real: brasileiro com e sem ponto de
# milhar (1.234,56 / 1234,56), americano (71,928.65) e milhar por espaço
# (97 649,59). A comparação é por TOKEN numérico, nunca por substring: 1.000,00
# não pode "achar" 11.000,00.
_TOKEN_BR = re.compile(r"(?<![\d.,])\d{1,3}(?:\.?\d{3})*,\d{2}(?!\d)")
_TOKEN_US = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+\.\d{2}(?!\d)")
_TOKEN_ESPACO = re.compile(r"(?<![\d.,])\d{1,3}(?: \d{3})+,\d{2}(?!\d)")


def centavos(valor) -> int | None:
    """Valor monetário (str/número) → centavos inteiros; None se não for número.

    Aceita "R$ 1.234,56", "1234,56", "1.234" (milhar BR, sem centavos) e
    "1234.56" (decimal com ponto, como o modelo às vezes devolve).
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return int(round(valor * 100))
    s = re.sub(r"[^\d.,-]", "", str(valor))
    if not re.search(r"\d", s):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif not re.fullmatch(r"-?\d+\.\d{1,2}", s):
        s = s.replace(".", "")          # ponto de milhar, sem centavos
    try:
        return int((Decimal(s) * 100).quantize(Decimal("1")))
    except InvalidOperation:
        return None


def _tokens(texto: str) -> set[int]:
    out = {centavos(t) for t in _TOKEN_BR.findall(texto or "")}
    out |= {centavos(t.replace(",", "")) for t in _TOKEN_US.findall(texto or "")}
    out |= {centavos(t.replace(" ", ".")) for t in _TOKEN_ESPACO.findall(texto or "")}
    out.discard(None)
    return out


def paginas_com_valor(valor, paginas: list[dict]) -> list[int]:
    """Números das páginas (texto OU célula da tabela) em que o valor aparece."""
    alvo = centavos(valor)
    if alvo is None:
        return []
    achou = []
    for p in paginas:
        toks = _tokens(p.get("texto") or "")
        for linha in p.get("tabela") or []:
            for cel in linha:
                toks |= _tokens(cel or "")
        if alvo in toks:
            achou.append(p.get("pagina"))
    return achou


def valor_presente(valor, paginas: list[dict]) -> bool:
    """O valor existe literalmente em alguma das `paginas` (substrato)?

    Zero é ISENTO: o prompt manda devolver 0 quando a conta não destaca juros
    ou SELIC — um zero legítimo não precisa estar escrito no documento. Valor
    que nem é número não passa. Só as páginas recebidas contam: quem chama
    decide o escopo (a CONTA — o que o extrator leu), e o mesmo número numa
    outra peça não salva um valor que o modelo compôs.
    """
    alvo = centavos(valor)
    if alvo is None:
        return False
    if alvo == 0:
        return True
    return bool(paginas_com_valor(valor, paginas))
