# -*- coding: utf-8 -*-
"""Coleta a ordem cronologica de precatorios de TODOS os entes de UM TRT (GPREC) via
Playwright (headed). Resumavel: salva data/trt<N>/<cnpj>_<nome>.json por ente. Trata o
reCAPTCHA esperando resolver (auto ou manual no inicio da sessao).

O GPREC e' NACIONAL (mesmo app Angular nos 24 TRTs, so muda o host pje.trtXX.jus.br) --
por isso este coletor serve qualquer TRT, so passar o numero. A API por tras (descoberta
em 2026-08-20) e' `POST /gprec/rest/requisicaopagamento/devedores` + `/precatorio/lista/`
com `{"respostaCaptcha": token}`; aqui a gente deixa o proprio app dispara-las e so
INTERCEPTA as respostas (mais robusto que replicar a geracao do token do reCAPTCHA).

RODAR DE CASA (IP residencial): headless/datacenter recebe desafio de captcha o tempo todo.
  python scripts/gprec_coletar.py --trt 3      # TRT3 (MG)
  python scripts/gprec_coletar.py --trt 5      # TRT5 (BA)
  python scripts/gprec_coletar.py --trt 17     # TRT17 (ES) -- default
"""
import argparse, json, os, pathlib, re, unicodedata, random
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
_ap = argparse.ArgumentParser()
_ap.add_argument("--trt", type=int, default=17, help="numero do TRT (1..24)")
TRT = _ap.parse_args().trt
URL = f"https://pje.trt{TRT}.jus.br/gprec-frontend/precatorio"
OUTDIR = os.path.join(BASE, "data", f"trt{TRT}")
os.makedirs(OUTDIR, exist_ok=True)
def digs(s): return re.sub(r"\D", "", str(s or ""))
def norm(s): return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()

def run():
    print(f"TRT{TRT} · {URL}\n  saida: {OUTDIR}")
    capturado = {}   # cnpj_digits -> body da lista
    devedores = {}   # capturado do /devedores
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                            locale="pt-BR", viewport={"width": 1366, "height": 900})
        pg = ctx.new_page()

        def on_resp(r):
            u = r.url
            try:
                if u.endswith("/devedores") and r.status == 200:
                    devedores["list"] = r.json()
                elif "precatorio/lista" in u and r.status == 200:
                    body = r.json(); capturado[digs(body.get("cnpjDevedor"))] = body
            except Exception:
                pass
        pg.on("response", on_resp)

        def challenge_visivel():
            for c in pg.query_selector_all("iframe[src*='bframe']"):
                try:
                    box = c.bounding_box()
                    if c.is_visible() and box and box["width"] > 50 and box["height"] > 50: return True
                except Exception: pass
            return False
        def resolver(motivo):
            if challenge_visivel():
                print(f"   >>> reCAPTCHA ({motivo}): RESOLVA na janela (ate 180s)...", flush=True)
                for _ in range(90):
                    pg.wait_for_timeout(2000)
                    if not challenge_visivel():
                        print("   >>> ok, seguindo.", flush=True)
                        pg.wait_for_timeout(4000)   # cooldown apos resolver (reconstroi confianca)
                        return True
                print("   >>> tempo esgotado."); return False
            return True

        def humano():
            # movimento de mouse + pausa aleatoria para parecer humano (reduz desafios)
            for _ in range(random.randint(2, 4)):
                pg.mouse.move(random.randint(200, 1100), random.randint(200, 700), steps=random.randint(4, 10))
                pg.wait_for_timeout(random.randint(150, 400))
            pg.wait_for_timeout(random.randint(3500, 7000))

        pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(6000)
        resolver("ao carregar")
        # garante devedores carregados
        for _ in range(10):
            if devedores.get("list"): break
            pg.wait_for_timeout(1000)
        entes = devedores.get("list", [])
        json.dump(entes, open(os.path.join(OUTDIR, "_devedores.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"Entes no GPREC: {len(entes)}")

        feitos = {digs(f.split("_")[0]) for f in os.listdir(OUTDIR) if f[0].isdigit()}
        print(f"Ja coletados: {len(feitos)}")

        for i, ente in enumerate(entes, 1):
            cnpj = digs(ente["cnpjDevedor"]); nome = ente["nome"]
            if cnpj in feitos:
                continue
            try:
                # limpa desafio residual do ente anterior e faz pausa humana
                resolver("residual")
                humano()
                # abre o select e escolhe o ente pelo nome
                pg.click("#devedor"); pg.wait_for_timeout(random.randint(700, 1400))
                achou = False
                for o in pg.query_selector_all("mat-option"):
                    if norm(o.inner_text()) == norm(nome):
                        o.scroll_into_view_if_needed(); o.click(); achou = True; break
                if not achou:  # fallback: contains
                    for o in pg.query_selector_all("mat-option"):
                        if norm(nome) in norm(o.inner_text()):
                            o.scroll_into_view_if_needed(); o.click(); achou = True; break
                if not achou:
                    print(f"[{i}/{len(entes)}] {nome}: opcao nao encontrada, pulando"); pg.keyboard.press("Escape"); continue
                pg.wait_for_timeout(random.randint(500, 1200))
                bt = pg.query_selector("#btnBuscar")
                if bt:
                    box = bt.bounding_box()
                    if box: pg.mouse.move(box["x"]+box["width"]/2, box["y"]+box["height"]/2, steps=6)
                pg.click("#btnBuscar")
                pg.wait_for_timeout(1800); resolver(f"buscar {nome}")
                # espera a resposta desse cnpj (ate 25s)
                got = None
                for _ in range(25):
                    if cnpj in capturado: got = capturado[cnpj]; break
                    pg.wait_for_timeout(1000)
                if got is None:
                    print(f"[{i}/{len(entes)}] {nome}: SEM resposta (timeout)"); continue
                slug = norm(nome).lower().replace(" ", "_")
                json.dump({"nome": nome, "cnpj": cnpj, **got},
                          open(os.path.join(OUTDIR, f"{cnpj}_{slug}.json"), "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                n = len(got.get("listaCronologica", []))
                print(f"[{i}/{len(entes)}] {nome}: {n} precatorios | total {got.get('totalPrecatorio')}", flush=True)
            except Exception as e:
                print(f"[{i}/{len(entes)}] {nome}: ERRO {e}")
                try: pg.keyboard.press("Escape")
                except Exception: pass
        print("\nConcluido. Arquivos em:", OUTDIR)
        b.close()

if __name__ == "__main__":
    run()
