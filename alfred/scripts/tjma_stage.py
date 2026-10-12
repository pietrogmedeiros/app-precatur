# -*- coding: utf-8 -*-
"""Estagia as Listas de Ordem Cronologica do TJMA (PDF) -> data/tjma/precatorios.json.

FONTE (portal TJMA, hotsite de precatorios -> "Listas Cronologicas", item 6847):
  item 6848  Estado do Maranhao (administracao direta e indireta)
  item 6849  Municipio de Sao Luis (administracao direta e indireta)
  item 6850  INSS e Municipios Diversos   <-- NAO ESTAGIADO, ver abaixo

Formato do PDF (identico nas tres, texto extraivel, sem OCR):
  Ordem | No Precatorio | Natureza | Orc. | Recebimento | Prioridade | Valor atualizado | Ente
Vantagens sobre outros tribunais: o valor ja vem ATUALIZADO (nao e' face) e a
superpreferencia vem MARCADA na propria linha (Idade / Doenca Grave / Deficiencia).
O credor NAO e' publicado -- o art. 12 §3o da Res. CNJ 303/2019 veda identificar o
beneficiario na lista, entao `credor` fica None (o TJMA cumpre a regra a risca).

POR QUE O ITEM 6850 FICA DE FORA: aquela lista e' uma fila unificada e NAO identifica
o ente devedor em 343 das 362 paginas (so 7% das linhas trazem a coluna preenchida).
Sem o ente nao ha fila por municipio. Ver a memoria maranhao-alvo-mapeamento.

    python scripts/tjma_stage.py            # le os PDFs de data/tjma/
"""
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

from pypdf import PdfReader

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(BASE, "data", "tjma")
SAIDA = os.path.join(DIR, "precatorios.json")

# Ordem | numero CNJ | natureza | ano | data hora | [prioridade] | valor | [ente]
LINHA = re.compile(
    r"^(\d{1,6})\s+"
    r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\s+"
    r"(Alimentar|Comum)\s+"
    r"(\d{4})\s+"
    r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s*"
    r"(.*?)\s*"
    r"([\d\.]+,\d{2})\s*"
    r"(.*)$")

# a coluna "Prioridade"/"TIPO DE CLASSIFICACAO" so' vem preenchida quando ha
# superpreferencia do art. 100 §2o; o texto varia entre os documentos.
SUPER = {"IDADE": "Idade", "DOENCA GRAVE": "Doença Grave", "DOENCA": "Doença Grave",
         "DEFICIENCIA": "Deficiência", "PESSOA COM DEFICIENCIA": "Deficiência"}


def _sa(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().strip()


def _valor(s):
    return float(s.replace(".", "").replace(",", "."))


def _data_iso(d):
    return f"{d[6:10]}-{d[3:5]}-{d[0:2]}"


def le_pdf(caminho):
    """Devolve (lista de precatorios, data_de_atualizacao_iso ou None).

    O REGIME (Geral/Especial) e' cabecalho de secao, nao coluna: propaga-se para
    baixo ate' o proximo cabecalho.
    """
    regs, regime, atualizado = [], None, None
    for pg in PdfReader(caminho).pages:
        for bruta in (pg.extract_text() or "").split("\n"):
            l = re.sub(r"[ \t]+", " ", bruta).strip()
            if not l:
                continue
            if atualizado is None:
                m = re.search(r"[Aa]tualizada?\s+at[ée]\s+(\d{2}/\d{2}/\d{4})", l)
                if m:
                    atualizado = _data_iso(m.group(1))
            up = _sa(l)
            if up.startswith("REGIME "):
                regime = "Especial" if "ESPECIAL" in up else "Comum"
                continue
            m = LINHA.match(l)
            if not m:
                continue
            prio, ente = _sa(m.group(7)), (m.group(9) or "").strip()
            regs.append({
                "ordem": int(m.group(1)),
                "numero": m.group(2),
                "natureza": m.group(3),
                "ano_orcamento": int(m.group(4)),
                "apresentacao": _data_iso(m.group(5)),
                "hora": m.group(6),
                "superpreferencia": next((v for k, v in SUPER.items() if k in prio), None),
                "valor_atualizado": _valor(m.group(8)),
                "ente": ente or None,
                "regime": regime,
            })
    return regs, atualizado


# Nome curto que o TJMA usa na coluna Ente -> nome do ente devedor.
# O Estado e Sao Luis publicam a fila da administracao DIRETA E INDIRETA junta;
# cada autarquia vira um ente proprio no banco (como TJES/TJBA), e o rateio do §23
# junta tudo pelo IBGE do municipio (ou pseudo-IBGE do Estado).
NOMES = {
    "ESTADO": "ESTADO DO MARANHÃO",
    "SAO LUIS": "MUNICÍPIO DE SÃO LUÍS",
    "SÃO LUÍS": "MUNICÍPIO DE SÃO LUÍS",
    # o TJMA escreve a MESMA autarquia de dois jeitos ao longo do documento
    # (mudou de padrao em 2023) -- unificar, senao viram dois entes no banco e a
    # fila de cada um fica pela metade.
    "DETRAN": "DETRAN/MA",
    "DETRAN/MA": "DETRAN/MA",
}


def main():
    fontes = [("lista_estado.pdf", "MA", "21"),          # pseudo-IBGE do Estado
              ("lista_saoluis.pdf", "MA", "2111300")]    # Sao Luis/MA
    entes, tot, atual = {}, 0, None
    for arq, uf, ibge in fontes:
        caminho = os.path.join(DIR, arq)
        if not os.path.exists(caminho):
            print(f"  AUSENTE: {arq} — baixe do hotsite do TJMA")
            continue
        regs, dt = le_pdf(caminho)
        atual = atual or dt
        for r in regs:
            nome = NOMES.get(_sa(r["ente"]), r["ente"] or "?")
            k = (nome, ibge)
            entes.setdefault(k, []).append(r)
        tot += len(regs)
        print(f"  {arq}: {len(regs):>6,} precatórios · atualizada até {dt}")

    saida = {"tribunal": "TJMA", "coletado_em": (atual or datetime.now(timezone.utc).date().isoformat()) + "T00:00:00+00:00",
             "fonte": "TJMA — Listas de Ordem Cronológica (hotsite/prec, itens 6848 e 6849)",
             "entes": [{"ente": nome, "uf": "MA", "ibge": ibge,
                        "precatorios": sorted(v, key=lambda x: x["ordem"])}
                       for (nome, ibge), v in sorted(entes.items())]}
    io.open(SAIDA, "w", encoding="utf-8").write(json.dumps(saida, ensure_ascii=False, indent=1))
    print(f"\n{tot:,} precatórios · {len(entes)} entes -> {SAIDA}")
    for e in saida["entes"]:
        v = sum(p["valor_atualizado"] for p in e["precatorios"])
        print(f"   {e['ente'][:38]:38s} ibge={e['ibge']:>7s} {len(e['precatorios']):>6,} · R$ {v/1e6:>8,.1f} mi")


if __name__ == "__main__":
    main()
