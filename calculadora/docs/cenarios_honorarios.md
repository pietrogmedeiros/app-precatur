# Cenários por % de honorário contratual — cobertura do teste e o caso #2405

Contexto: o memorial sai com a seção "Cenários por honorário contratual
(provisório)" (`cenarios_honorarios_contratuais` em
`precaturia/pipeline/calculadora.py`; render em `memorial.py`). A feature nasceu
do caso **#2405 Raquel** (12/08/2026): o closer descontou o honorário "por fora"
(líquido × 0,80 = 442.017,14) e o motor dava **449.484,79** — R$ 7.467,65 de
diferença, vetada pelo Carlos De'Carli no chat do negócio.

## O gabarito real NÃO está travado no teste

`tests/test_memorial_cenarios_honorarios.py` usa **valores sintéticos**
(500.000, RRA de 24 meses). A linha de 20% em **449.484,79** do #2405 não está
pinada porque **os inputs originais não estão no repo** — a reconstrução da
`EntradaCalculadora` feita em 12/08/2026 partiu do memorial em PDF **anexado ao
card #2405** e não foi preservada em script. Para travar o gabarito quando os
inputs estiverem à mão (baixar o anexo exige `BITRIX_COOKIE`; o webhook não
serve download): montar a `EntradaCalculadora` do memorial e afirmar que a
linha de 20% da grade dá exatamente 449.484,79.

O que o teste cobre, no lugar, é o **invariante** que o #2405 revelou:

1. cada linha da grade é idêntica ao centavo a `calcular_dict` com aquele
   percentual (nunca aproximação);
2. o motor dá líquido **maior** que o desconto linear — a direção exata do erro
   do #2405.

## Descoberta: o desconto linear só diverge do motor quando PSS/IR mordem

Achado na primeira rodada do teste (27/08/2026), com valores baixos
(150k/60 meses): a base mensal do IR-RRA ficou **abaixo da isenção**, o IR
estimado zerou, e aí `líquido × (1 − pct)` **coincidiu com o motor ao
centavo**. Não é acaso, é álgebra:

- o PSS estimado é linear na base (14% × base × (1 − pct)), então
  `0,8 × pss` do desconto linear é o mesmo número do motor;
- os honorários são `pct × total`, idênticos nos dois caminhos;
- quem quebra a linearidade é **só o IR-RRA**: a parcela a deduzir torna a
  função afim (`ir(0,8·base) < 0,8·ir(base)` sempre que a parcela > 0) e a
  troca de faixa da tabela progressiva amplia a diferença (no #2405 caiu de
  22,5% para 15%).

Consequência prática: a "conta de padaria" não é sempre errada — é errada
exatamente quando PSS/IR incidem de verdade (valores altos, RRA curto), que é
quando o erro é maior e sempre **contra o líquido** (subtrai demais). Por isso
o teste usa 500k/24 meses: com IR zerado, a desigualdade que ele afirma nem
existiria.
