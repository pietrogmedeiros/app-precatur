# Alfred embutido no App Precatur

O Alfred é a base de consulta de precatórios: dado um número, um CPF ou um nome,
ele diz quanto o crédito vale, em que posição da fila está, como o ente devedor
vem pagando e em que ano a projeção alcança aquele crédito. Vinha da VM
`204-216-151-25` (serviço `alfred.service`, publicado em `busca.precatur.com.br`);
agora roda dentro do app, na tela `/alfred`.

## As camadas

```
Next :3000 ──/alfred──► tela React (components/alfred/*)
     └─ /api/alfred/* ─► Express :8080 ─► Alfred :8610 (servico.py → scripts/api.py)
                           login, papel        SQLite em /app/alfred/data/alfred.db
                           e autoria
```

O Alfred escuta **só em 127.0.0.1**. A base tem nome e CPF de credor: não existe
porta dela para fora, e quem autentica é o login do app.

## O que foi preservado da ferramenta original

- **`scripts/api.py` entra intacto.** Ele já resolve papel, máscara de CPF,
  limite de 90 consultas por minuto e log sem dado pessoal. `servico.py` só
  embrulha (atribuição da consulta + segredo compartilhado) e fecha a UI antiga.
- **CPF mascarado por padrão.** Só o papel `completo` vê inteiro, e só quando
  pede explicitamente (`?completo=1`). Quem define o papel é o perfil do app.
- **CPF nunca em URL.** A busca é `POST /busca` porque o log de acesso registra
  método e caminho — CPF em query string iria para o log.
- **Autoria da consulta.** O Alfred identifica *quem consultou* pelo rótulo do
  token. Vindo pelo app o token é um por papel, então o Express manda o e-mail do
  usuário em `X-Alfred-Usuario` e ele entra no log. Sem isso, a trilha de
  auditoria diria apenas "completo".

## Variáveis de ambiente

| Variável | Onde | Para quê |
|---|---|---|
| `ALFRED_TOKENS` | alfred | `tok:papel:rótulo,...` — defina dois: um `leitor` e um `completo`. |
| `ALFRED_TOKEN_LEITOR` / `ALFRED_TOKEN_COMPLETO` | backend | Os mesmos tokens, para o Express escolher conforme o perfil. |
| `ALFRED_PERFIS_COMPLETO` | backend | Perfis do app que veem CPF inteiro. Padrão `admin`. |
| `ALFRED_SEGREDO` | ambos | Segunda tranca entre Express e Alfred. Opcional. |
| `ALFRED_URL` | backend | Padrão `http://127.0.0.1:8610`. |
| `ALFRED_TIMEOUT_MS` | backend | Padrão 60000. |

Sem `ALFRED_TOKEN_LEITOR` a tela diz que a consulta não está configurada, em vez
de dar erro em cada clique.

## O banco: 308 MB que NÃO estão no git

`alfred.db` tem 923.931 precatórios e 215.290 credores. Ele não cabe no git (nem
deveria: muda sem o código mudar) e não vai na imagem. Mora num **volume**
montado em `/app/alfred/data`.

No EasyPanel: crie um volume do serviço apontando para `/app/alfred/data` e
coloque o arquivo lá. O caminho no host costuma ser
`/etc/easypanel/projects/<projeto>/<serviço>/volumes/<nome>`.

```bash
# na sua máquina (o arquivo comprime de 308 MB para ~95 MB)
gzip -c alfred.db > alfred.db.gz
scp alfred.db.gz usuario@servidor:/tmp/

# no servidor
gunzip -c /tmp/alfred.db.gz > /etc/easypanel/projects/<projeto>/<serviço>/volumes/<nome>/alfred.db
```

Depois reinicie o serviço e confira `/api/alfred/saude`: ele devolve a contagem
de precatórios, que é a prova de que o banco certo subiu.

Os CSVs/JSONs pequenos que o núcleo lê (editais de acordo, mapa do CNJ, RCL,
enquadramento) **vêm na imagem** em `data-seed/` e o `start.sh` os copia para o
volume quando faltarem — nunca sobrescrevendo.

## A base congela, e isso precisa de dono

Na VM, um cron rodava `scripts/rotina_nacp.sh` todo dia às 06:50 coletando o DJEN
e recarregando o banco, com trava, backup pela API do SQLite e rollback se a
saúde não voltasse. **Esse cron não foi trazido**: a ingestão ficou fora do
escopo desta entrega.

Consequência prática: o banco é um retrato de **12/10/2026** e não se move. A
consulta funciona, as projeções continuam corretas para os dados que existem, mas
precatório novo não aparece e pagamento recente não é refletido.

Os coletores vieram junto (`scripts/fetch_*.py`, `db_build.py`,
`rotina_nacp.sh`) justamente para não morrerem com a VM — só não estão ligados.
Religá-los exige: `DATAJUD_APIKEY`, as dependências dos coletores (que não estão
em `requisitos-servico.txt`) e um agendador. **Decisão em aberto.**

## Rodar local

```bash
cd alfred
python3 -m venv .venv && .venv/bin/pip install -r requisitos-servico.txt
cp -n data-seed/* data/                      # os CSVs pequenos
cp /caminho/do/alfred.db data/alfred.db      # o banco
ALFRED_TOKENS="tokleitor:leitor:local,tokchefe:completo:local" \
ALFRED_SEGREDO=seg-local \
  .venv/bin/python -m uvicorn servico:app --host 127.0.0.1 --port 8610 --reload
```

O backend precisa de `ALFRED_TOKEN_LEITOR=tokleitor ALFRED_TOKEN_COMPLETO=tokchefe
ALFRED_SEGREDO=seg-local`.

## Verificar

`tests/teste_busca.py` e `tests/teste_modelo_p23.py` **não são pytest** — são
scripts de regressão que se rodam direto:

```bash
.venv/bin/python tests/teste_busca.py        # busca por nome: FTS × oráculo
.venv/bin/python tests/teste_modelo_p23.py   # escada do §23
```

O primeiro compara o caminho rápido (FTS5 + credor_norm) com uma varredura
ingênua sobre os 215 mil credores — é a prova de que a busca não mudou de
comportamento. O segundo **para no meio**: ele carrega
`data/fixtures_teste/cortes_es.json`, que **não existe no backup da VM** (nem
lá rodava). A parte da escada do §23 passa antes disso.
