# Calculadora de Precatórios — Precatur

> **Esta cópia roda embutida no App Precatur.** O motor (`precaturia/`) é servido
> por HTTP em `127.0.0.1:8090` (`servico.py`) e a tela é a `/calculadora` do
> Next. O Streamlit continua aqui como **referência de paridade** e base dos
> testes — não é o que o usuário abre. Ver `CLAUDE.md` para a fronteira entre o
> que é motor e o que é adaptação, e `LEIAME-EMBUTIDO.md` para variáveis de
> ambiente e como rodar local.

App Streamlit **standalone** da calculadora manual. Contém **apenas** o motor de
cálculo determinístico (`precaturia/pipeline`) + os índices públicos do BACEN.
**Nenhum dado de cliente** — o advogado digita os números; nada é armazenado.

Reusa o mesmo motor do sistema completo (`calcular_dict`), então os números são
**idênticos** (paridade estrutural).

## Rodar localmente

```bash
pip install -r requirements.txt
streamlit run Calculadora.py
# http://localhost:8501
```

## Deploy — Streamlit Community Cloud

1. Suba esta pasta para um **repositório GitHub privado** próprio (só a calculadora).
2. share.streamlit.io → **Create app** → aponte para `Calculadora.py`.
3. O Community Cloud instala o `requirements.txt` (só `streamlit`) e aplica o
   tema de `.streamlit/config.toml`.

### Liberar só para o time (allowlist)

App → **Settings → Sharing → "Only specific people can view"** → adicione os
e-mails do time. (Repo privado + allowlist = só quem está na lista acessa.)

## Atualizações

- **Código:** commit + push → redeploy automático (Render).
- **Índices:** automatizado. A GitHub Action `atualizar-indices` roda
  mensalmente (dia 12), regenera os CSVs (histórico BACEN SGS + **projeção
  Focus**) e commita se mudou → redeploy. Rodar na mão:
  `python scripts/baixar_indices.py` (urllib puro, sem deps) ou disparar o
  workflow (`workflow_dispatch`).

### Projeção Focus (meses futuros)

IPCA (433), IPCA-E (proxy do IPCA) e SELIC (meta anual Focus → base 252, dias
úteis reais) são **projetados** de `último_real+1` até **dezembro do ano
seguinte**, marcados na 3ª coluna `origem` do CSV. O valor REAL do SGS sempre
substitui a projeção quando o mês é publicado (o mês corrente parcial da SELIC é
descartado). **INPC não é projetado** (não entra na atualização ao presente).
Quando a oferta ancora em meses projetados, o app mostra um aviso ("valores
estimados de mercado, não índice oficial"). Metodologia em
`scripts/projecao_focus.py`.

## Estrutura

```
Calculadora.py              formulário + render (Streamlit)
requirements.txt            streamlit
.streamlit/config.toml      tema da marca
scripts/
  baixar_indices.py         SGS real + merge da projeção → CSVs
  projecao_focus.py         projeção Focus (IPCA/IPCA-E/SELIC) + dias úteis
.github/workflows/
  atualizar-indices.yml     cron mensal (regenera índices + redeploy)
tests/test_projecao_focus.py  testes offline da projeção
precaturia/
  pipeline/
    calculadora.py          camada fina: monta payload e chama o motor
    cenarios.py             motor de cenários (homologado × sentencial)
    calculo_pss.py          PSS determinístico
    calculo_ir.py           IR-RRA determinístico
    credor_advogado.py      classificação credor/advogado
    indices/                aplicar_regime + loader das séries
  data/indices/*.csv        IPCA-E, IPCA, SELIC, INPC (dados públicos BACEN)
```

> Sincronia: este é um subconjunto do sistema principal. Ao corrigir o motor no
> sistema, replique aqui (ou vice-versa) para manter a paridade.
