# -*- coding: utf-8 -*-
"""Mapa Anual de Precatorios publicado por CADA TRIBUNAL -> serie historica.

POR QUE EXISTE (e por que o painel do CNJ nao resolve)

O painel Qlik do CNJ (scripts/extrair_cnj_mapa_anual.py) publica APENAS o
exercicio corrente. Resultado na base: MG tem 2021-2025 (veio de outra fonte) e
os outros 25 estados tem UM ano so. Com um ano so a leitura do ente e' fragil —
e chegou a inverter uma conclusao real:

    Lauro de Freitas/BA, so com 2025:  pagou 4,4% do estoque -> "nao paga"
    Com a serie 2020-2025:             pagou R$ 3,2 mi em 2021, R$ 2,4 mi em 2023
                                       e zerou o saldo para R$ 297 mil em 2022.
    O que mudou em 2025 nao foi o pagamento secar: foi entrar R$ 20,5 mi de
    divida NOVA de uma vez. Um ano isolado confunde pico de expedicao com
    colapso de pagamento.

A Resolucao CNJ 303/2019 (art. 85 §1o) obriga CADA tribunal a publicar o proprio
Mapa Anual ate 31/03. E' de la que vem a serie. Cada tribunal publica num layout
proprio, entao cada um e' uma entrada em FONTES com seu proprio parser.

ATENCAO — vlr_ano_anterior fica NULO nas linhas vindas daqui. O PDF do tribunal
publica pago/saldo/expedidos, nao o montante de abertura. Da' para estimar por
`anterior ~= saldo + pago` (a identidade fecha com ~4,4% de residuo, que e'
correcao monetaria — ver db_mapa.py), mas estimativa gravada como se fosse dado
publicado e' exatamente o tipo de coisa que volta como erro meses depois. Fica
nulo; quem precisa da taxa de quitacao usa o ano do CNJ, que tem o campo.

TJSP FICA DE FORA — E NAO E' BUG DE PARSER (verificado 2026-08-19)

O parser de grade le o PDF do TJSP corretamente (cabecalho e celulas conferem),
mas os valores DIVERGEM do painel do CNJ em 18% das comparacoes de 2025:

    vlr_expedidos   0 divergencias   <- o que foi expedido nao muda
    vlr_pago      287 divergencias
    vlr_saldo     266 divergencias
    direcao: 316 vezes o PDF e' maior, 271 vezes o CNJ e' maior (nao e' vies)
    total pago 2025/SP:  PDF R$ 11,84 bi  x  CNJ R$ 11,02 bi  (+7,4%, R$ 819 mi)

Expedido bate sempre; pago e saldo divergem nos dois sentidos. Isso e' assinatura
de DUAS APURACOES do mesmo exercicio em momentos diferentes (reconciliacao de
pagamento), nao de leitura errada. Carregar como se fosse a mesma serie faria a
base afirmar dois valores para o mesmo fato. Fica fora ate alguem decidir qual
fonte manda no TJSP.

URLs ja descobertas, para nao ter de garimpar de novo (handler de anexo do TJSP:
https://api.tjsp.jus.br/Handlers/Handler/FileFetch.ashx?codigo=<cod>):
    2025 -> 183262   2024 -> 165834   2023 -> 154760
    2022 -> 144839   2021 -> 138175   2019 -> 137460

Uso:
  python scripts/fetch_mapa_tribunal.py --tribunal TJBA
  python scripts/fetch_mapa_tribunal.py --tribunal TJBA --ano 2023
  python scripts/fetch_mapa_tribunal.py --listar

Saida: data/mapa_tribunal_<sigla>.json  (carregado por db_mapa.carrega_tribunal)
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.environ.get("ALFRED_BASE") or str(pathlib.Path(__file__).resolve().parents[1])
CACHE = os.path.join(BASE, "data", "mapas_tribunal")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0"

# ---------------------------------------------------------------------------
# FONTES: sigla -> {"uf":…, "formato":…, "anos": {ano: url}}
# Para acrescentar um tribunal: achar a pagina "Mapa Anual de Precatorios" dele
# (todos tem, por forca da Res. 303/2019 art. 85 §1o) e mapear ano -> URL.
# ---------------------------------------------------------------------------
FONTES = {
    "TJBA": {
        "uf": "BA", "formato": "pdf",
        "anos": {
            2020: "https://www.tjba.jus.br/portal/wp-content/uploads/2021/03/Mapa-Anual-de-Precatorios-2020.pdf",
            2021: "https://www.tjba.jus.br/portal/wp-content/uploads/2024/04/Mapa-Anual-2021.pdf",
            2022: "https://www.tjba.jus.br/portal/wp-content/uploads/2024/04/Mapa-Anual-2022.pdf",
            2023: "https://www.tjba.jus.br/portal/wp-content/uploads/2024/04/Mapa-Anual-2023.pdf",
            2024: "https://www.tjba.jus.br/portal/wp-content/uploads/2025/03/Mapa-Anual-2024.pdf",
            2025: "https://www.tjba.jus.br/portal/wp-content/uploads/2026/03/mapa-anual-precatorios-2025.pdf",
        },
    },
    # TJRJ: PDF sem grade -> parser por linha de texto. Cuidado com o nome do
    # arquivo: o TJRJ batiza pelo ano de PUBLICACAO ("Mapa Anual 2026 —
    # orcamento do ano de 2025"), nao pelo ano de referencia. As chaves abaixo
    # sao o ano_ref REAL, lido do conteudo; o parser reconfere linha a linha.
    "TJRJ": {
        "uf": "RJ", "formato": "pdf_texto", "ssl_relaxado": True,
        "anos": {
            2023: "https://www.tjrj.jus.br/documents/d/precatorios/mapa-anual-de-precatorios-cnj-2024-publicacao-no-portal-do-tjrj-atualizado-em-09-05-2024-1",
            2024: "https://www.tjrj.jus.br/documents/d/precatorios/mapa_anual_de_precatorios_2025_cnj",
            2025: "https://www.tjrj.jus.br/documents/d/precatorios/mapa_anual_de_precatorios_2026_cnj-orcamento_do_ano_de_2025",
        },
    },
    # TJES: de 2023 em diante publica em XLS — o formato mais confiavel de todos
    # (celulas e numeros ja separados). 2021/2022 sao PDF e ficam de fora ate
    # alguem precisar: o ganho e' pequeno perto do risco de parser novo.
    "TJES": {
        "uf": "ES", "formato": "xls",
        "anos": {
            2023: "https://www.tjes.jus.br/wp-content/uploads/Mapa-de-Precatorios-Ano-de-Referencia-2023.xls",
            2024: "https://www.tjes.jus.br/wp-content/uploads/Mapa-de-Precatorios-Ano-de-Referencia-2024-1.xls",
            2025: "https://www.tjes.jus.br/wp-content/uploads/Mapa-de-Precatorios-Ano-Referencia-2025-1.xls",
        },
    },
    # TJAL: o portal e' SPA e nao expoe os PDFs em pagina indexada — nem busca
    # nem crawl acham. As URLs estavam HARDCODED no bundle JS da rota Precatorios
    # (/assets/Precatorios-*.js). Se um dia sumirem daqui, e' la que se acha de
    # novo: baixar o bundle e grepar por "/precatorios/mapa/".
    "TJAL": {
        "uf": "AL", "formato": "pdf",
        "anos": {
            2021: "https://www.tjal.jus.br/precatorios/mapa/mapa-anual-de-precatorios-tj-al-2021.1.pdf",
            2022: "https://www.tjal.jus.br/precatorios/mapa/mapa-anual-de-precatorios-tj-al-2022.pdf",
            2023: "https://www.tjal.jus.br/precatorios/mapa/mapa-anual-de-precatorios-tj-al-2023.1.pdf",
            2024: "https://www.tjal.jus.br/precatorios/mapa/mapa-anual-de-precatorios-tj-al-2024.1.pdf",
            2025: "https://www.tjal.jus.br/precatorios/mapa/mapa-anual-de-precatorios-tj-al-2025.1.pdf",
        },
    },
}

# Colunas do Mapa Anual, identificadas por PEDACO DO NOME do cabecalho.
#
# Por que por nome e nao por posicao: o layout MUDA de ano para ano no mesmo
# tribunal. TJBA 2020 e 2024 tem 13 colunas (incluem "expedidos ate o ano
# anterior"); 2025 tem 12 (sem essa). Ler por indice fixo trocaria pago por
# saldo silenciosamente no ano errado. Os cabecalhos tambem vem com quebras de
# linha aleatorias ("Ano de Referenci a"), por isso a chave e' normalizada.
COLUNAS = {
    "tribunal":         "sigladotribunal",
    "ano_ref":          "anodereferencia",
    "esfera":           "esferadoente",
    "uf":               "sigladoestado",
    "ibge":             "codigomunicipio",
    "regime":           "regimedepagamento",
    "tipo_entidade":    "tipodeentidade",
    "cnpj":             "cnpjdaentidade",
    "ente_nome":        "nomedaentidade",
    "vlr_ano_anterior": "expedidosateoanoanterior",
    "vlr_pago":         "montantepagonoano",
    "vlr_saldo":        "saldodevedorapospagamento",
    "vlr_expedidos":    "expedidosnoanodereferencia",
}


def _chave(s):
    """Cabecalho -> forma comparavel: sem acento, SEM ESPACO NENHUM, minusculo.

    Tirar todo espaco (e nao so normalizar) e' o que torna o casamento imune as
    quebras que o PDF insere no meio das palavras: o TJBA 2024 traz "Codigo
    Municipi o Devedor" e "Ano de Referenci a". Com espacos preservados nenhuma
    coluna casava e o exercicio inteiro saia com ZERO linhas, sem erro.
    """
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "", s).strip().lower()


def _num(tok):
    """Celula -> float. '-' e vazio = zero; ',00' = 0,00 (o extrator perde o 0)."""
    t = (tok or "").strip()
    if t in ("", "-", "—"):
        return 0.0
    t = re.sub(r"[^\d.,\-]", "", t)
    if t.startswith(","):
        t = "0" + t
    m = re.search(r"-?[\d.]*,\d{2}|-?\d+", t)
    if not m:
        return 0.0
    return float(m.group(0).replace(".", "").replace(",", "."))


def baixa(url, destino, ssl_relaxado=False):
    """Baixa (com cache em disco) o arquivo do mapa.

    ssl_relaxado: alguns portais de tribunal servem cadeia de certificado
    INCOMPLETA (falta o intermediario) e qualquer cliente que valide direito
    recusa — o do TJRJ e' assim. Como o conteudo e' documento estatistico
    publico, e o unico dado que trafega e' o proprio PDF que ja e' publico,
    aceitar a cadeia incompleta NESSA fonte e' preferivel a nao coletar. Fica
    por fonte, nunca global, para nao afrouxar as demais sem querer.
    """
    if os.path.exists(destino) and os.path.getsize(destino) > 2000:
        return destino
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    ctx = None
    if ssl_relaxado:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r, open(destino, "wb") as f:
        f.write(r.read())
    time.sleep(0.4)
    return destino


def parse_pdf_padrao(caminho, tribunal, ano_esperado):
    """Parser do Mapa Anual em PDF, guiado pelo cabecalho da tabela.

    Usa pdfplumber (celulas de verdade), NAO regex sobre texto achatado: o
    extrator de texto simples quebra os numeros de forma imprevisivel
    ("1.010.541,1 3" no TJBA 2024, ",00" no lugar de "0,00" no 2020) e isso
    derrubava ~130 de 137 linhas de um exercicio inteiro sem erro nenhum.
    """
    import pdfplumber
    linhas, ignoradas = [], 0
    with pdfplumber.open(caminho) as pdf:
        mapa_idx = None
        for pagina in pdf.pages:
            for tab in pagina.extract_tables() or []:
                if not tab:
                    continue
                # O cabecalho NEM SEMPRE e' a linha 0: o TJRJ poe duas linhas de
                # titulo institucional antes. Procura a linha que contem
                # "sigladotribunal" em qualquer posicao das primeiras.
                i_cab = None
                for j, linha in enumerate(tab[:6]):
                    if any("sigladotribunal" in _chave(c) for c in linha):
                        i_cab = j
                        break
                if i_cab is not None:
                    cab = [_chave(c) for c in tab[i_cab]]
                    mapa_idx = {}
                    for campo, pedaco in COLUNAS.items():
                        for i, c in enumerate(cab):
                            if pedaco in c:
                                mapa_idx[campo] = i
                                break
                    corpo = tab[i_cab + 1:]
                else:
                    corpo = tab
                if not mapa_idx or "ibge" not in mapa_idx:
                    continue
                for row in corpo:
                    def cel(campo):
                        i = mapa_idx.get(campo)
                        return row[i] if (i is not None and i < len(row)) else None
                    ibge = re.sub(r"\D", "", cel("ibge") or "")
                    ano = re.sub(r"\D", "", cel("ano_ref") or "")
                    if len(ibge) != 7 or len(ano) != 4:
                        ignoradas += 1
                        continue
                    esf = (cel("esfera") or "").strip().upper()[:1]
                    reg = (cel("regime") or "").strip().upper()[:1]
                    tip = (cel("tipo_entidade") or "").strip().upper()[:1]
                    linhas.append({
                        "ano_ref": int(ano),
                        "tribunal": (cel("tribunal") or tribunal).strip(),
                        "esfera": {"M": "Municipal", "E": "Estadual", "F": "Federal",
                                   "U": "União"}.get(esf, esf or None),
                        "uf": (cel("uf") or "").strip() or None,
                        "ibge": ibge,
                        "regime": {"C": "Comum", "E": "Especial"}.get(reg),
                        "tipo_entidade": {"D": "Direta", "I": "Indireta"}.get(tip),
                        "cnpj": (cel("cnpj") or "").strip() or None,
                        "ente_nome": re.sub(r"\s+", " ", (cel("ente_nome") or "").strip()) or None,
                        # so existe nos layouts de 13 colunas; ausente -> None (nao zero)
                        "vlr_ano_anterior": (_num(cel("vlr_ano_anterior"))
                                             if "vlr_ano_anterior" in mapa_idx else None),
                        "vlr_pago": _num(cel("vlr_pago")),
                        "vlr_saldo": _num(cel("vlr_saldo")),
                        "vlr_expedidos": _num(cel("vlr_expedidos")),
                    })
    return linhas, ignoradas


# TJRJ: PDF sem linhas de grade — o extrator de tabela do pdfplumber devolve UMA
# coluna. Mas o texto cru sai limpo, uma linha por ente:
#   TJRJ 2025 M RJ 3305133 C D R$ 8 6.912,97 R$ - R$ 9 0.827,77 R$ 2 7.413,41
# O espaco depois do "R$" e' kerning do PDF, nao separador: "8 6.912,97" e'
# 86.912,97. Os 4 valores sao, nesta ordem, anterior / pago / saldo / expedidos —
# confirmado pela identidade saldo ~= anterior - pago (residuo de 4,5%, que e' a
# correcao monetaria documentada em db_mapa.py).
RX_LINHA_TXT = re.compile(
    r"^(TJ[A-Z]{2}|TRT\d+|TRF\d+)\s+(\d{4})\s+"
    r"(Municipal|Estadual|Federal|Uni[ãa]o|[MEFU])\s+"
    r"([A-Z]{2})\s+"
    r"(\d{7})?\s*"                                        # vazio em ente estadual
    r"(Comum|Especial|[CE])\s+"
    r"(Administra[çc][ãa]o\s+(?:direta|indireta)|[DI])\s+"
    r"(.*)$", re.M)

# O TJRJ mudou a grafia entre exercicios: 2023 traz "Municipal / Especial /
# Administracao direta" por extenso e 2025 traz "M / E / D". Normalizar aqui
# evita que a mesma coluna vire dois valores distintos no banco.
_ESFERA = {"M": "Municipal", "E": "Estadual", "F": "Federal", "U": "União"}
_REGIME = {"C": "Comum", "E": "Especial"}
_TIPO = {"D": "Direta", "I": "Indireta"}


def _norm_cod(v, tabela, contem=None):
    v = re.sub(r"\s+", " ", (v or "").strip())
    if v in tabela:
        return tabela[v]
    b = v.lower()
    for alvo in (contem or []):
        if alvo.lower() in b:
            return alvo
    return v.capitalize() or None


def parse_pdf_texto(caminho, tribunal, ano_esperado):
    """Parser por linha de texto, para PDFs sem grade (validado no TJRJ)."""
    import pdfplumber
    linhas, ignoradas = [], 0
    with pdfplumber.open(caminho) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
    for m in RX_LINHA_TXT.finditer(texto):
        cauda = m.group(8)
        # cada valor comeca em "R$"; junta os pedacos e tira o espaco de kerning
        brutos = re.split(r"R\$", cauda)[1:]
        vals = []
        for b in brutos:
            b = re.sub(r"\s+", "", b.strip())
            if b in ("", "-", "—"):
                vals.append(0.0)
                continue
            g = re.search(r"[\d.]*,\d{2}|\d+", b)
            vals.append(float(g.group(0).replace(".", "").replace(",", ".")) if g else 0.0)
        if len(vals) < 4:
            ignoradas += 1
            continue
        anterior, pago, saldo, expedidos = vals[:4]
        nome = re.sub(r"\s+", " ", re.split(r"R\$", cauda)[0]).strip()
        cnpj = None
        if (g := re.match(r"^(\d{14})\s*(.*)$", nome)):
            cnpj, nome = g.group(1), g.group(2).strip()
        linhas.append({
            "ano_ref": int(m.group(2)), "tribunal": m.group(1),
            "esfera": _norm_cod(m.group(3), _ESFERA, ["Municipal", "Estadual", "Federal"]),
            "uf": m.group(4), "ibge": m.group(5),
            "regime": _norm_cod(m.group(6), _REGIME, ["Comum", "Especial"]),
            "tipo_entidade": _norm_cod(m.group(7), _TIPO, ["Indireta", "Direta"]),
            "cnpj": cnpj, "ente_nome": nome or None,
            "vlr_ano_anterior": anterior, "vlr_pago": pago,
            "vlr_saldo": saldo, "vlr_expedidos": expedidos,
        })
    return linhas, ignoradas


def parse_planilha(caminho, tribunal, ano_esperado):
    """Parser de XLS/XLSX (validado no TJES 2023-2025).

    De longe o formato mais confiavel: as celulas ja vem separadas e os numeros
    ja vem como numero, sem os artefatos de extracao que assombram os PDFs
    (decimal partido, zero virando ",00", espaco de kerning dentro do valor).
    Reusa o MESMO mapeamento por cabecalho do parser de PDF — o layout do Mapa
    Anual e' o mesmo; o que muda e' so o container.
    """
    import pandas as pd
    df = pd.read_excel(caminho, header=None, dtype=str)
    linhas, ignoradas = [], 0
    mapa_idx = None
    for _, serie in df.iterrows():
        celulas = ["" if (v is None or str(v) == "nan") else str(v) for v in serie.tolist()]
        chaves = [_chave(c) for c in celulas]
        if any("sigladotribunal" in c for c in chaves):
            mapa_idx = {}
            for campo, pedaco in COLUNAS.items():
                for i, c in enumerate(chaves):
                    if pedaco in c:
                        mapa_idx[campo] = i
                        break
            continue
        if not mapa_idx or "ibge" not in mapa_idx:
            continue

        def cel(campo):
            i = mapa_idx.get(campo)
            return celulas[i] if (i is not None and i < len(celulas)) else ""

        ibge = re.sub(r"\D", "", cel("ibge"))
        ano = re.sub(r"\D", "", cel("ano_ref"))
        if len(ano) != 4:
            ignoradas += 1
            continue
        esf, reg, tip = cel("esfera").strip(), cel("regime").strip(), cel("tipo_entidade").strip()
        linhas.append({
            "ano_ref": int(ano), "tribunal": cel("tribunal").strip() or tribunal,
            "esfera": _norm_cod(esf, _ESFERA, ["Municipal", "Estadual", "Federal"]),
            "uf": cel("uf").strip() or None,
            # ente estadual/federal nao tem municipio: fica NULO, nao string vazia
            "ibge": ibge if len(ibge) == 7 else None,
            "regime": _norm_cod(reg, _REGIME, ["Comum", "Especial"]),
            "tipo_entidade": _norm_cod(tip, _TIPO, ["Indireta", "Direta"]),
            "cnpj": re.sub(r"\D", "", cel("cnpj")) or None,
            "ente_nome": re.sub(r"\s+", " ", cel("ente_nome")).strip() or None,
            "vlr_ano_anterior": (_num_planilha(cel("vlr_ano_anterior"))
                                 if "vlr_ano_anterior" in mapa_idx else None),
            "vlr_pago": _num_planilha(cel("vlr_pago")),
            "vlr_saldo": _num_planilha(cel("vlr_saldo")),
            "vlr_expedidos": _num_planilha(cel("vlr_expedidos")),
        })
    return linhas, ignoradas


def _num_planilha(v):
    """Celula de planilha -> float. Vem como '111528790.77' (ponto decimal)."""
    t = (v or "").strip()
    if t in ("", "-", "nan", "None"):
        return 0.0
    try:
        return float(t)
    except ValueError:
        return _num(t)


PARSERS = {"pdf": parse_pdf_padrao, "pdf_texto": parse_pdf_texto,
           "xls": parse_planilha}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tribunal", default="TJBA")
    ap.add_argument("--ano", type=int, help="so um exercicio")
    ap.add_argument("--listar", action="store_true", help="fontes mapeadas")
    a = ap.parse_args()

    if a.listar:
        for sig, cfg in FONTES.items():
            print(f"{sig} ({cfg['uf']}, {cfg['formato']}): "
                  f"{', '.join(map(str, sorted(cfg['anos'])))}")
        return

    sig = a.tribunal.upper()
    if sig not in FONTES:
        sys.exit(f"{sig} sem fonte mapeada. Mapeadas: {', '.join(FONTES)}. "
                 f"Ver o dicionario FONTES no topo.")
    cfg = FONTES[sig]
    parser = PARSERS[cfg["formato"]]
    anos = [a.ano] if a.ano else sorted(cfg["anos"])

    todas, resumo = [], []
    for ano in anos:
        url = cfg["anos"].get(ano)
        if not url:
            print(f"  {ano}: sem URL mapeada"); continue
        ext = "pdf" if cfg["formato"].startswith("pdf") else cfg["formato"]  # xls -> .xls
        dest = os.path.join(CACHE, sig, f"{ano}.{ext}")
        try:
            baixa(url, dest, cfg.get("ssl_relaxado", False))
            linhas, ign = parser(dest, sig, ano)
        except Exception as e:                                    # noqa: BLE001
            print(f"  {ano}: FALHOU — {type(e).__name__}: {e}")
            continue
        # o mapa de um exercicio pode citar outros anos em nota: fica so o do ano
        linhas = [x for x in linhas if x["ano_ref"] == ano]
        deste_trib = sum(1 for x in linhas if x["tribunal"] == sig)
        todas.extend(linhas)
        resumo.append((ano, len(linhas), deste_trib, ign))
        print(f"  {ano}: {len(linhas)} linhas ({deste_trib} do proprio {sig})"
              + (f", {ign} linha(s) ignorada(s)" if ign else ""))

    saida = {"tribunal": sig, "uf": cfg["uf"], "fonte": "Mapa Anual do proprio tribunal "
             "(Res. CNJ 303/2019 art. 85 §1o)", "urls": cfg["anos"],
             "coletado_em": time.strftime("%Y-%m-%d"), "linhas": todas}
    fn = os.path.join(BASE, "data", f"mapa_tribunal_{sig.lower()}.json")
    json.dump(saida, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"OK -> {fn}  ({len(todas)} linhas, {len(resumo)} exercicios)")


if __name__ == "__main__":
    main()
