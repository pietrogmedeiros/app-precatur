"""Mede a rotulagem de páginas ANTES × DEPOIS do catálogo de marcadores, usando
como gabarito as peças que o advogado anexou nos cards do Bitrix
("Anexo - Cálculos Homologados", "Anexo - Ofício", "Anexo - Sentença / Acórdão").

    calculadora/.venv/bin/python scripts/elastic/avaliar_bitrix.py --cards 300

É a mesma régua do levantamento de 28/10/2026: "a peça que o advogado recortou
é reconhecida como o tipo dela?" (cobertura) e "é confundida com o outro tipo?"
(confusão). A sentença entra como NEGATIVO: o ideal é não virar conta nem ofício.

⚠ PII: os PDFs são baixados para a MEMÓRIA, lidos e descartados. Nada do
documento vai para disco nem para o Elasticsearch: o índice
`precatur-avaliacao-paginas` recebe só tipo, página, marcadores e contagens,
com o card como hash. O que sai na tela é agregado por tribunal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx

sys.stdout.reconfigure(line_buffering=True)  # progresso visível mesmo indo para arquivo

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "calculadora"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prefill import marcadores as M  # noqa: E402
from prefill import telemetria as T  # noqa: E402
from prefill.pipeline import TIPO_CONTA, TIPO_OFICIO, _label_pagina  # noqa: E402
from prefill.substrato import processar_pdf  # noqa: E402

import precatur_es as ES  # noqa: E402

IDX = "precatur-avaliacao-paginas"

# ── a regra ANTES (pipeline.py em f51028c, copiada literalmente) ─────────
_ANTES_CONTA = re.compile(
    r"projef|resumo do c[áa]lculo|c[áa]lculos judiciais|\bsicar\b|demonstrativo de c[áa]lculo|"
    r"mem[óo]ria de c[áa]lculo|e-?pcalc|pje-?calc|pfe-?inss|diferen[çc]a devida|"
    r"dados da liquida[çc][ãa]o|conta de liquida[çc][ãa]o", re.I)
_ANTES_OFICIO = re.compile(
    r"of[íi]cio\s+requisit[óo]rio|requisi[çc][ãa]o\s+de\s+pagamento|"
    r"requisi[çc][ãa]o\s+de\s+pequeno\s+valor|\bRPV\b|"
    r"n[º.]?\s*(?:do\s+)?(?:of[íi]cio|precat[óo]rio|requisit[óo]rio)", re.I)


def antes(p: dict) -> str | None:
    if _ANTES_CONTA.search(p.get("texto") or "") or ((p.get("oraculo") or {}).get("razao") or 0) >= 0.5:
        return TIPO_CONTA
    if _ANTES_OFICIO.search(p.get("texto") or ""):
        return TIPO_OFICIO
    return None


def depois(p: dict) -> str | None:
    return _label_pagina(p, p.get("pagina"), None)


CURTO = {TIPO_CONTA: "conta", TIPO_OFICIO: "oficio", None: "outro"}
PECAS = {"anexo_conta": "conta", "anexo_oficio": "oficio", "anexo_sentenca": "sentenca"}


# ── Bitrix ───────────────────────────────────────────────────────────────
def _webhook() -> str:
    wh = ES.ENV.get("BITRIX_WEBHOOK") or ES._env().get("BITRIX_WEBHOOK_BASE") or ""
    if not wh:
        arq = RAIZ / ".env"
        for ln in arq.read_text().splitlines():
            if ln.startswith("BITRIX_WEBHOOK_BASE="):
                wh = ln.split("=", 1)[1].strip()
    if not wh:
        sys.exit("BITRIX_WEBHOOK_BASE não encontrado no .env")
    return wh.rstrip("/")


def _campos() -> dict:
    c = json.loads((RAIZ / "calculadora" / "bitrix_campos.json").read_text())["campos"]
    return {k: c[k]["id"] for k in (*PECAS, "numero_precatorio")}


def listar(wh: str, f: dict, n: int, pular: int = 0) -> list[dict]:
    """Cards com conta E ofício anexados, do mais novo para o mais velho."""
    out, start = [], 0
    while len(out) < n + pular:
        r = httpx.post(f"{wh}/crm.deal.list.json", timeout=60, json={
            "filter": {f"!{f['anexo_conta']}": "", f"!{f['anexo_oficio']}": ""},
            "select": ["ID", *f.values()], "order": {"ID": "DESC"}, "start": start}).json()
        out += r.get("result") or []
        if "next" not in r:
            break
        start = r["next"]
    return out[pular:pular + n]


def _camel(uf: str) -> str:
    """UF_CRM_123 (crm.deal.*) → ufCrm_123 (crm.item.*)."""
    return "ufCrm_" + uf.split("UF_CRM_", 1)[1]


def links(wh: str, deal_id, f: dict) -> dict:
    """{peça: urlMachine}. O `downloadUrl` do crm.deal.* exige sessão de
    navegador; o `urlMachine` do crm.item.get é o que aceita o webhook."""
    it = (httpx.post(f"{wh}/crm.item.get.json", timeout=60,
                     json={"entityTypeId": 2, "id": int(deal_id)}).json().get("result") or {}).get("item") or {}
    out = {}
    for campo, peca in PECAS.items():
        v = it.get(_camel(f[campo]))
        v = v[0] if isinstance(v, list) and v else v
        if isinstance(v, dict) and v.get("urlMachine"):
            out[peca] = v["urlMachine"]
    return out


_PRIMEIRA_FALHA: list[str] = []


def baixar(url: str) -> bytes | None:
    r = httpx.get(url, follow_redirects=True, timeout=120)
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        return r.content
    if not _PRIMEIRA_FALHA:
        _PRIMEIRA_FALHA.append(f"HTTP {r.status_code}, {r.headers.get('content-type')}, começa com {r.content[:8]!r}")
    return None


# ── mineração (só texto que se repete entre cards: o formulário, não a parte) ──
_PII = re.compile(r"@|\d{3}\.\d{3}\.\d{3}|cpf|cnpj|rg\b|\boab\b|advogad|nome\b|rua |av\. |cep|"
                  r"assinado eletronicamente|assinatura")
# A linha só entra se tiver vocabulário de FORMULÁRIO. Sem isto, a lista de
# beneficiários de uma conta coletiva (o mesmo PDF anexado em 6 cards do TRF5)
# passou como "termo recorrente" — eram nomes de pessoas (28/10/2026).
_FORMULARIO = frozenset("""total subtotal valor valores juros principal data calculo calculos honorarios
processo requisicao precatorio oficio credito natureza beneficiario devedor tribunal justica poder
judiciario estado federal vara juizo correcao atualizacao atualizado selic ipca geral devido liquido
bruto desagio resumo planilha conta sentenca acordao pagamento requisitorio alimentar comum indice
periodo competencia parcela sucumbencia sucumbencias custas pss imposto renda previdencia inss uniao
municipio fazenda exequente executado credor requisitado originario execucao cumprimento liquidacao
contadoria demonstrativo memoria base corrigido moratorios rpv expedicao numero cnj""".split())


def _linhas(paginas: list[dict]) -> set[str]:
    out = set()
    for p in paginas[:4]:  # cabeçalho e 1ªs páginas: é onde o formulário se identifica
        for ln in (p.get("texto") or "").splitlines():
            n = re.sub(r"\d", "#", M.normalizar(ln)).strip(" .:-")
            if (8 <= len(n) <= 90 and sum(ch.isalpha() for ch in n) >= 6 and not _PII.search(n)
                    and _FORMULARIO & set(re.findall(r"[a-z]+", n))):
                out.add(n)
    return out


def minerar(nao_rec, por_peca, minimo: int) -> list[dict]:
    """Linhas recorrentes nas peças NÃO reconhecidas e raras nas outras peças."""
    docs, vistos = [], set()
    print("\ncandidatos a marcador (linhas em >= %d documentos distintos das peças não reconhecidas):" % minimo)
    for (trib, peca), linhas in sorted(nao_rec.items(), key=lambda kv: (kv[0][0] != "TOTAL", kv[0])):
        top = []
        for ln, cards in linhas.items():
            if len(cards) < minimo:
                continue
            fora = sum(len(d.get(ln, ())) for pc, d in por_peca.items() if pc != peca)
            dentro = len(por_peca[peca].get(ln, ()))
            espec = dentro / (dentro + fora) if dentro + fora else 0
            if espec >= 0.8:
                top.append((len(cards), espec, ln))
        top.sort(reverse=True)
        if not top:
            continue
        print(f"  {trib} · {peca}")
        for n, espec, ln in top[:12]:
            print(f"    {n:3} documentos · especificidade {espec:.2f} · {ln}")
            chave = (peca, ln)
            if chave in vistos:
                continue
            vistos.add(chave)
            docs.append({
                "id": "termo_minerado:bitrix:%s:%s" % (peca, hashlib.sha1(ln.encode()).hexdigest()[:12]),
                "tipo_registro": "termo_minerado",
                "tipo_documento": ["calculo_homologado" if peca == "conta" else peca],
                "papel": "candidato_a_marcador", "termos": [ln], "status": "candidato",
                "tribunal": [trib if trib != "TOTAL" else "*"],
                "evidencia": {"documentos_nao_reconhecidos": n, "especificidade": round(espec, 3)},
                "origem": {"arquivo": "anexos dos cards do Bitrix", "simbolo": "avaliar_bitrix.minerar"},
                "observacao": "Linha recorrente nas peças que a regra nova não reconheceu. Exige curadoria.",
                "atualizado_em": T._agora()[:10],
            })
    return docs


def gravar(docs: list, lote: int = 100) -> None:
    """_bulk em lotes pequenos, com pausa e nova tentativa. O Elastic da VM tem
    1 GB de RAM: lotes de 500 páginas o derrubaram no meio (28/10/2026)."""
    import time
    for k in range(0, len(docs), lote):
        corpo = "".join(json.dumps(x, ensure_ascii=False) + "\n" for par in docs[k:k + lote] for x in par)
        for tentativa in range(5):
            try:
                st, r = ES.es("POST", "/_bulk", corpo, ndjson=True)
                if st == 200 and not r.get("errors"):
                    break
            except Exception:  # noqa: BLE001 — conexão caiu: espera o Elastic voltar
                pass
            time.sleep(10 * (tentativa + 1))
        else:
            print(f"! lote {k // lote + 1} não gravou depois de 5 tentativas")
        time.sleep(0.5)


# ── medição ──────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", type=int, default=200)
    ap.add_argument("--sem-elastic", action="store_true")
    ap.add_argument("--pular", type=int, default=0,
                    help="pula os N cards mais recentes (ex.: 300 = amostra nova, nunca usada para ajustar)")
    ap.add_argument("--min-cards", type=int, default=5,
                    help="mineração: linha precisa se repetir em N cards distintos")
    a = ap.parse_args()
    wh, f = _webhook(), _campos()
    cards = listar(wh, f, a.cards, a.pular)
    print(f"{len(cards)} cards com conta e ofício anexados (pulando os {a.pular} mais recentes)")

    # (tribunal, peça) → contadores; "peça reconhecida" = alguma página dela
    # recebe o rótulo do próprio tipo
    tab = defaultdict(lambda: defaultdict(int))
    # mineração: (tribunal, peça) → linha → cards distintos; só das peças que a
    # regra nova NÃO reconheceu, e o total por peça para medir especificidade
    nao_reconhecidas = defaultdict(lambda: defaultdict(set))
    por_peca = defaultdict(lambda: defaultdict(set))
    docs = []
    falhas = 0
    for i, card in enumerate(cards, 1):
        cnj = str(card.get(f["numero_precatorio"]) or "")
        trib = T.sinais_processo([{"texto": cnj}])["tribunal"] or "DESCONHECIDO"
        cid = hashlib.sha256(f"bitrix:{card['ID']}".encode()).hexdigest()[:16]
        try:
            urls = links(wh, card["ID"], f)
        except Exception:  # noqa: BLE001
            urls = {}
        for peca, url in urls.items():
            try:
                pdf = baixar(url)
            except Exception:  # noqa: BLE001
                pdf = None
            if not pdf:
                falhas += 1
                continue
            try:
                paginas = processar_pdf(pdf)
            except Exception:  # noqa: BLE001
                falhas += 1
                continue
            doc_id = hashlib.sha256(pdf).hexdigest()[:16]  # o mesmo PDF em vários cards conta 1
            del pdf
            com_texto = [p for p in paginas if p.get("nativa")]
            for chave in (trib, "TOTAL"):
                c = tab[(chave, peca)]
                c["pecas"] += 1
                if not com_texto:
                    c["escaneadas"] += 1
                    continue
                c["com_texto"] += 1
                for nome, fn in (("antes", antes), ("depois", depois)):
                    rot = {CURTO[fn(p)] for p in com_texto}
                    if peca in rot:
                        c[f"{nome}_ok"] += 1
                    outros = rot - {peca, "outro"}
                    if outros:
                        c[f"{nome}_confunde"] += 1
            linhas = _linhas(com_texto)
            for ln in linhas:
                por_peca[peca][ln].add(doc_id)
            if com_texto and peca != "sentenca" and peca not in {CURTO[depois(p)] for p in com_texto}:
                for ln in linhas:
                    nao_reconhecidas[(trib, peca)][ln].add(doc_id)
                    nao_reconhecidas[("TOTAL", peca)][ln].add(doc_id)
            for p in com_texto:
                cls = M.classificar(p.get("texto") or "")
                docs.append(({"index": {"_index": IDX, "_id": f"{cid}:{peca}:{p['pagina']}"}}, {
                    "@timestamp": T._agora(), "analise_id": cid, "versao": "offline-bitrix",
                    "pagina": p["pagina"], "tribunal": trib, "justica": None,
                    "sistema_processual": T.sinais_processo([p])["sistema_processual"],
                    "nativa": True, "n_caracteres": len(p.get("texto") or ""),
                    "n_valores": len(M._VALOR.findall(p.get("texto") or "")),
                    "oraculo_razao": (p.get("oraculo") or {}).get("razao"),
                    "tipo_classificador": cls["tipo"] or "indefinido", "nivel": cls["nivel"],
                    "marcadores": cls["marcadores"], "provisorio": cls["provisorio"],
                    "rotulo_sistema": (cls["sistema"] or {}).get("rotulo"),
                    "tipo_sugerido": CURTO[antes(p)], "origem_sugestao": "regra_antiga",
                    "tipo_confirmado": peca,
                    "classificador_acertou": (cls["tipo"] or "outro") == peca,
                }))
        if i % 25 == 0:
            print(f"  {i}/{len(cards)} cards")
    print(f"peças que não baixaram ou não abriram: {falhas}"
          + (f" (1ª falha: {_PRIMEIRA_FALHA[0]})" if _PRIMEIRA_FALHA else "") + "\n")

    def pct(x, n):
        return f"{x / n:.0%}" if n else "—"

    print(f"{'tribunal':12} {'peça':9} {'n':>4} {'escan':>5} {'antes':>6} {'depois':>6} "
          f"{'confunde antes':>14} {'depois':>6}")
    linhas = sorted(tab.items(), key=lambda kv: (kv[0][0] != "TOTAL", -kv[1]["pecas"], kv[0]))
    for (trib, peca), c in linhas:
        n = c["com_texto"]
        if trib != "TOTAL" and n < 5:
            continue
        print(f"{trib:12} {peca:9} {c['pecas']:4} {c['escaneadas']:5} {pct(c['antes_ok'], n):>6} "
              f"{pct(c['depois_ok'], n):>6} {pct(c['antes_confunde'], n):>14} {pct(c['depois_confunde'], n):>6}")
    json.dump({f"{k[0]}|{k[1]}": v for k, v in tab.items()},
              open(os.environ.get("AVALIACAO_SAIDA", "/dev/null"), "w"), indent=1)

    candidatos = minerar(nao_reconhecidas, por_peca, a.min_cards)

    if a.sem_elastic or not docs:
        return
    st, _ = ES.es("HEAD", f"/_alias/{IDX}")
    if st != 200:
        m = json.loads((Path(__file__).parent / "pre_analises_paginas.mapping.json").read_text())
        m["aliases"] = {IDX: {"is_write_index": True}}
        ES.es("PUT", f"/{IDX}-v1", m)
    gravar(docs)
    ES.es("POST", f"/{IDX}/_refresh")
    print(f"\n{len(docs)} páginas no índice {IDX} (sem texto)")
    if candidatos:
        ES._bulk("precatur-palavras-chave", candidatos)
        print(f"{len(candidatos)} termos candidatos em precatur-palavras-chave (status=candidato, origem bitrix)")


if __name__ == "__main__":
    main()
