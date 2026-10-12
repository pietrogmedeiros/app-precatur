# Calculadora embutida no App Precatur

Como a calculadora do jurídico passou a viver dentro do app, o que é preciso
configurar e como mexer nela sem quebrar o número.

## Por que o motor continua em Python

O cálculo são ~5.200 linhas de regra jurídico-financeira em `Decimal` (EC 113,
EC 136, art. 12-A da Lei 7.713, Súmula 368, superpreferência, Temas 810/905,
séries do BACEN). Reescrever isso em TypeScript não é portar uma fórmula: é
reproduzir decisões que o time já conferiu caso a caso. A escolha foi manter o
**mesmo código** e dar a ele uma porta HTTP — assim "o número é igual" é um fato
estrutural, não uma esperança.

## As três camadas

```
Next :3000  ──/calculadora──►  tela React (components/calculadora/*)
     │
     └─ /api/calculadora/* ──►  Express :8080  (backend/src/routes/calculadora.ts)
                                      │          login, papéis e a autoria do CRM
                                      │
                                      └──────►  Python :8090  (servico.py)
                                                  formulario.py → precaturia/
```

O motor escuta **só em 127.0.0.1**. Quem o expõe é o Express, que já tem o login
do app. A autoria que vai para o card do CRM é lida do **token**, nunca do corpo
da requisição.

## Variáveis de ambiente

| Variável | Onde | Para quê |
|---|---|---|
| `MOTOR_URL` | backend | Endereço do motor. Padrão `http://127.0.0.1:8090`. |
| `MOTOR_SEGREDO` | backend + motor | Segunda tranca: se definida, o motor só aceita requisições com o mesmo segredo. Opcional (o motor já é interno). |
| `MOTOR_TIMEOUT_MS` | backend | Teto da chamada. Padrão 300000 (5 min) — a leitura de um processo escaneado passa de um minuto. |
| `PREFILL_ENABLED` | motor | `1` liga a leitura de PDF. Desligado, a tela esconde a seção. |
| `OPENROUTER_API_KEY` | motor | Chave do modelo que extrai os campos. Sem ela, a extração responde 503 explicando. |
| `PREFILL_MODELO` | motor | Modelo do OpenRouter (tem padrão no código). |
| `PREFILL_OCR` | motor | `off` desliga o OCR. Ligado, usa o tesseract da imagem. |
| `PREFILL_SESSAO_TTL` | motor | Validade da sessão do assistente de corte, em segundos (padrão 3600). |
| `BITRIX_WEBHOOK` | motor | Liga o envio ao card. Sem ela, a tela não mostra o painel do CRM. |
| `BITRIX_PORTAL`, `BITRIX_CATEGORIA` | motor | Portal e funil permitido para escrita. |
| `HUB_URL`, `HUB_USER`, `HUB_PASS` | motor | Opcional: registra snapshot/journal do envio. Sem elas tudo funciona, só não guarda. |

Nada disso é obrigatório para a calculadora em si: sem nenhuma variável, o
cálculo e o memorial em PDF funcionam. As variáveis ligam os **extras**.

## Rodar local

```bash
# 1) motor
cd calculadora
python3 -m venv .venv && .venv/bin/pip install -r requisitos-servico.txt
.venv/bin/python -m uvicorn servico:app --host 127.0.0.1 --port 8090 --reload

# 2) backend (a porta 8080 não é negociável: o proxy do Next é assado no build)
cd ../backend && PORT=8080 MOTOR_URL=http://127.0.0.1:8090 npx tsx src/index.ts

# 3) frontend
cd ../frontend && BACKEND_URL=http://127.0.0.1:8080 npx next dev -p 3055
```

Sem `--reload` no uvicorn, mudança em `.py` **não** entra: o processo serve o
código que carregou no boot.

## Testes

```bash
cd calculadora
.venv/bin/pip install -r requirements.txt pytest   # requirements traz o streamlit
.venv/bin/python -m pytest tests -q
```

O teste que importa para esta adaptação é `tests/test_paridade_formulario.py`.
Ele roda a tela Streamlit original e confere que `formulario.ler` monta a MESMA
`EntradaCalculadora` — é o que garante que a tela nova não mudou o resultado.

## Atualizar o motor a partir do repositório de origem

1. `git clone --depth 1 https://github.com/victorkulnig/Calculadora.git /tmp/calc-novo`
2. Copie **só** o motor e os dados: `precaturia/`, `memorial.py`, `numeros.py`,
   `bitrix.py`, `hub.py`, `versao.py`, `prefill/`, `assets/`, `scripts/`, `tests/`.
3. Mantenha os arquivos desta adaptação: `formulario.py`, `servico.py`,
   `rotas_documentos.py`, `rotas_crm.py`, `requisitos-servico.txt`,
   `UPSTREAM.txt`, `LEIAME-EMBUTIDO.md`, `CLAUDE.md`.
4. Atualize o SHA em `UPSTREAM.txt` e rode a suíte. Se o teste de paridade
   falhar, o formulário da origem mudou — alinhe `formulario.py` antes de subir.

## Os índices envelhecem — e isso precisa de dono

Os índices do BACEN vivem em `precaturia/data/indices/*.csv`. No repositório de
origem uma GitHub Action os regenera todo dia 12; **nesta cópia não há nada que
faça isso**. Sem atualização, o motor continua calculando: ele só passa a usar a
projeção do Boletim Focus para os meses que o BACEN já publicou, e o valor sai
abaixo (ou acima) do índice oficial.

Isso não corre em silêncio: a tela mostra no topo até que mês cada índice é
**oficial**, e o resultado ganha o aviso de projeção sempre que a data-alvo passa
desse mês. É o sinal de que está na hora de atualizar.

Atualizar na mão (sem dependências, só urllib):

```bash
cd calculadora && python3 scripts/baixar_indices.py
```

Se o Focus estiver fora do ar, o script **aborta sem sobrescrever** — nunca grava
projeção pela metade. Depois é commit + deploy, como qualquer mudança de código.

Fica em aberto automatizar isso (uma Action mensal neste repositório, ou um
refresh no boot do contêiner). Enquanto não houver, atualizar o motor a partir da
origem é também atualizar os índices.
