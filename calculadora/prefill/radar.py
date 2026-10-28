"""Pipeline v2 — CAMADA 2: radar (recupera candidatos, garante cobertura).

Papel: localizar TODAS as páginas que podem conter conta de liquidação ou ofício
requisitório — inclusive em layout sem adapter regex (TJRJ, TRT). Não decide nada;
só entrega candidatos ao juiz. Medido na fase 0c/0d: acha a conta perdida da NEUZA
em rank 1, e cobre os 2 ofícios distintos da VANDERLINA (multi-ofício).

3 canais fundidos por RRF (Reciprocal Rank Fusion):
  D = denso (embedding e5) com bateria de queries por tipo de layout
  B = BM25 lexical (tokens exatos: "RESUMO DO CÁLCULO", "Projef", "SICAR"...)
  E = estrutural determinístico (página tem tabela que FECHA aritmeticamente)

Depois: MMR (evita encher o top-k com N páginas da MESMA conta) → corte adaptativo
(não top-k fixo: o doc decide quantas contas tem) → merge em runs contíguos →
expansão de borda enquanto a vizinha continua parecendo conta.

Embeddings via `transformers` puro (sem sentence-transformers → sem sklearn/scipy).
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict

import numpy as np

from .marcadores import conta_forte

MODELO_EMB = "intfloat/multilingual-e5-base"

QUERIES = {
    "conta_projef": "RESUMO DO CÁLCULO Projef cálculos judiciais principal corrigido juros moratórios selic total",
    "conta_sicar": "SICAR sistema de cálculo de atualização de requisitório valor atualizado",
    "conta_pjecalc": "PJe-Calc e-Pcalc demonstrativo de cálculo de liquidação trabalhista",
    "conta_diferencas": "planilha de diferenças por competência: diferença lançada, índice de correção, valor corrigido, diferença devida",
    "conta_liquidacao": "dados da liquidação valores de principal atualizado e juros",
    "conta_generica": "conta de liquidação homologada demonstrativo da contadoria judicial valor total da execução",
    "oficio_prec": "ofício requisitório de precatório requisição de pagamento beneficiário valor do crédito",
    "oficio_rpv": "requisição de pequeno valor RPV valor requisitado",
}

BM25_QUERIES = {
    "bm_projef": "resumo do calculo projef",
    "bm_sicar": "sicar atualizacao requisitorio",
    "bm_pjecalc": "pje-calc e-pcalc",
    "bm_difer": "diferenca lancada diferenca devida valor corrigido competencia",
    "bm_dadosliq": "dados da liquidacao",
    "bm_reqpag": "requisicao de pagamento requisitorio precatorio rpv",
    # levantamento 28/10/2026: o formulário da Res. CNJ 303/2019 (TJMG) e a
    # totalização da contadoria/Projef, que os termos acima não alcançavam
    "bm_res303": "requisicao para pagamento de precatorio beneficiario principal juizo de origem",
    "bm_totaliz": "total partes totalizacao sucumbencias criterios parametros calculo",
}

RRF_K = 60
RANK_CAP = 30
MMR_LAMBDA = 0.75
CORTE_FRACAO = 0.35      # mantém quem tiver ≥35% do score do topo (adaptativo)
MAX_PAGINAS = 40
EXPANDIR_BORDA = 3

_FORTE = re.compile(
    r"projef|resumo do c[áa]lculo|c[áa]lculos judiciais|\bsicar\b|demonstrativo de c[áa]lculo|"
    r"mem[óo]ria de c[áa]lculo|e-?pcalc|pje-?calc|pfe-?inss|diferen[çc]a devida|"
    r"dados da liquida[çc][ãa]o|requisi[çc][ãa]o de pagamento", re.I)


def _norm_tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9][a-z0-9\-]+", s.lower())


class Embedder:
    """e5 via transformers puro: mean-pooling mascarado + L2. Sem sklearn/scipy."""

    def __init__(self, modelo: str = MODELO_EMB, device: str | None = None):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(modelo)
        self.model = AutoModel.from_pretrained(modelo).to(self.device).eval()

    def encode(self, textos: list[str], prefixo: str, batch: int = 16) -> np.ndarray:
        torch = self.torch
        saidas = []
        for i in range(0, len(textos), batch):
            lote = [f"{prefixo}: {(t or ' ')[:4000]}" for t in textos[i:i + batch]]
            enc = self.tok(lote, padding=True, truncation=True, max_length=512,
                           return_tensors="pt").to(self.device)
            with torch.no_grad():
                out = self.model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (out * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            saidas.append(pooled.cpu().numpy())
        return np.vstack(saidas) if saidas else np.zeros((0, 768))


class BM25:
    def __init__(self, docs: list[list[str]], k1=1.5, b=0.75):
        self.k1, self.b, self.N = k1, b, max(len(docs), 1)
        self.dl = [len(d) for d in docs]
        self.avgdl = sum(self.dl) / self.N if self.N else 1.0
        self.tf = [defaultdict(int) for _ in docs]
        df = defaultdict(int)
        for i, d in enumerate(docs):
            for t in d:
                self.tf[i][t] += 1
            for t in set(d):
                df[t] += 1
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def score(self, q: list[str]) -> np.ndarray:
        out = np.zeros(self.N)
        for i in range(self.N):
            s, dl = 0.0, self.dl[i] or 1
            for t in q:
                f = self.tf[i].get(t, 0)
                if f:
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out[i] = s
        return out


def _runs(paginas: set[int]) -> list[tuple[int, int]]:
    if not paginas:
        return []
    ps = sorted(paginas)
    out, a, b = [], ps[0], ps[0]
    for p in ps[1:]:
        if p == b + 1:
            b = p
        else:
            out.append((a, b)); a = b = p
    out.append((a, b))
    return out


def parece_conta(pag: dict) -> bool:
    """Sinal DETERMINÍSTICO: cabeçalho de sistema OU tabela que fecha a aritmética."""
    if _FORTE.search(pag.get("texto") or "") or conta_forte(pag.get("texto") or ""):
        return True
    orc = pag.get("oraculo")
    return bool(orc and orc.get("razao", 0) >= 0.5)


def buscar(paginas: list[dict], embedder: Embedder | None = None) -> dict:
    """Devolve {runs, scores, paginas_sel} — os candidatos que vão ao juiz."""
    n = len(paginas)
    if n == 0:
        return {"runs": [], "paginas_sel": [], "canais": {}}
    textos = [p.get("texto") or "" for p in paginas]
    rrf = np.zeros(n)
    canais: dict[int, set] = defaultdict(set)

    def somar(scores: np.ndarray, nome: str):
        ordem = np.argsort(-scores)[:RANK_CAP]
        for r, i in enumerate(ordem):
            if scores[i] <= 0:
                break
            rrf[i] += 1.0 / (RRF_K + r + 1)
            canais[int(i)].add(nome)

    # canal DENSO
    emb = None
    if embedder is not None:
        emb = embedder.encode(textos, "passage")
        qv = embedder.encode(list(QUERIES.values()), "query")
        for qi, qn in enumerate(QUERIES):
            somar(emb @ qv[qi], f"D:{qn}")

    # canal LEXICAL
    bm = BM25([_norm_tokens(t[:6000]) for t in textos])
    for qn, q in BM25_QUERIES.items():
        somar(bm.score(_norm_tokens(q)), f"B:{qn}")

    # canal ESTRUTURAL determinístico (não depende de modelo).
    # Graduado: página cuja tabela FECHA a aritmética (resumo/totalização) pontua
    # mais que página que só tem cabeçalho, e MUITO mais que listagem de detalhe.
    # Sem isso o radar tratava detalhe e resumo como iguais e o juiz escolhia a
    # listagem mensal, perdendo o total (causa da extração vazia em IONE).
    est = []
    for p in paginas:
        orc = p.get("oraculo") or {}
        razao = orc.get("razao", 0.0) or 0.0
        s = 0.0
        if _FORTE.search(p.get("texto") or "") or conta_forte(p.get("texto") or ""):
            s += 1.0
        if razao >= 0.5:
            s += 1.5 + razao      # tabela que fecha = forte sinal de conta operativa
        elif razao > 0:
            s += 0.5
        est.append(s)
    somar(np.array(est), "E:estrutural")

    # MMR + corte adaptativo
    ordem = list(np.argsort(-rrf))
    topo = rrf[ordem[0]] if len(ordem) else 0.0
    sel: list[int] = []
    for i in ordem:
        if topo <= 0 or rrf[i] < CORTE_FRACAO * topo or len(sel) >= MAX_PAGINAS:
            break
        if sel and emb is not None:
            red = max(float(emb[i] @ emb[j]) for j in sel)
            if MMR_LAMBDA * (rrf[i] / topo) - (1 - MMR_LAMBDA) * red < 0:
                continue
        sel.append(int(i))

    pgs = {i + 1 for i in sel}
    # expansão de borda: a conta continua na página seguinte?
    for a, b in _runs(pgs):
        for passo in range(1, EXPANDIR_BORDA + 1):
            p = a - passo
            if p >= 1 and parece_conta(paginas[p - 1]):
                pgs.add(p)
            else:
                break
        for passo in range(1, EXPANDIR_BORDA + 1):
            p = b + passo
            if p <= n and parece_conta(paginas[p - 1]):
                pgs.add(p)
            else:
                break
    return {
        "runs": _runs(pgs),
        "paginas_sel": sorted(pgs),
        "canais": {str(i + 1): sorted(canais[i]) for i in sel[:15]},
        "scores": {str(i + 1): round(float(rrf[i]), 5) for i in sel[:15]},
    }
