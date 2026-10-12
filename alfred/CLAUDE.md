# Alfred — instruções para o Claude

**Diretório vendorizado.** O código veio da VM `204-216-151-25`
(`/home/ubuntu/alfred`, serviço `alfred.service`, publicado em
`busca.precatur.com.br`) e hoje roda dentro do App Precatur como serviço HTTP
interno, servindo a tela `/alfred`. A VM vai ser desligada.

- **A fronteira:** `scripts/` é o Alfred e entra INTACTO — `api.py` inclusive.
  Nossa adaptação é só `servico.py` (atribuição da consulta + segredo) e a rota
  `backend/src/routes/alfred.ts`. Nada de regra de consulta aqui.

- **Privacidade não é detalhe.** A base tem nome e CPF de 215 mil credores. As
  três regras do Alfred valem e já estão implementadas: CPF mascarado por
  padrão, CPF nunca em URL (busca é POST), e log atribuível sem dado pessoal.
  Quem vê CPF inteiro vem de `ALFRED_PERFIS_COMPLETO` (padrão: só admin) —
  mudar isso é decisão de privacidade, não de código.

- **O banco não está no git.** 308 MB em `data/alfred.db`, por volume. Se
  `/api/alfred/saude` não devolve a contagem, o volume está vazio — ver
  `LEIAME-EMBUTIDO.md`.

- **Os testes NÃO são pytest.** São scripts (`python tests/teste_busca.py`).
  `teste_modelo_p23.py` morre no meio por falta de um fixture que não veio no
  backup; a parte da escada do §23 roda antes disso.

- **A base está congelada em 12/10/2026.** O cron de ingestão do DJEN
  (`scripts/rotina_nacp.sh`, 06:50 diário) ficou fora do escopo. Os coletores
  vieram junto mas não estão ligados. Antes de "consertar" um dado que parece
  velho, confira se não é só isto.
