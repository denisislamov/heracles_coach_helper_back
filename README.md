# Heracles — Admin Server + Admin Panel

Remote-config backend and admin panel for the Heracles Coach mobile app. The backend
stores AI provider keys (OpenAI / Claude) **encrypted, server-side only**, serves the
AI coach, and exposes a JWT-protected admin API. The admin panel (Expo Router web) is a
minimal SPA to manage config, prompts and admins.

Built from `SERVER_ADMIN_PROMPT.md` (kept in the repo as the spec).

## Repository layout

```
server/   Node 20 + TypeScript + Express backend (JSON-file store, AES-256-GCM secrets, JWT)
admin/    Expo Router (web) admin SPA
render.yaml   Render.com Blueprint for the backend
```

## Security model

- Provider API keys never leave the server and are stored encrypted (AES-256-GCM).
- Public endpoint `GET /api/coach/config` returns only `{ provider }` — no keys.
- Admin views mask keys (`hasKey: boolean`, never the ciphertext).
- Passwords: scrypt + `timingSafeEqual`; login errors are generic (`invalid_credentials`).
- JWT (12h TTL); `requireAdmin` guards all admin routes.
- `citationIds` from the model are filtered against the evidence ids the app supplied —
  the model cannot invent sources.

---

## Backend (`server/`)

### Local setup

```bash
cd server
npm install
cp .env.example .env
# generate secrets:
node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"   # JWT_SECRET
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"      # SECRETS_MASTER_KEY (EXACTLY 32 bytes)
# paste both into .env, then:
npm run typecheck
npm run dev          # GET http://localhost:4000/health -> { ok: true }
```

On first start, if no admins exist, a seed admin (`SEED_ADMIN_EMAIL`) is created. If
`SEED_ADMIN_PASSWORD` is empty, a random password is generated and printed **once** in
the logs.

### Scripts

| Script              | Action                                  |
| ------------------- | --------------------------------------- |
| `npm run dev`       | watch mode via tsx                      |
| `npm run build`     | `tsc` → `dist/`                         |
| `npm start`         | `node dist/index.js`                    |
| `npm run seed`      | create the seed admin                   |
| `npm run typecheck` | `tsc --noEmit`                          |

### API

Public (used by the mobile app):

- `GET /health` → `{ ok: true }`
- `GET /api/coach/config` → `{ provider }`
- `POST /api/coach/messages` → `{ text, citationIds }`
  - `409 { error: 'coach_unavailable' }` when provider is `none` or no key (app falls back to its local mock)
  - `502 { error: 'coach_failed' }` on provider error/timeout (30s)

Admin (JWT, `Authorization: Bearer <token>`):

- `POST /admin/auth/login` → `{ token, admin }`
- `GET /admin/config` → masked config
- `PUT /admin/config` → patch provider/model/key/prompts (key: string → encrypt, `null` → clear, omit → keep)
- `GET /admin/admins`
- `POST /admin/admins` → `{ email, password (min 8) }`
- `POST /admin/admins/:id/reset-password` → `{ password? }` (empty → generated, returned once)
- `POST /admin/admins/:id/disable` → `{ disabled }` (cannot disable the last active admin)

### Smoke test

```bash
curl localhost:4000/health
TOKEN=$(curl -s -X POST localhost:4000/admin/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"islamov.denis@gmail.com","password":"<password>"}' | jq -r .token)
curl localhost:4000/admin/config -H "authorization: Bearer $TOKEN"
```

---

## Admin panel (`admin/`)

Minimal Expo Router web SPA: **Login → Config form → Admins**.

```bash
cd admin
npm install
cp .env.example .env   # set EXPO_PUBLIC_API_URL to the backend URL
npm run web            # dev
npm run export         # static web build -> dist/
```

> Note: the Expo dependency tree is large; run `npm install` locally (it was not fully
> installed in the build sandbox). The backend was installed, typechecked and
> smoke-tested.

Screens:

- **Login** — `POST /admin/auth/login`; JWT kept in memory + `localStorage`; auto-logout on 401.
- **Config** — provider radio (`none|openai|claude`), per-provider model + API key (shows
  “key is set”, Save / Clear), prompt textareas with the available placeholders.
- **Admins** — list, create, reset password (shown once), enable/disable.

Keys are never displayed — only `hasKey`.

---

## Deploy on Render.com

### Backend — Web Service

- Build: `npm install && npm run build` · Start: `npm start` · Health: `/health`
- Root dir: `server`
- Add a **Persistent Disk** mounted at `/data` (1 GB) and set `DATA_FILE=/data/store.json`
  (the JSON store is wiped on redeploy without it).
- Environment: `JWT_SECRET`, `SECRETS_MASTER_KEY` (exactly 32 bytes base64, set manually),
  `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `CORS_ORIGINS`, `DATA_FILE`.

`render.yaml` (Blueprint) is included. `generateValue` does **not** guarantee 32 bytes,
so set `SECRETS_MASTER_KEY` manually.

### Admin panel

Render **Static Site** from the Expo web export: build `npx expo export -p web --output-dir dist`,
publish directory `dist`, set `EXPO_PUBLIC_API_URL`, and add the panel domain to the
backend's `CORS_ORIGINS`.

---

## Mobile app integration (later)

The coach response contract matches the app's current mock so the UI is unchanged:

1. `GET {BASE}/api/coach/config` → if `provider === 'none'`, use the local mock.
2. Else `POST {BASE}/api/coach/messages` with `{ message, context: { metrics, questionClass, evidence } }`.
3. `200 { text, citationIds }` renders as today; `409` / network error / timeout → fall back to the mock.

**Before prod:** add app-user auth + rate-limit on `/api/coach/messages`.
