# Subir para a VM — passo a passo da janela

> Nada aqui foi aplicado. O deploy tem cron a cada 2 min: **o push é o gatilho**,
> e a partir dele o relógio corre. Por isso o cron é desligado ANTES.

## Antes de começar
- avisar o time: a calculadora vai reiniciar e o que estiver na tela se perde;
- horário de baixo uso (`ss -tn state established '( sport = :8501 )'` mostra quem está conectado).

## 1. Congelar o deploy automático
```bash
crontab -l > /tmp/cron.bak
crontab -l | sed 's|^\*/2 .*deploy-calculadora.sh|#&|' | crontab -
```

## 2. Publicar
```powershell
# na máquina do Victor
cd C:\Users\victo\Precatur\Calculadora
git checkout main && git merge --ff-only feat/prefill
git push origin main
```

## 3. Aplicar na VM
```bash
cd ~/calculadora && git fetch origin main && git reset --hard origin/main
.venv/bin/pip install -q -r requirements.txt          # pymupdf, numpy, httpx

sudo cp ops/calculadora.service /etc/systemd/system/  # ⚠ ExecStart: Calculadora.py
sudo cp ops/preanalise.service  /etc/systemd/system/
sudo install -m 0640 -o root -g root /dev/null /etc/preanalise/env   # criar antes de preencher
sudo systemctl daemon-reload
```

### ⚠ `/etc/calculadora/env` também precisa do CRM

O botão "Enviar para o card" vive na CALCULADORA — é lá que existem o resultado
e o memorial, e o número que vai para o card tem de ser o que o advogado
conferiu na tela. Com os apps separados, a sessão da calculadora nunca tem os
PDFs (ficam no processo da pré-análise), então `HUB_URL` deixa de ser plano B:
é o único caminho dos anexos.

Acrescentar ao que já existe lá (`APP_PASSWORD`):
```
BITRIX_WEBHOOK=<webhook>
BITRIX_CATEGORIA=9
HUB_URL=https://hub.204-216-151-25.sslip.io/api
HUB_USER=precatur
HUB_PASS=<senha do basic auth>
APP_USERS=<ver "Login individual" abaixo>
```

O bloco de envio aparece para quem usa a calculadora — é aceitável porque a
trava de funil só permite escrever no 9 (sandbox). No go-live do funil 0, essa
decisão precisa ser revista.

`/etc/preanalise/env` (chaves NÃO entram no repositório):
```
APP_PASSWORD=<a mesma senha do time>
APP_USERS=<a mesma lista da calculadora>
PREFILL_ENABLED=1
PREFILL_MODELO=google/gemini-3.1-flash-lite
OPENROUTER_API_KEY=<chave>
BITRIX_WEBHOOK=<webhook>
BITRIX_CATEGORIA=9
HUB_URL=https://hub.204-216-151-25.sslip.io/api
HUB_USER=precatur
HUB_PASS=<senha do basic auth>
CALCULADORA_URL=https://204-216-151-25.sslip.io
```

### Login individual (`APP_USERS`)

Quem envia ao card carimba o próprio nome no comentário de auditoria e no
`revisor` do ledger de adjudicação. Com a senha única não havia de onde tirar
esse nome; é para isso que existe o login por pessoa.

Uma entrada por pessoa, `usuario:hash`, separadas por vírgula — **na mesma
linha** (`EnvironmentFile` do systemd não aceita valor multilinha):
```
APP_USERS=ana:pbkdf2_sha256$210000$…$…,victor:pbkdf2_sha256$210000$…$…
```
Cada hash sai de `python scripts/hash_senha.py <usuario>` (pede a senha sem
eco e imprime a linha pronta). **Senha em claro não é aceita**: entrada
malformada é ignorada em silêncio — e ignorar um usuário barra o acesso dele,
nunca abre a porta.

`APP_USERS` e `APP_PASSWORD` convivem **de propósito**: enquanto as senhas
individuais não estão distribuídas, quem deixar o campo "Usuário" vazio ainda
entra com a senha do time — só que sem autoria (o card e o ledger saem sem
nome, como hoje). **Terminada a migração, apagar `APP_PASSWORD` das duas envs**
é o que fecha a rampa e torna a autoria obrigatória.

As duas envs (`/etc/calculadora/env` e `/etc/preanalise/env`) precisam da MESMA
`APP_USERS`: são processos separados e cada um autentica por conta própria.

## 4. Subir os serviços
```bash
sudo systemctl restart calculadora            # <- único momento de indisponibilidade
sudo systemctl enable --now preanalise
systemctl is-active calculadora preanalise
curl -sf -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501
curl -sf -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8502
```

## 5. Publicar a rota nova
```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%s)
cat ops/Caddyfile.preanalise | sudo tee -a /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

## 6. Deploy seletivo + religar o cron
```bash
cp ~/deploy-calculadora.sh ~/deploy-calculadora.sh.bak
cp ops/deploy-calculadora.sh ~/deploy-calculadora.sh && chmod +x ~/deploy-calculadora.sh
crontab /tmp/cron.bak
```

## 7. Conferir
- `https://204-216-151-25.sslip.io` — calculadora, **igual a antes**;
- `https://pre.204-216-151-25.sslip.io` — pré-análise;
- um caso ponta a ponta até o card do funil 9.

## Se der errado
```bash
sudo cp /etc/systemd/system/calculadora.service /tmp/  # guarda a versão nova
git -C ~/calculadora reset --hard bbd96b2              # último estado bom conhecido
sudo sed -i 's/Calculadora.py/streamlit_app.py/' /etc/systemd/system/calculadora.service
sudo systemctl daemon-reload && sudo systemctl restart calculadora
```
A pré-análise pode ficar parada sem afetar ninguém: `sudo systemctl stop preanalise`.

## Depois (fora da janela)
- `PRE_ANALISE_URL=https://pre.204-216-151-25.sslip.io` no `.env` do Callix +
  scp do `analise_watcher.py` → a tarefa do advogado ganha o atalho;
- `sudo apt install tesseract-ocr tesseract-ocr-por` → contas escaneadas (~1 em 5).
