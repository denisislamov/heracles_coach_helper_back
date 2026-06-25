# Heracles — Admin Server + Admin Panel: build prompt

Промт-документ для **отдельного проекта** (свой git-репозиторий), который потом подключается к мобильному приложению Heracles Coach. Содержит: цель, архитектуру backend, архитектуру админки (Expo Router web), контракт интеграции с приложением, деплой на **Render.com** и пошаговый план.

> Дай этот файл AI-агенту или разработчику как ТЗ. Всё, что нужно для воспроизведения, — внутри.

---

## 0. Цель

Вынести **remote config** мобильного приложения на сервер и дать админ-панель, через которую можно:

- хранить **ключи** для OpenAI / Claude (Anthropic) — **только на сервере**, в зашифрованном виде;
- хранить и редактировать **промпты** ИИ-коуча (system + user template);
- переключать провайдера ИИ;
- заводить/сбрасывать/блокировать админов (без email-восстановления в v1, вручную из админки);
- seed-админ: `islamov.denis@gmail.com`.

### Поведение ИИ-коуча (требования заказчика)

1. **Ключа нет** (`provider = none`) → приложение работает как сейчас (локальный мок-коуч в приложении).
2. **Ключ есть** → бэкенд вызывает соответствующий ИИ.
3. Поведение аналогичное текущему: советы по восстановлению/сну/тренировкам, ссылки на исследования (citations), используются параметры из приложения (метрики). Промпты хранятся в админке.

### Безопасность (критично — OWASP Mobile M1/M9)

- API-ключи провайдеров **никогда** не уходят на мобильный клиент.
- Приложение получает только текстовые ответы коуча.
- Наружу (публичный конфиг) отдаётся только `{ provider }`, без ключей.
- Admin-view маскирует ключи: возвращает `hasKey: boolean`, а не сам ключ.

---

## 1. Технологический стек

**Backend** (без нативных зависимостей — легко деплоится на Render):

- Node.js (LTS, ≥ 20) + TypeScript, ESM (`"type": "module"`).
- Express 4.
- Хранилище: **JSON-файл** с атомарной записью (tmp + rename) и in-memory кэшем. (На Render — Persistent Disk, см. §6. Позже можно заменить на Postgres.)
- Шифрование секретов: `node:crypto`, **AES-256-GCM**.
- Хеш паролей: `node:crypto` **scrypt** + `timingSafeEqual`.
- Авторизация админки: **JWT** (`jsonwebtoken`), TTL 12 ч.
- Валидация входа: **zod**.
- Вызовы LLM: глобальный `fetch` (Node ≥ 20), без SDK.
- Dev-runner: `tsx` (`node --watch --import tsx`).

**Admin panel:** Expo Router (web target) — деплой через Expo/EAS Hosting или статикой. Простая SPA: логин → форма конфига.

---

## 2. Backend — структура файлов

```
server/
  package.json
  tsconfig.json
  .env.example
  .gitignore            # node_modules/, dist/, .env, data/
  src/
    env.ts              # загрузка и валидация переменных окружения
    crypto.ts           # AES-256-GCM encrypt/decrypt секретов; scrypt hash/verify; randomPassword
    types.ts            # доменные типы и публичные/админ DTO
    store.ts            # JSON-store: read/update, дефолтные промпты и конфиг
    auth.ts             # JWT sign + requireAdmin middleware
    llm.ts              # callOpenAI / callClaude
    coach.ts            # сборка промпта, парсинг ответа, runCoach()
    views.ts            # toAdminView (маскировка ключей) / toPublicView
    seed.ts             # ensureSeedAdmin()
    index.ts            # express app, маршруты, healthcheck, listen
    routes/
      auth.ts           # POST /admin/auth/login
      admin.ts          # GET/PUT /admin/config; CRUD админов
      coach.ts          # GET /api/coach/config; POST /api/coach/messages
```

### 2.1 Доменная модель (`types.ts`)

```ts
export type AiProvider = 'none' | 'openai' | 'claude';

export interface ProviderConfig { apiKeyEnc: string | null; model: string; }

export interface CoachPrompts {
  system: string;        // персона + правила безопасности + правила цитирования
  userTemplate: string;  // плейсхолдеры {{metrics}} {{evidence}} {{question}}
}

export interface RemoteConfig {
  ai: { provider: AiProvider; openai: ProviderConfig; claude: ProviderConfig };
  prompts: CoachPrompts;
  updatedAt: string;
  updatedBy: string | null;
}

export interface AdminUser {
  id: string; email: string; passwordHash: string; createdAt: string; disabled: boolean;
}

export interface StoreData { admins: AdminUser[]; config: RemoteConfig; }

// Публичные/админ DTO
export interface ProviderConfigPublic { hasKey: boolean; model: string; }
export interface RemoteConfigAdminView {
  ai: { provider: AiProvider; openai: ProviderConfigPublic; claude: ProviderConfigPublic };
  prompts: CoachPrompts; updatedAt: string; updatedBy: string | null;
}
export interface RemoteConfigPublicView { provider: AiProvider; }
```

### 2.2 Хранилище (`store.ts`)

- `store.read(): Promise<StoreData>` — кэш + чтение файла; если файла нет → `defaultData()`.
- `store.update(mutator): Promise<StoreData>` — читает, применяет мутатор, **атомарно** пишет (`writeFile(tmp)` → `rename(tmp, file)`), обновляет кэш.
- `defaultConfig()`: `provider: 'none'`, `openai.model: 'gpt-4o-mini'`, `claude.model: 'claude-3-5-sonnet-latest'`, оба `apiKeyEnc: null`.
- `DEFAULT_PROMPTS` — см. §2.7.

### 2.3 Шифрование (`crypto.ts`)

- `masterKey()`: base64-декод `SECRETS_MASTER_KEY`, должно быть **ровно 32 байта**.
- `encryptSecret(plain)` → строка формата `v1:<ivB64>:<tagB64>:<cipherB64>` (AES-256-GCM, random 12-byte IV).
- `decryptSecret(enc)` → plaintext (валидирует префикс `v1`).
- `hashPassword(pw)` → `scrypt:<saltB64>:<hashB64>` (scrypt N=16384 по умолчанию, keylen 64).
- `verifyPassword(pw, stored)` → `timingSafeEqual`.
- `randomPassword(len=18)` → URL-safe random (для сброса/seed).

### 2.4 Авторизация (`auth.ts`)

- `signAdminToken({ sub, email })` → JWT, `expiresIn: '12h'`, secret = `JWT_SECRET`.
- `requireAdmin` middleware: читает `Authorization: Bearer <token>`, верифицирует, кладёт `{ sub, email }` в `req.admin`; иначе `401`.

### 2.5 LLM-клиенты (`llm.ts`)

- `callOpenAI({ apiKey, model, system, user })`:
  - `POST https://api.openai.com/v1/chat/completions`
  - body: `{ model, messages: [{role:'system',content:system},{role:'user',content:user}], temperature: 0.4, response_format: { type: 'json_object' } }`
  - вернуть `choices[0].message.content` (строка).
- `callClaude({ apiKey, model, system, user })`:
  - `POST https://api.anthropic.com/v1/messages`
  - headers: `x-api-key`, `anthropic-version: 2023-06-01`, `content-type: application/json`
  - body: `{ model, max_tokens: 1024, temperature: 0.4, system, messages: [{role:'user',content:user}] }`
  - вернуть `content[0].text`.
- Оба: при `!res.ok` → `throw new Error('<provider> error <status>: <body>')`.

### 2.6 Коуч (`coach.ts`)

- `coachRequestSchema` (zod):
  ```
  message: string (1..4000),
  context: {
    metrics?: Record<string, unknown>,
    questionClass?: string,
    evidence?: { id: string; title?: string; summary?: string; url?: string }[]  // max 50
  }
  ```
- `CoachReply = { text: string; citationIds: string[] }`.
- `class CoachUnavailableError extends Error` — кидается, если `provider === 'none'` или нет ключа.
- `renderTemplate(tpl, vars)` — подстановка `{{metrics}}` / `{{evidence}}` / `{{question}}`.
- `formatEvidence(items)` — список `"[id] title — summary (url)"`.
- `parseReply(raw, allowedIds)`:
  - толерантный `extractJson` (вырезать JSON-объект из текста, если модель добавила лишнее);
  - `text` обязателен; `citationIds` фильтруются по `allowedIds` (id из переданного приложением evidence) — **модель не может выдумать источник**.
- `runCoach(req)`:
  1. `store.read()`; если `provider === 'none'` или `apiKeyEnc` пуст → `throw CoachUnavailableError`.
  2. `decryptSecret` ключ; собрать `system` (из config.prompts) и `user` (renderTemplate с метриками/evidence/вопросом).
  3. `provider === 'openai' ? callOpenAI : callClaude`.
  4. `parseReply` → `CoachReply`.

### 2.7 Дефолтные промпты (`DEFAULT_PROMPTS`)

`system` (смысл — воспроизвести персону текущего мок-коуча):

```
You are the Heracles AI health coach. You give concise, practical recovery, sleep,
training and lifestyle guidance for adults on TRT/ED/weight-loss programmes. Ground
advice in the user's supplied metrics when relevant. Be supportive and specific, not
generic.
Safety: you are not a doctor; never diagnose, never change prescribed medication, and
advise contacting their clinician for medical concerns.
Citations: you may ONLY cite from the provided evidence list, using their ids. Never
invent sources.
Respond ONLY with JSON: {"text": string, "citationIds": string[]}.
```

`userTemplate`:

```
User metrics:
{{metrics}}

Evidence you may cite (id — title):
{{evidence}}

User question:
{{question}}
```

### 2.8 Маршруты

**`routes/auth.ts`**
- `POST /admin/auth/login` — body `{ email, password }` (zod). `verifyPassword`; при успехе `{ token, admin: { id, email } }`. Ошибка — **обобщённая** (`invalid_credentials`), не раскрывать, что именно неверно. Блокированный админ (`disabled`) → ошибка.

**`routes/admin.ts`** (все под `requireAdmin`)
- `GET /admin/config` → `toAdminView(config)` (ключи замаскированы).
- `PUT /admin/config` — zod-патч:
  - `ai.provider?: 'none'|'openai'|'claude'`
  - `ai.openai?: { model?: string; apiKey?: string | null }` — строка → зашифровать и сохранить; `null` → очистить; **omit** → не трогать.
  - `ai.claude?: { ... }` аналогично.
  - `prompts?: { system?: string; userTemplate?: string }`.
  - проставить `updatedAt`, `updatedBy = req.admin.email`. Вернуть `toAdminView`.
- `GET /admin/admins` → список `{ id, email, createdAt, disabled }`.
- `POST /admin/admins` — `{ email, password(min8) }` → создать (uniq email).
- `POST /admin/admins/:id/reset-password` — `{ password? }`; если пусто — сгенерировать и вернуть **один раз** в ответе.
- `POST /admin/admins/:id/disable` — `{ disabled: boolean }`; **запретить блокировать последнего активного админа**.

**`routes/coach.ts`**
- `GET /api/coach/config` → `toPublicView(config)` = `{ provider }`. **Публичный**, без ключей.
- `POST /api/coach/messages`:
  - валидация `coachRequestSchema`;
  - `AbortController` timeout 30 с;
  - `runCoach` → `200 { text, citationIds }`;
  - `CoachUnavailableError` → `409 { error: 'coach_unavailable' }` (приложение использует свой мок);
  - прочая ошибка → `502 { error: 'coach_failed' }`.
  - **TODO до прода:** закрыть пользовательской авторизацией приложения + rate-limit (сейчас открыт для интеграции).

### 2.9 Seed (`seed.ts`) и `index.ts`

- `ensureSeedAdmin()`: если есть админы — no-op; иначе создать `SEED_ADMIN_EMAIL` с `SEED_ADMIN_PASSWORD` (или random, напечатать в лог **один раз**).
- `index.ts`: express + `cors` (origins из `CORS_ORIGINS`) + `express.json({ limit: '256kb' })`; `GET /health` → `{ ok: true }`; смонтировать `/admin/auth`, `/admin`, `/api/coach`; 404-fallback; `ensureSeedAdmin()` на старте; `listen(PORT)`.

### 2.10 Переменные окружения (`.env.example`)

```
PORT=4000
CORS_ORIGINS=http://localhost:8081,http://localhost:19006
JWT_SECRET=                 # node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"
SECRETS_MASTER_KEY=         # node -e "console.log(require('crypto').randomBytes(32).toString('base64'))" (РОВНО 32 байта)
SEED_ADMIN_EMAIL=islamov.denis@gmail.com
SEED_ADMIN_PASSWORD=        # пусто → сгенерируется и напечатается один раз
DATA_FILE=./data/store.json
```

`env.ts` валидирует обязательные `JWT_SECRET` и `SECRETS_MASTER_KEY` (иначе фейл на старте).

### 2.11 `package.json` scripts

```
dev:       node --watch --import tsx src/index.ts
build:     tsc
start:     node dist/index.js
seed:      node --import tsx src/seed.ts
typecheck: tsc --noEmit
```

deps: `cors`, `dotenv`, `express@^4`, `jsonwebtoken@^9`, `zod@^3`
devDeps: `@types/cors`, `@types/express`, `@types/jsonwebtoken`, `@types/node`, `tsx`, `typescript@^5`

---

## 3. Контракт интеграции с мобильным приложением

Базовый URL бэкенда настраивается в приложении (`constants/api.ts`). Контракт ответа коуча **идентичен** текущему мок-коучу, чтобы UI не менялся.

1. На старте/при открытии коуча: `GET {BASE}/api/coach/config` → `{ provider }`.
2. Если `provider === 'none'` → приложение использует локальный `generateMockAIReply` (как сейчас).
3. Иначе `POST {BASE}/api/coach/messages`:
   ```json
   {
     "message": "How is my recovery?",
     "context": {
       "metrics": { "...": "из HealthKit/Health Connect/приложения" },
       "questionClass": "recovery",
       "evidence": [ { "id": "E1", "title": "...", "summary": "...", "url": "..." } ]
     }
   }
   ```
   - `evidence` — кандидаты из `pickTopEvidence` (services/evidence.ts), как в моке.
   - Ответ `200 { text, citationIds }` — отрисовать как сейчас.
   - `409` (coach_unavailable) или сетевая ошибка/timeout → **fallback** на `generateMockAIReply`.

> Эту часть НЕ делаем сейчас. Подключим, когда сервер переедет в свой репозиторий и задеплоится.

---

## 4. Admin panel (Expo Router web)

Минимальная SPA, общается с admin API.

**Экраны/функции:**
- **Login**: email + password → `POST /admin/auth/login`, хранить JWT в памяти/`localStorage`. Авто-выход по 401.
- **Config form** (`GET/PUT /admin/config`):
  - провайдер: radio `none | openai | claude`;
  - OpenAI: поле `model` + поле `API key` (показывает «ключ задан» из `hasKey`; кнопки «Сохранить ключ» и «Очистить» → `apiKey: string | null`);
  - Claude: то же;
  - промпты: textarea `system` + textarea `userTemplate` (показать доступные плейсхолдеры);
  - кнопка Save → `PUT /admin/config`.
- **Admins** (`/admin/admins`): список; создать; сбросить пароль (показать сгенерированный один раз); включить/выключить.

**UX-замечания:** ключи никогда не показываются (только `hasKey`); все вызовы с `Authorization: Bearer`.

Деплой админки — через Expo (web export) или EAS Hosting (см. §6.3).

---

## 5. Пошаговый план запуска

1. Создать новый репозиторий, перенести `server/` (структура из §2).
2. `npm install`, заполнить `.env` (сгенерировать `JWT_SECRET`, `SECRETS_MASTER_KEY`).
3. `npm run typecheck` → чисто. `npm run dev` → `GET /health` ok.
4. Smoke-test: login → `GET/PUT /admin/config` (выставить ключ, проверить `hasKey: true`) → `POST /api/coach/messages` с реальным ключом.
5. Задеплоить backend на Render (§6).
6. Сделать админку (§4), задеплоить (§6.3), завести/проверить админов.
7. Подключить приложение (§3): сервис конфига + вызов коуча + fallback на мок.

---

## 6. Деплой на Render.com

### 6.1 Backend — Render **Web Service**

- New → **Web Service** → подключить репозиторий (или Public Git URL).
- **Root Directory:** `server` (если монорепо) или корень.
- **Runtime:** Node.
- **Build Command:** `npm install && npm run build`
- **Start Command:** `npm start`  *(запускает `node dist/index.js`)*
- **Health Check Path:** `/health`
- **Instance type:** Starter (или Free для теста — учти, что Free засыпает после простоя и теряет содержимое эфемерного диска).

**Environment Variables** (Render → Environment):
```
JWT_SECRET=<48 random bytes base64url>
SECRETS_MASTER_KEY=<32 random bytes base64>
SEED_ADMIN_EMAIL=islamov.denis@gmail.com
SEED_ADMIN_PASSWORD=<надёжный пароль>     # или оставить пустым и взять из логов первого запуска
CORS_ORIGINS=https://<твоя-админка>.onrender.com,https://<expo-web-domain>
DATA_FILE=/data/store.json                # путь на Persistent Disk (см. ниже)
```
Render сам прокидывает `PORT` — `env.ts` должен читать `process.env.PORT`.

**Persistent Disk** (обязателен для JSON-store, иначе данные стираются при редеплое):
- Render → твой сервис → **Disks** → Add Disk.
- Name: `data`; **Mount Path:** `/data`; Size: 1 GB.
- Тогда `DATA_FILE=/data/store.json`. Каталог должен создаваться, если его нет (store.ts: `mkdir -p` перед записью).

> Альтернатива для прод-масштаба: завести **Render PostgreSQL** и заменить JSON-store на таблицы (`admins`, `config`). Контракт API не меняется.

#### `render.yaml` (Blueprint, опционально)

```yaml
services:
  - type: web
    name: heracles-admin-server
    runtime: node
    rootDir: server
    plan: starter
    buildCommand: npm install && npm run build
    startCommand: npm start
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: JWT_SECRET
        generateValue: true
      - key: SECRETS_MASTER_KEY
        sync: false          # задать вручную: ровно 32 байта base64
      - key: SEED_ADMIN_EMAIL
        value: islamov.denis@gmail.com
      - key: SEED_ADMIN_PASSWORD
        sync: false
      - key: CORS_ORIGINS
        sync: false
      - key: DATA_FILE
        value: /data/store.json
    disk:
      name: data
      mountPath: /data
      sizeGB: 1
```
> Примечание: `generateValue` даёт случайную строку, но **не гарантирует ровно 32 байта** для `SECRETS_MASTER_KEY` — его задавай вручную (`sync: false`).

### 6.2 Проверка после деплоя

```
curl https://<service>.onrender.com/health
curl -X POST https://<service>.onrender.com/admin/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"islamov.denis@gmail.com","password":"<пароль>"}'
```

### 6.3 Admin panel — деплой

Вариант A (рекомендуется для простоты): Render **Static Site** из Expo web export.
- Build: `npx expo export -p web` (или `--output-dir dist`), **Publish Directory:** `dist`.
- В админке базовый URL backend задать через env (`EXPO_PUBLIC_API_URL=https://<service>.onrender.com`).
- Добавить домен админки в `CORS_ORIGINS` backend.

Вариант B: задеплоить админку через Expo/EAS Hosting (как договаривались про «деплой через expo»). Тогда backend всё равно на Render.

---

## 7. Чек-лист безопасности

- [ ] Ключи провайдеров только на сервере, в шифре (AES-256-GCM); наружу — никогда.
- [ ] Публичный `/api/coach/config` отдаёт только `{ provider }`.
- [ ] Admin-view маскирует ключи (`hasKey`), не отдаёт шифртекст.
- [ ] Пароли — scrypt + `timingSafeEqual`; ошибки логина обобщённые.
- [ ] JWT с TTL; `requireAdmin` на всех admin-маршрутах.
- [ ] `SECRETS_MASTER_KEY` ровно 32 байта; секреты в Render Env, не в git; `.env` и `data/` в `.gitignore`.
- [ ] CORS только для доменов админки/приложения.
- [ ] До прода: авторизация пользователя приложения + rate-limit на `/api/coach/messages`.
- [ ] `citationIds` фильтруются по переданному списку evidence (нет выдуманных источников).
```
