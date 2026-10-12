# -*- coding: utf-8 -*-
"""Puxa a "Lista Unificada de Precatórios" do TJRS (CSV estatico gerado sob demanda, balde A/B) p/ cada ente.

Portal: https://www.tjrs.jus.br/novo/processos-e-servicos/precatorios-e-rpv/consultar-lista-unificada-de-precatorios/
E' um site WordPress/PHP comum (sem SPA, sem Power BI). O <select id="select__devedor"> dessa
pagina lista ~750-900 entes devedores com o id numerico usado como chave em TODAS as consultas
(nao existe endpoint JSON pra essa lista de entes -- so vem embutida no HTML da propria pagina).

O botao "Exportar" da pagina chama direto:
  GET https://www.tjrs.jus.br/novo/wp-content/themes/tjrs/exportacsv.php?param=<base64("devedor=<id>")>
  -> CSV (Content-Disposition: attachment) com header:
     ordem;prioridadeSigla;siglaTribunal;carater;verbaAno;numeroProcesso;dataApresentacao;valorDevido
  Ex.: "1;PD;TJRS ;A;2021;'50317312120208217000;29/06/2020;16455,94"
     prioridadeSigla: PI=Prioridade Idade, PD=Prioridade Doenca, PcD=Prioridade PcD, N=Normal
     carater: A=Alimentar, C=Comum
     numeroProcesso vem com apostrofo Excel na frente (evita truncar como numero) -- remover.
     valorDevido usa virgula decimal BR -- trocar por ponto antes de float().

GOTCHAS descobertos empiricamente (testado ao vivo em 29/08/2026):
  * O endpoint exportacsv.php e' TOTALMENTE stateless: GET direto, sem cookie/sessao/captcha/login,
    responde 200 mesmo na primeira requisicao "fria" (sem visitar a pagina antes).
  * O UNICO parametro suportado e' "devedor=<id>" dentro do base64 de "param". Vasculhei o JS da
    pagina de listagem e da pagina irma "Pesquisa de Precatórios" (busca por numero de processo) e
    NAO existe filtro por ano/natureza/prioridade embutido no export -- o botao "Exportar" so monta
    esse mesmo par devedor=<id> (visto no codigo-fonte: `exporta(){ window.open(".../exportacsv.php
    ?param=" + btoa("devedor=" + valorSelecionado)) }`). Se algum dia precisar filtrar por ano, tem
    que filtrar DEPOIS de baixar o CSV inteiro do ente.
  * devedor=0 (ou vazio) devolve corpo 100% VAZIO (0 bytes, nem header) -- nao da pra pedir "todos os
    entes de uma vez"; e' preciso iterar id por id (mesma limitacao do TJPR).
  * O CSV NAO tem nome do ente devedor nem credor/CPF -- mais anonimizado que o TJPR. O nome do ente
    so existe no HTML do <select> da pagina de listagem (por isso este script raspa esse <select>
    uma vez no inicio pra montar o mapa id -> nome).
  * Confirmado Content-Type: application/csv; charset=utf-8 (decodificar como UTF-8, nao Latin-1).
  * *** BUG CONFIRMADO E REPRODUTIVEL NO SERVIDOR, e NAO SO com a fila gigante do Estado (nao e'
    race condition -- retestado varias vezes, sempre o mesmo resultado): "devedor=<id>" DIFERENTES
    e validos (aparecem normalmente no <select> da pagina) as vezes devolvem CSVs byte-a-byte
    IDENTICOS. Dois exemplos observados, um grande e um pequeno:
      - id=652 "Assembléia Legislativa do Estado do RS" == id=795 "Autoridade Portuária dos Portos
        do RS" == (aparentemente) id invalido 1: os tres devolvem os MESMOS 76.852 registros /
        R$ 14,2 bi (provavelmente a fila geral do proprio Estado do RS).
      - id=880 "AUTARQUIA MUN DE TURISMO - GRAMADOTUR - GRAMADO/RS" == id=859 "COMPANHIA DE
        SANEAMENTO AMB. DO MARANHAO-CAEMA" (uma autarquia gaucha e uma empresa DE OUTRO ESTADO,
        sem nenhuma relacao logica entre si): os dois devolvem os MESMOS 13 registros / R$ 2,74 mi.
    Ou seja, isso nao e' so "orgaos estaduais compartilham a fila do Estado" -- parece um bug de
    verdade no mapeamento id->fila do exportacsv.php (possivelmente uma chave interna colidindo,
    nao o "devedor" numerico que aparece na URL). NAO DA' PRA CONFIAR CEGAMENTE que cada arquivo
    salvo e' de fato exclusivo daquele ente. ISSO INFLA SOMATORIOS: somar "valor_total" de todo
    data/tjrs/*.json sem tratar duplicatas conta a mesma fila 2x, 3x...
    MITIGACAO neste script: cada arquivo salvo carrega "fila_hash" (sha1 do CSV cru, so p/ filas
    NAO-vazias). O main() mantem um mapa hash->[ids] DENTRO da mesma rodada e imprime um AVISO
    quando 2+ entes diferentes caem no mesmo hash -- mas so pega colisoes vistas NA MESMA execucao
    (rodadas resumidas em dias diferentes nao comparam hash entre si, entao rode um passo de
    dedupe por "fila_hash" sobre TODO o data/tjrs/*.json antes de qualquer analise agregada em R$).

Salva data/tjrs/<id>_<slug>.json (1 arquivo por ente). Resumavel (pula arquivo ja salvo) e educado.

Uso:
  python scripts/fetch_tjrs.py             # fila completa de cada ente
  python scripts/fetch_tjrs.py --limit=5   # so os 5 primeiros entes ainda nao salvos (teste)
"""
import base64, csv, hashlib, html, io, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request

BASE = r"C:\Users\victo\Precatur\Alfred"
OUT = os.path.join(BASE, "data", "tjrs")
LISTA_URL = "https://www.tjrs.jus.br/novo/processos-e-servicos/precatorios-e-rpv/consultar-lista-unificada-de-precatorios/"
EXPORT_URL = "https://www.tjrs.jus.br/novo/wp-content/themes/tjrs/exportacsv.php"
DELAY = 0.4
os.makedirs(OUT, exist_ok=True)

LIMIT = None
for _a in sys.argv[1:]:
    if _a.startswith("--limit="):
        LIMIT = int(_a.split("=", 1)[1])


def norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()


def slugify(s):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", norm(s).lower())).strip("_") or "ente"


def get_bytes(url, tries=6):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
                "Referer": LISTA_URL,
            })
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(DELAY * (a + 2))
    raise RuntimeError(f"falhou {url}: {last}")


def listar_devedores():
    """Raspa o <select id="select__devedor"> da pagina de Lista Unificada (nao existe API p/ isso)."""
    page = get_bytes(LISTA_URL).decode("utf-8", "replace")
    m = re.search(r'<select[^>]*id="select__devedor".*?</select>', page, re.DOTALL)
    if not m:
        raise RuntimeError("select__devedor nao encontrado no HTML -- pagina pode ter mudado de layout")
    block = m.group(0)
    ents = []
    for mid, nome in re.findall(r'<option\s+value="(\d+)"\s*>\s*([^<]*?)\s*</option>', block, re.DOTALL):
        if mid == "0":
            continue
        ents.append({"id": int(mid), "nome": html.unescape(re.sub(r"\s+", " ", nome)).strip()})
    return ents


def export_csv(ente_id):
    """Devolve (linhas, fila_hash). fila_hash = sha1 do CSV cru, usado p/ flagar colisao entre
    entes (ver gotcha de bug do servidor no topo do arquivo)."""
    param = base64.b64encode(f"devedor={ente_id}".encode()).decode()
    url = f"{EXPORT_URL}?param={urllib.parse.quote(param)}"
    raw_bytes = get_bytes(url)
    fila_hash = hashlib.sha1(raw_bytes).hexdigest() if raw_bytes else None
    raw = raw_bytes.decode("utf-8", "replace").strip()
    if not raw:
        return [], fila_hash
    reader = csv.DictReader(io.StringIO(raw), delimiter=";")
    rows = []
    for row in reader:
        try:
            # celula vazia = valor NAO publicado -> None (nao 0: o zero escondia a falta de
            # valor e entrava como divida zerada; ver ad_tjrs, 05/10/2026)
            vd = (row.get("valorDevido") or "").strip()
            valor = (float(vd.replace(".", "").replace(",", ".")) if "," in vd else float(vd)) if vd else None
        except ValueError:
            valor = None
        rows.append({
            "ordem": int(row["ordem"]) if (row.get("ordem") or "").isdigit() else row.get("ordem"),
            "prioridadeSigla": row.get("prioridadeSigla"),
            "siglaTribunal": (row.get("siglaTribunal") or "").strip(),
            "carater": row.get("carater"),
            "verbaAno": int(row["verbaAno"]) if (row.get("verbaAno") or "").isdigit() else row.get("verbaAno"),
            "numeroProcesso": (row.get("numeroProcesso") or "").lstrip("'"),
            "dataApresentacao": row.get("dataApresentacao"),
            "valorDevido": valor,
        })
    return rows, fila_hash


def main():
    ents = listar_devedores()
    print(f"entes no <select> da Lista Unificada: {len(ents)}", flush=True)

    feitos = {f.split("_")[0] for f in os.listdir(OUT) if f.endswith(".json") and f.split("_")[0].isdigit()}
    print(f"ja salvos (resume): {len(feitos)} | limit={LIMIT}", flush=True)

    pendentes = [e for e in ents if str(e["id"]) not in feitos]
    if LIMIT:
        pendentes = pendentes[:LIMIT]

    tot_ent = tot_prec = 0
    tot_val = 0.0
    vistos_por_hash = {}  # fila_hash -> [ids] vistos NESTA rodada (deteccao de colisao/bug do servidor)
    for i, e in enumerate(pendentes, 1):
        eid, nome = e["id"], e["nome"]
        try:
            fila, fila_hash = export_csv(eid)
        except Exception as ex:
            print(f"  [{i}/{len(pendentes)}] ERRO id={eid} {nome[:40]}: {ex}", flush=True)
            continue

        if fila_hash and len(fila) > 0:  # so ignora colisao de fila VAZIA (header-only, sem sentido avisar)
            outros = vistos_por_hash.setdefault(fila_hash, [])
            if outros:
                print(f"  [{i}/{len(pendentes)}] *** AVISO: id={eid} ({nome[:30]}) tem fila IDENTICA "
                      f"(mesmo hash) a {outros} -- possivel bug do exportacsv.php, ver docstring ***",
                      flush=True)
            outros.append(eid)

        por_carater = {}
        por_prioridade = {}
        valor_total = 0.0
        for r in fila:
            c = r.get("carater") or "?"
            por_carater[c] = por_carater.get(c, 0) + 1
            p = r.get("prioridadeSigla") or "?"
            por_prioridade[p] = por_prioridade.get(p, 0) + 1
            if isinstance(r.get("valorDevido"), (int, float)):
                valor_total += r["valorDevido"]

        rec = {
            "id_entidade": eid,
            "nome": nome,
            "total": len(fila),
            "por_carater": por_carater,        # A=Alimentar, C=Comum
            "por_prioridade": por_prioridade,  # PI/PD/PcD/N
            "valor_total": round(valor_total, 2),
            "fila_hash": fila_hash,  # sha1 do CSV cru -- usar p/ dedupe (ver gotcha no topo do arquivo)
            "precatorios": fila,
        }
        fn = os.path.join(OUT, f"{eid}_{slugify(nome)}.json")
        json.dump(rec, open(fn, "w", encoding="utf-8"), ensure_ascii=False)

        tot_ent += 1
        tot_prec += len(fila)
        tot_val += valor_total
        print(f"  [{i}/{len(pendentes)}] id={eid:<5} {nome[:34]:34} "
              f"{len(fila):>6} prec  R$ {valor_total:>16,.2f}", flush=True)
        time.sleep(DELAY)

    print(f"\nOK -> {OUT}", flush=True)
    print(f"entes novos gravados: {tot_ent} | precatorios: {tot_prec} | R$ {tot_val:,.2f}", flush=True)


if __name__ == "__main__":
    main()
