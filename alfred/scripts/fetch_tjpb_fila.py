# -*- coding: utf-8 -*-
r"""Puxa a FILA INDIVIDUAL de precatorios do TJPB (balde A, JSON aberto, sem
captcha/Cloudflare/Playwright) via a ferramenta publica "Consulta de
Precatorios" (Ordem Cronologica) em app.tjpb.jus.br.

DESCOBERTA (2026-09-17): o site institucional so tinha o Painel Precatorios
Municipais (Qlik Sense, so dado AGREGADO -- ver fetch_tjpb.py). Mas o menu
"Precatorios" tambem tem um item separado "Ordem Cronologica" apontando pra
outro subdominio, app.tjpb.jus.br/transparencia/precatorios -- uma pagina
HTML simples (nao SPA pesada) com busca por Ente/Entidade, que chama:

  GET https://app.tjpb.jus.br/transparencia-backend/precatorios/entidades
      -> lista de entes [{"id","nome","adesaoSistemaPagamentoEC62"}], ~320
         registros (223 municipios + Estado/autarquias/INSS/etc.)
  GET https://app.tjpb.jus.br/transparencia-backend/precatorios/consulta
      ?entidadeId=<id>&offset=<n>&limit=<n>
      -> Page (Spring Data) com totalElements/totalPages e "content": lista
         de precatorios com posicao (fila real, estavel entre paginas),
         numero (CNJ do proprio precatorio), anoOrcamento, naturezaAlimentar
         (bool), superpreferencia (bool) + tipoPreferencia{id,descricao},
         dataAutuacao, valorOriginario, valorAtual (atualizado!) e
         entidadeDevedora{id,nome,entidade{id,nome,...},valorMaximoRPV}.

Testado ao vivo: funciona com requests PUROS, SEM cookie/sessao/Playwright
-- diferente da pagina institucional (que tem Cloudflare Managed Challenge),
o backend deste subdominio responde 200 direto, ate' "frio". limit=2000 num
unico request funcionou sem erro/rate-limit aparente.

GOTCHA (mesma familia do bug do TJRJ, ver ad_tjrj em db_build.py):
"entidadeId" e' um agrupador -- ao consultar CAMPINA GRANDE (id=53) vem a
fila da PREFEITURA MISTURADA com a de autarquias subordinadas (Instituto de
Previdencia, Superintendencia de Transportes...), cada uma com seu proprio
`entidadeDevedora.id`/nome dentro da MESMA lista. Se gravasse tudo sob um so'
ente, a divida do municipio ficaria inflada com a das autarquias. Este
coletor SEPARA por entidadeDevedora.id na hora de salvar -- um arquivo por
devedor REAL, nao por entidadeId consultado.

Sem credor (o proprio aviso da pagina cita art.12 §3o da Res. CNJ 303/2019).

Salva data/tjpb_fila/<entidadeDevedora_id>_<slug>.json (1 por devedor real).
Resumavel (pula quem ja tem arquivo). Educado (pequeno delay entre entes).

Uso:
  python scripts/fetch_tjpb_fila.py             # todos os entes
  python scripts/fetch_tjpb_fila.py --limit=5   # so os 5 primeiros ainda nao salvos (teste)
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

BASE = os.environ.get("ALFRED_BASE") or r"C:\Users\victo\Precatur\Alfred"
OUT = os.path.join(BASE, "data", "tjpb_fila")
os.makedirs(OUT, exist_ok=True)

API = "https://app.tjpb.jus.br/transparencia-backend/precatorios"
PAGE_SIZE = 2000
DELAY = 0.3

LIMIT = None
for _a in sys.argv[1:]:
    if _a.startswith("--limit="):
        LIMIT = int(_a.split("=", 1)[1])


def norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()


def slugify(s):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", norm(s).lower())).strip("_") or "ente"


def get_json(url, tries=5):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(DELAY * (a + 2))
    raise RuntimeError(f"falhou {url}: {last}")


def listar_entidades():
    return get_json(f"{API}/entidades")


def consultar_tudo(entidade_id):
    """Pagina ate' o fim; devolve a lista completa 'content' daquele grupo (entidadeId)."""
    todos = []
    offset = 0
    while True:
        d = get_json(f"{API}/consulta?entidadeId={entidade_id}&offset={offset}&limit={PAGE_SIZE}")
        todos.extend(d.get("content", []))
        if d.get("last") or len(d.get("content", [])) == 0:
            break
        offset += PAGE_SIZE
    return todos


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    entidades = listar_entidades()
    print(f"entidades (grupos) no endpoint /entidades: {len(entidades)}", flush=True)

    feitos = {f.split("_")[0] for f in os.listdir(OUT) if f.endswith(".json") and f.split("_")[0].isdigit()}
    print(f"devedores reais ja salvos (resume): {len(feitos)}", flush=True)

    pendentes = [e for e in entidades]
    if LIMIT:
        pendentes = pendentes[:LIMIT]

    tot_grupos = tot_devedores_novos = tot_prec = 0
    tot_val = 0.0
    for i, ent in enumerate(pendentes, 1):
        gid, gnome = ent["id"], ent["nome"]
        try:
            rows = consultar_tudo(gid)
        except Exception as ex:
            print(f"  [{i}/{len(pendentes)}] ERRO grupo id={gid} {gnome[:40]}: {ex}", flush=True)
            continue

        # separa por DEVEDOR REAL (entidadeDevedora.id) -- ver gotcha no topo do arquivo
        por_devedor = {}
        for r in rows:
            dev = r.get("entidadeDevedora") or {}
            did = dev.get("id")
            if did is None:
                continue
            grupo = por_devedor.setdefault(did, {"nome": dev.get("nome"), "regime": (dev.get("entidade") or {}).get("adesaoSistemaPagamentoEC62"),
                                                   "valor_maximo_rpv": dev.get("valorMaximoRPV"), "grupo_id": gid, "grupo_nome": gnome,
                                                   "precatorios": []})
            grupo["precatorios"].append(r)

        novos_neste_grupo = 0
        for did, info in por_devedor.items():
            if str(did) in feitos:
                continue
            valor_total = sum((p.get("valorAtual") or 0) for p in info["precatorios"])
            rec = {
                "id_entidade": did,
                "nome": info["nome"],
                "regime": info["regime"],
                "valor_maximo_rpv": info["valor_maximo_rpv"],
                "grupo_consultado_id": info["grupo_id"],
                "grupo_consultado_nome": info["grupo_nome"],
                "total": len(info["precatorios"]),
                "valor_total": round(valor_total, 2),
                "precatorios": info["precatorios"],
            }
            fn = os.path.join(OUT, f"{did}_{slugify(info['nome'])}.json")
            json.dump(rec, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
            feitos.add(str(did))
            novos_neste_grupo += 1
            tot_devedores_novos += 1
            tot_prec += len(info["precatorios"])
            tot_val += valor_total

        tot_grupos += 1
        print(f"  [{i}/{len(pendentes)}] grupo={gid:<5} {gnome[:34]:34} "
              f"{len(rows):>6} linhas / {len(por_devedor)} devedor(es) ({novos_neste_grupo} novo(s))", flush=True)
        time.sleep(DELAY)

    print(f"\nOK -> {OUT}", flush=True)
    print(f"grupos consultados: {tot_grupos} | devedores novos gravados: {tot_devedores_novos} | "
          f"precatorios: {tot_prec} | R$ {tot_val:,.2f}", flush=True)


if __name__ == "__main__":
    main()
