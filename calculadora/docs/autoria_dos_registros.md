# Autoria dos registros — o que já tem nome e o que ainda não tem

Desde o login individual (`APP_USERS`, ver `auth.py` e a seção "Login
individual" de `ops/DEPLOY.md`), a sessão sabe QUEM está usando o app.
`auth.usuario_atual()` é a única fonte dessa informação — e devolve `None` em
três situações legítimas: ambiente sem login individual, entrada pela senha
compartilhada da migração (`APP_PASSWORD`), e uso local sem env nenhuma.

Regra que vale em todo ponto de escrita: **`None` grava sem autoria, nunca com
autoria inventada.** Um registro sem revisor é um buraco conhecido; um registro
com o revisor errado é uma mentira com cara de rastro, e é ela que estraga o
corpus de gabarito e a auditoria do card.

## Onde a autoria já chega

| Escrita | Onde | Como chega |
|---|---|---|
| Ledger de adjudicação | `hub.registrar_adjudicacao` → `POST /cases/{id}/adjudicacoes` | campo `revisor` (`Adjudicacao.revisor`, nullable) |
| Comentário de auditoria no card | `bitrix.enviar` → `crm.timeline.comment.add` | parâmetro `autor` → "conferido por FULANO na calculadora" |

Sem autor, o comentário volta ao texto genérico ("conferido pelo advogado") e o
`revisor` vai `None`. Coberto por `tests/test_auth.py` e por dois testes em
`tests/test_bitrix.py`.

## A lacuna — escopo da Fase 2 (mudança no hub)

Os outros dois pontos de escrita da calculadora/pré-análise gravam **anônimos**,
e não por esquecimento: a API do hub não tem onde receber o nome.

| Escrita | Cliente | Endpoint | O que falta |
|---|---|---|---|
| Abrir/reencontrar o caso do card | `hub.abrir_caso`, usado em `telas/pre_analise.py` | `POST /cases` (`api/cases.py`, `create_case`) | nenhum campo de autor no `Form()`; `models.Case` não tem coluna |
| Guardar PDF no caso | `hub.guardar_documento`, idem | `POST /cases/{case_id}/documents` (`api/cases.py`, `upload_document`) | idem; `models.Document` não tem coluna |

Consequência prática hoje: dá para saber quem CONFERIU o cálculo (ledger) e
quem MANDOU ao card (comentário), mas não quem abriu o caso nem quem subiu cada
PDF — que é justamente o rastro que interessa quando a peça anexada está errada
ou trocada.

Fechar isso é trabalho no `PrecaturIA/backend`, não aqui. O que ele envolve:

1. coluna nullable de autor em `Case` e `Document` (+ migração);
2. campo opcional no `Form()` dos dois endpoints;
3. `hub.py` passando `auth.usuario_atual()` nas duas chamadas.

**Nullable não é detalhe:** enquanto `APP_PASSWORD` existir como rampa da
migração, uma sessão autenticada pode legitimamente não ter nome. Coluna
obrigatória forçaria o cliente a inventar um valor — exatamente o que a regra do
topo proíbe. Só depois de apagar `APP_PASSWORD` das duas envs a autoria passa a
ser garantida, e aí vale reavaliar.
