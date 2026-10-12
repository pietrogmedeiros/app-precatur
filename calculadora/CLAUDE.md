# Calculadora — instruções para o Claude

**Este diretório é um motor vendorizado.** O código veio de
`github.com/victorkulnig/Calculadora` (o SHA de origem está em `UPSTREAM.txt`) e
hoje roda **dentro do App Precatur** como serviço HTTP interno. Ele não é mais um
app Streamlit em produção — a tela é a `/calculadora` do Next.

- **Não existe deploy daqui.** O aviso antigo ("`git push origin main` = DEPLOY
  EM PRODUÇÃO") valia para o repositório de ORIGEM, que continua existindo e
  servindo a VM do jurídico. Este clone não tem `.git` e **nunca** deve receber
  push para `victorkulnig/Calculadora`. Quem publica esta cópia é o deploy do
  app Precatur (EasyPanel), e push também não garante deploy lá.

- **A fronteira que não pode ser cruzada:** `precaturia/` é o motor e é intocado.
  Toda a adaptação vive em três arquivos nossos — `formulario.py` (lê o
  formulário e monta a `EntradaCalculadora`), `servico.py` (HTTP) e as rotas
  `rotas_documentos.py` / `rotas_crm.py`. Corrigiu algo no motor? Replique no
  repositório de origem, ou a paridade se perde dos dois lados.

- **O teste que protege o porte** é `tests/test_paridade_formulario.py`: ele
  dirige a tela Streamlit REAL (que continua aqui como referência) e compara,
  campo a campo, a `EntradaCalculadora` dela com a que o `formulario.ler` monta.
  Se divergirem, o número muda sem ninguém perceber — nenhum teste do motor
  pegaria isso, porque o motor estaria certo.

- **Testes:** existe venv neste diretório (`.venv`, fora do git).
  `PYTHONIOENCODING=utf-8 .venv/bin/python -m pytest tests -q`. Dois testes de
  sessão do Streamlit (`test_aliquota_padrao::...volta_a_14` e
  `test_prefill_handoff::...sobrevive_ao_rerun`) falham com o Streamlit atual —
  são da tela antiga, que está sendo aposentada.

- **Streamlit não vai para a imagem.** `requirements.txt` é o do repositório de
  origem (serve para rodar os testes de referência);
  `requisitos-servico.txt` é o que a imagem instala.

- **Cenários de honorário contratual**: cobertura do teste, o gabarito não
  travado do caso #2405 e por que o desconto linear só diverge do motor quando
  PSS/IR mordem — ver `docs/cenarios_honorarios.md`.

- **Autoria dos registros**: quem carimba nome no ledger e no card, por que
  `None` grava sem autoria em vez de inventar — ver `docs/autoria_dos_registros.md`.
  No app, a autoria vem do **token JWT**, nunca do corpo da requisição.
