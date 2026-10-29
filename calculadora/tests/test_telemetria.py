"""Telemetria → Elasticsearch: os documentos cabem no mapping `strict` (senão
o ES recusa e a medição some sem ninguém ver), não levam texto nem valor do
processo, e sem ELASTIC_URL nada é enviado."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from prefill import telemetria as T  # noqa: E402

_MAPS = _RAIZ.parent / "scripts" / "elastic"

_PAGINAS = [
    {"pagina": 1, "nativa": True, "texto": "Processo 5001234-56.2021.8.13.0024\nPetição inicial do Fulano"},
    {"pagina": 2, "nativa": True, "texto": "RESUMO DO CÁLCULO\nTotal Partes -> 120.000,00"},
    {"pagina": 3, "nativa": True, "texto": "REQUISIÇÃO DE PAGAMENTO\nBeneficiário: Fulano de Tal\nValor bruto: 120.000,00"},
]
_SUG = [{"tipo": "Conta homologada", "pagina_inicio": 2, "pagina_fim": 2, "origem": "radar"},
        {"tipo": "Ofício requisitório", "pagina_inicio": 3, "pagina_fim": 3, "origem": "pje"}]
_CONF = [{"tipo": "Conta homologada", "pagina_inicio": 2, "pagina_fim": 2},
         {"tipo": "Ofício requisitório", "pagina_inicio": 3, "pagina_fim": 4}]
_RES = {"ok": True, "paginas": 3, "escaneadas": 0,
        "campos": {"valor_total": {"valor": "120.000,00", "citacao": {"pagina": 2, "trecho": "Total"}},
                   "numero_precatorio": {"valor": "5001234-56.2021.8.13.0024", "fonte": "regex"}},
        "prova": {"ok": True, "dif_pct": 0.0}, "rejeitados": [{"campo": "valor_juros"}],
        "conflitos": [], "alertas_pje": [{"tipo": "oficio_data_base"}], "custo": 0.01}


def _caminhos(doc: dict, prefixo="") -> set[str]:
    out = set()
    for k, v in doc.items():
        p = f"{prefixo}{k}"
        if isinstance(v, dict):
            out |= _caminhos(v, p + ".")
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            for x in v:
                out |= _caminhos(x, p + ".")
        else:
            out.add(p)
    return out


def _do_mapping(props: dict, prefixo="") -> set[str]:
    out = set()
    for k, v in props.items():
        if "properties" in v:
            out |= _do_mapping(v["properties"], f"{prefixo}{k}.")
        else:
            out.add(f"{prefixo}{k}")
    return out


@pytest.fixture
def capturados(monkeypatch):
    monkeypatch.setenv("ELASTIC_URL", "http://es.invalido:9200")
    docs = []
    monkeypatch.setattr(T, "_enviar", lambda pares: docs.extend(pares))
    return docs


def _corpo(acao, corpo):
    return corpo["doc"] if "update" in acao else corpo


@pytest.mark.skipif(not _MAPS.is_dir(), reason="mapping fica no App Precatur (scripts/elastic)")
def test_documentos_cabem_no_mapping_strict(capturados):
    T.registrar_analise("s1", b"%PDF", {"paginas": _PAGINAS, "cortes_sugeridos": _SUG,
                                        "n_paginas": 3, "escaneadas": 0,
                                        "pje": {"conta": {"votos": 2, "ancora": {}}, "oficios": [{}],
                                                "alertas": [{"tipo": "x"}]},
                                        "homologacao": {"pagina": 2, "evento": 7},
                                        "radar": {"runs": [(2, 3)]}})
    T.registrar_confirmacao("s1", _PAGINAS, _SUG, _CONF, _RES)
    T.registrar_extracao_direta("s2", "pecas", [], b"%PDF", _RES, pecas=["Conta homologada"])
    T.registrar_envio("s1", {"numero_precatorio": "5001234-56.2021.8.13.0024"},
                      {"numero_precatorio": "5001234-56.2021.8.13.0024", "natureza": "alimentar"})
    maps = {
        T.IDX_ANALISES: _do_mapping(json.loads((_MAPS / "pre_analises.mapping.json").read_text())["mappings"]["properties"]),
        T.IDX_PAGINAS: _do_mapping(json.loads((_MAPS / "pre_analises_paginas.mapping.json").read_text())["mappings"]["properties"]),
    }
    assert capturados
    for acao, corpo in capturados:
        indice = next(iter(acao.values()))["_index"]
        sobra = _caminhos(_corpo(acao, corpo)) - maps[indice]
        assert not sobra, f"{indice}: campos fora do mapping {sobra}"


def test_sem_texto_nem_valor_do_processo(capturados):
    T.registrar_confirmacao("s1", _PAGINAS, _SUG, _CONF, _RES)
    T.registrar_envio("s1", {"numero_precatorio": "5001234-56.2021.8.13.0024"},
                      {"numero_precatorio": "5001234-56.2021.8.13.0024"})
    bruto = json.dumps(capturados, ensure_ascii=False)
    for proibido in ("Fulano", "120.000,00", "5001234-56.2021.8.13.0024", "RESUMO DO"):
        assert proibido not in bruto


def test_tribunal_pelo_cnj_e_avaliacao(capturados):
    T.registrar_confirmacao("s1", _PAGINAS, _SUG, _CONF, _RES)
    analise = _corpo(*capturados[0])
    assert analise["avaliacao"]["conta"]["status"] == "exato"
    assert analise["avaliacao"]["oficio"] == {"status": "parcial", "iou": 0.5, "origem": "pje",
                                              "acertou": True, "desvio_inicio": 0, "desvio_fim": 1}
    paginas = {c["pagina"]: c for _, c in capturados[1:]}
    assert paginas[2]["tribunal"] == "TJMG" and paginas[2]["tipo_confirmado"] == "conta"
    assert paginas[3]["tipo_classificador"] == "oficio" and paginas[3]["classificador_acertou"]


def test_sem_elastic_url_nao_envia(monkeypatch):
    monkeypatch.delenv("ELASTIC_URL", raising=False)
    chamou = []
    monkeypatch.setattr(T, "_fila", type("F", (), {"put_nowait": lambda self, x: chamou.append(x)})())
    T.registrar_confirmacao("s1", _PAGINAS, _SUG, _CONF, _RES)
    assert not chamou and not T.habilitada()


def test_modo_autonomo_acha_o_tribunal_no_pdf(capturados):
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((50, 72), "Processo 5001234-56.2021.8.13.0024")
    T.registrar_extracao_direta("s3", "autonomo", [], doc.tobytes(), {"ok": True, "campos": {}})
    corpo = capturados[-1][1]
    assert corpo["processo"]["tribunal"] == "TJMG" and corpo["processo"]["justica"] == "estadual"
