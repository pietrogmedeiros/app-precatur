# -*- coding: utf-8 -*-
"""Coluna precatorio.credor_norm + indice FTS5 `credor_fts` da busca por nome.

POR QUE: a busca por nome e' "contem cada palavra, sem acento" (LIKE '%SILVA%'). Antes
ela chamava uma funcao Python (SEM_ACENTO) em cada uma das ~900k linhas, duas vezes por
busca (pagina + total): ~0,7 s por varredura local, ~2 s na VM. Agora:
  - credor_norm guarda o nome ja normalizado (sem acento, maiusculo) -- calculado aqui,
    UMA vez, com a MESMA normaliza() que o alfred_core aplica ao termo buscado;
  - credor_fts (FTS5, tokenizer trigram) indexa credor_norm em trechos de 3 letras, o
    que atende LIKE '%X%' por indice sem mudar a semantica de "contem" (o tokenizer
    padrao do FTS5 so' casaria palavra inteira/prefixo). Palavras com menos de 3 letras
    nao formam trigrama: o alfred_core as filtra por LIKE em credor_norm.
Sem indice B-tree em credor_norm: com curinga no inicio ('%X%') ele nunca e' usado.

SINCRONIA: credor_norm e credor_fts sao DERIVADOS de `credor`. Quem altera `credor`
chama sincroniza(cx, ids) no fim (db_build faz a carga inteira; enriquece_credor e
enriquece_credor_djen, os ids que mudaram). Nao ha trigger de proposito: a normalizacao
e' Python, e um trigger que a chamasse faria QUALQUER conexao que escreva em precatorio
(sqlite3 da VM, DB Browser) falhar com "no such function".
"""
import unicodedata

FTS = "credor_fts"


def normaliza(s):
    """'José Sátiro' -> 'JOSE SATIRO'. Unica definicao: dado gravado e termo buscado."""
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.upper()


def existe(cx):
    """Banco com credor_norm/credor_fts? (os anteriores a 2026-09-29 nao tem)"""
    return cx.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (FTS,)).fetchone() is not None


def sincroniza(cx, ids=None):
    """Recalcula credor_norm e credor_fts a partir de `credor`.
    ids=None: o banco inteiro (fim da carga). ids=[...]: so' esses (enriquecimentos).
    Em banco sem credor_fts nao faz nada (a busca de la' ainda usa o caminho antigo).
    Devolve quantos precatorios foram reindexados."""
    if not existe(cx):
        return 0
    # Normaliza em Python e grava o valor pronto -- SEM registrar funcao SQL na conexao:
    # com escrita pendente no FTS5 (antes do commit) o SQLite recusa redefinir funcao
    # ("Error creating function"), e duas sincronizacoes na mesma transacao quebravam.
    if ids is None:
        cx.execute("UPDATE precatorio SET credor_norm = NULL WHERE credor IS NULL")
        linhas = cx.execute("SELECT id, credor FROM precatorio WHERE credor IS NOT NULL").fetchall()
        cx.execute(f"DELETE FROM {FTS}")
    else:
        ids = list(dict.fromkeys(ids))                 # sem repetidos, ordem preservada
        linhas = [r for r in (cx.execute("SELECT id, credor FROM precatorio WHERE id = ?", (i,)).fetchone()
                              for i in ids) if r]
        cx.executemany(f"DELETE FROM {FTS} WHERE rowid = ?", [(r[0],) for r in linhas])
    vals = [(None if c is None else normaliza(c), i) for i, c in linhas]
    cx.executemany("UPDATE precatorio SET credor_norm = ? WHERE id = ?", vals)
    cx.executemany(f"INSERT INTO {FTS}(rowid, credor_norm) VALUES (?, ?)",
                   [(i, n) for n, i in vals if n is not None])
    return cx.execute("SELECT COUNT(*) FROM precatorio").fetchone()[0] if ids is None else len(vals)
