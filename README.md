# App Precatur — Sales Dashboard

Plataforma de dashboard de vendas com design monocromático (preto & branco) inspirado no **shadcn/ui**.

- **Frontend** (`frontend/`) — Next.js 14 + Tailwind + shadcn/ui + Recharts → deploy na **Vercel**.
- **Backend** (`backend/`) — Express + TypeScript + Postgres → container **Docker** para **EasyPanel** (Hostinger).

## Funcionalidades

Menu lateral **recolhível** com categoria **Dashboard**:

| Painel | Conteúdo |
|--------|----------|
| **Dados Sales** | KPIs agregados (`total_leads`, `qualificados`, `convertidos`, `taxa_qualificacao`, `taxa_conversao`, `valor_pipeline`), funil, medidores de taxa e evolução mensal. |
| **Dados Individuais** | Métricas por `owner` (mesmas colunas), gráfico comparativo e tabela ordenável. |

Interface **totalmente responsiva**. Acesso protegido por **login** (JWT) com dois perfis:

- **admin** — acessa tudo + categoria **Administração › Usuários** (adicionar/remover usuários).
- **padrao** — acessa apenas os painéis.

### Credenciais iniciais (padrão — troque em produção)

- E-mail: `admin@precatur.com`
- Senha: `precatur`

O admin inicial é criado no primeiro boot via `ADMIN_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
Senhas são armazenadas como **hash SHA-256** na tabela `users`.

---

## 1. Rodar localmente

### Backend + Postgres (dev) via Docker

> Usa `docker-compose.dev.yml`, que sobe um Postgres descartável **só para desenvolvimento**.
> (Em produção o Postgres é o da VM — veja a seção de deploy.)

```bash
docker compose -f docker-compose.dev.yml up --build
```

Sobe Postgres em `localhost:5432` e a API em `http://localhost:8080` (migração + admin + seed automáticos).

```bash
curl http://localhost:8080/api/health
# login
curl -X POST http://localhost:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@precatur.com","password":"precatur"}'
```

### Frontend

```bash
cd frontend
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8080
npm install
npm run dev                  # http://localhost:3000
```

### Backend sem Docker

```bash
cd backend
cp .env.example .env         # ajuste DATABASE_URL para seu Postgres
npm install
npm run migrate && npm run seed
npm run dev                  # http://localhost:8080
```

---

## 2. Deploy do backend (EasyPanel / Docker na VM)

O **Postgres já existe na VM**, então o container roda **só a API** apontando para ele.

### Opção A — EasyPanel (recomendado)

1. Crie um serviço **App** a partir deste repositório, pasta `backend/` (build via `Dockerfile`).
2. Configure as variáveis de ambiente:

   ```
   DATABASE_URL=postgres://usuario:senha@HOST_DO_POSTGRES:5432/precatur
   PORT=8080
   CORS_ORIGIN=https://SEU-PROJETO.vercel.app
   ADMIN_NAME=Admin
   ADMIN_EMAIL=admin@precatur.com
   ADMIN_PASSWORD=uma-senha-forte
   JWT_SECRET=string-aleatoria-longa
   JWT_TTL=12h
   MIGRATE_ON_START=true
   SEED_ON_START=false          # sem dados demo em produção
   ```

   > `HOST_DO_POSTGRES` = nome do serviço Postgres no EasyPanel, ou o host/IP do
   > Postgres da VM. Se exigir SSL, use `?sslmode=require`.

3. Exponha a porta `8080` e associe um domínio. A API responde em `https://SEU-BACKEND/api/...`.

### Opção B — docker-compose na VM

`docker-compose.yml` sobe **apenas a API** (sem Postgres):

```bash
cp .env.example .env    # preencha DATABASE_URL com o Postgres da VM
docker compose up -d --build
```

> Se o Postgres roda no host da VM (fora do Docker), use
> `DATABASE_URL=postgres://user:pass@host.docker.internal:5432/precatur`
> (o mapeamento `host.docker.internal` já está no compose).

No primeiro boot: as tabelas `leads` e `users` são criadas (migração idempotente) e o admin inicial é criado.

## 3. Deploy do frontend (Vercel)

1. Importe o repositório na Vercel, **Root Directory** = `frontend/`.
2. Environment Variables: `NEXT_PUBLIC_API_URL=https://SEU-BACKEND`.
3. Deploy (Next.js detectado automaticamente).

> Garanta que `CORS_ORIGIN` no backend contenha o domínio da Vercel.

---

## Modelo de dados

**leads** — fonte das métricas:

```sql
leads(id, owner, status['novo'|'qualificado'|'convertido'|'perdido'], value, created_at)
```

Métricas calculadas por SQL em `backend/src/queries.ts`:

- `total_leads`, `qualificados` (`qualificado`+`convertido`), `convertidos`
- `taxa_qualificacao` = qualificados / total_leads
- `taxa_conversao` = convertidos / qualificados
- `valor_pipeline` = soma de `value` dos leads em aberto (`novo` + `qualificado`)

**users** — autenticação (senha em SHA-256):

```sql
users(id, name, email UNIQUE, password[sha256], role['admin'|'padrao'], created_at)
```

## API

| Método | Rota | Auth | Descrição |
|--------|------|------|-----------|
| GET | `/api/health` | público | Status da API e do banco |
| POST | `/api/auth/login` | público | Login (`email`, `password`) → `{ token, user }` |
| GET | `/api/metrics/summary` | autenticado | Métricas agregadas (Dados Sales) |
| GET | `/api/metrics/by-owner` | autenticado | Métricas por owner (Dados Individuais) |
| GET | `/api/metrics/funnel` | autenticado | Estágios do funil |
| GET | `/api/metrics/timeseries` | autenticado | Séries mensais |
| GET | `/api/users` | admin | Lista usuários |
| POST | `/api/users` | admin | Cria usuário (`name`, `email`, `password`, `role`) |
| DELETE | `/api/users/:id` | admin | Remove usuário |
