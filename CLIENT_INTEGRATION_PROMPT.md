# Heracles — Client Integration: build prompt

Промт-документ для **мобильного приложения Heracles Coach** (Expo / React Native). Описывает, как приложение ходит на admin-сервер (см. `SERVER_ADMIN_PROMPT.md`), забирает конфиг и ответы ИИ-коуча, и как делает fallback на локальный мок. Контракт ответа коуча **идентичен** текущему мок-коучу, поэтому UI не меняется.

> Отдай этот файл AI-агенту или разработчику приложения как ТЗ на интеграцию. Сервер уже реализован и задеплоен — здесь только клиентская часть.

---

## 0. Цель

Сейчас коуч в приложении — локальный мок (`generateMockAIReply`). Нужно:

1. При открытии коуча спросить у сервера, включён ли ИИ (`GET /api/coach/config`).
2. Если ИИ **выключен** (`provider === 'none'`) → работать как сейчас (локальный мок).
3. Если ИИ **включён** → отправлять вопрос + метрики + кандидаты-источники на сервер (`POST /api/coach/messages`) и рисовать ответ.
4. При любой ошибке/таймауте/`409` → **молча падать обратно на мок**. Пользователь не должен видеть ошибку — коуч всегда отвечает.

**Важно по безопасности:** приложение **никогда** не хранит и не получает ключи OpenAI/Claude. Оно получает только текст ответа и список id источников. Ключи живут только на сервере.

---

## 1. Конфигурация базового URL

Файл `constants/api.ts`:

```ts
// Базовый URL admin-сервера (Render). Можно переопределить через env.
export const COACH_API_BASE =
  process.env.EXPO_PUBLIC_COACH_API_URL ?? 'https://<service>.onrender.com';
```

`.env` приложения:

```
EXPO_PUBLIC_COACH_API_URL=https://<service>.onrender.com
```

> На время разработки можно ставить `http://localhost:4000`. На iOS-симуляторе `localhost` работает; на Android-эмуляторе используйте `http://10.0.2.2:4000`.

---

## 2. Контракт API (что отдаёт сервер)

### 2.1 `GET /api/coach/config` — публичный, без ключей

Ответ `200`:

```json
{ "provider": "none" }
```

`provider` ∈ `"none" | "openai" | "claude"`. Больше ничего наружу не отдаётся (ключи скрыты).

### 2.2 `POST /api/coach/messages`

**Тело запроса:**

```json
{
  "message": "How is my recovery?",
  "context": {
    "metrics": { "...": "произвольные метрики из HealthKit / Health Connect / приложения" },
    "questionClass": "recovery",
    "evidence": [
      { "id": "E1", "title": "Sleep & HRV", "summary": "...", "url": "https://..." }
    ]
  }
}
```

Ограничения (валидируются на сервере, zod):
- `message` — строка, 1..4000 символов (обязательно).
- `context.metrics` — произвольный объект (опционально).
- `context.questionClass` — строка (опционально).
- `context.evidence` — массив, **максимум 50** элементов; у каждого обязателен `id`, остальное (`title`, `summary`, `url`) — опционально.

**Успех `200`:**

```json
{ "text": "Your recovery looks solid...", "citationIds": ["E1"] }
```

- `text` — готовый текст ответа коуча (рисуем как сейчас).
- `citationIds` — массив id, **только из тех, что приложение прислало в `evidence`**. Сервер фильтрует выдуманные источники, так что модель не может сослаться на то, чего вы не передавали. Маппинг id → источник делает приложение (как в моке).

**Ошибки:**

| Статус | Тело                                | Что делать в приложении                          |
| ------ | ----------------------------------- | ------------------------------------------------ |
| `409`  | `{ "error": "coach_unavailable" }`  | ИИ выключен или нет ключа → **fallback на мок**  |
| `502`  | `{ "error": "coach_failed" }`       | Ошибка/таймаут провайдера → **fallback на мок**  |
| `400`  | `{ "error": "invalid_body", ... }`  | Невалидное тело (баг клиента) → **fallback на мок** |

Сервер сам обрывает вызов LLM по таймауту 30 с. На клиенте всё равно ставим свой таймаут (см. §3).

---

## 3. Клиентский сервис (`services/coach.ts`)

Создать модуль, который инкапсулирует поход на сервер и решение «сервер или мок».

```ts
import { COACH_API_BASE } from '../constants/api';
import { generateMockAIReply } from './mockCoach'; // существующий мок
import { pickTopEvidence } from './evidence';       // существующий подбор источников

export type AiProvider = 'none' | 'openai' | 'claude';

export interface EvidenceItem {
  id: string;
  title?: string;
  summary?: string;
  url?: string;
}

export interface CoachReply {
  text: string;
  citationIds: string[];
}

export interface CoachContext {
  metrics?: Record<string, unknown>;
  questionClass?: string;
  evidence?: EvidenceItem[];
}

const CLIENT_TIMEOUT_MS = 30_000;

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);
  try {
    const res = await fetch(`${COACH_API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
    });
    if (!res.ok) {
      const err = new Error(`http_${res.status}`);
      (err as any).status = res.status;
      throw err;
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

/** Кэшируем provider, чтобы не дёргать config на каждое сообщение. */
let cachedProvider: { value: AiProvider; at: number } | null = null;
const CONFIG_TTL_MS = 60_000;

export async function getCoachProvider(): Promise<AiProvider> {
  if (cachedProvider && Date.now() - cachedProvider.at < CONFIG_TTL_MS) {
    return cachedProvider.value;
  }
  try {
    const { provider } = await fetchJson<{ provider: AiProvider }>('/api/coach/config');
    cachedProvider = { value: provider, at: Date.now() };
    return provider;
  } catch {
    return 'none'; // сервер недоступен → ведём себя как мок
  }
}

/**
 * Главная точка входа коуча. Всегда возвращает ответ:
 * сервер, если ИИ включён и доступен; иначе локальный мок.
 */
export async function askCoach(
  message: string,
  context: CoachContext = {},
): Promise<CoachReply> {
  const provider = await getCoachProvider();
  if (provider === 'none') {
    return mockReply(message, context);
  }

  try {
    const reply = await fetchJson<CoachReply>('/api/coach/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message, context }),
    });
    // на всякий случай: пустой text → мок
    if (!reply?.text) return mockReply(message, context);
    return reply;
  } catch {
    // 409 / 502 / 400 / сеть / таймаут — единый fallback
    return mockReply(message, context);
  }
}

function mockReply(message: string, context: CoachContext): CoachReply {
  const text = generateMockAIReply(message, context.metrics);
  // мок тоже может цитировать те же кандидаты-источники
  const citationIds = (context.evidence ?? []).slice(0, 2).map((e) => e.id);
  return { text, citationIds };
}
```

> Адаптируйте сигнатуры `generateMockAIReply` / `pickTopEvidence` под то, что реально есть в проекте — имена выше ориентировочные.

---

## 4. Сборка контекста запроса

Перед вызовом `askCoach` приложение собирает `context`:

1. **`metrics`** — актуальные метрики пользователя (сон, HRV, RHR, вес, шаги и т.п.) из HealthKit / Health Connect / локального состояния. Передавайте plain-объектом; сервер сам сериализует их в промпт.
2. **`questionClass`** — класс вопроса (например `recovery` / `sleep` / `training` / `nutrition`), если приложение его уже определяет.
3. **`evidence`** — кандидаты-источники из существующего `pickTopEvidence` (как в моке). Каждому — стабильный `id`; именно эти `id` вернутся в `citationIds`.

Пример вызова из экрана коуча:

```ts
const evidence = pickTopEvidence(question, metrics); // как сейчас
const reply = await askCoach(question, {
  metrics,
  questionClass: classify(question),
  evidence,
});
renderCoachMessage(reply.text, reply.citationIds); // как сейчас
```

---

## 5. Поведение UI (без изменений)

- Текст ответа рисуется как сегодня для мока.
- `citationIds` маппятся в карточки источников через тот же реестр, что и раньше (id → title/url).
- Никаких новых состояний ошибки на экране: если сервер недоступен или ИИ выключен — пользователь видит обычный (мок) ответ.
- Опционально (необязательно): показывать маленький бейдж «AI» когда ответ пришёл с сервера (`provider !== 'none'`), если продукту это нужно. По умолчанию — не показывать.

---

## 6. Пошаговый план интеграции

1. Добавить `EXPO_PUBLIC_COACH_API_URL` в `.env` и `constants/api.ts`.
2. Создать `services/coach.ts` (§3), переиспользовав существующие `generateMockAIReply` и `pickTopEvidence`.
3. В экране коуча заменить прямой вызов мока на `askCoach(...)`.
4. Проверить три сценария:
   - сервер с `provider: 'none'` → отвечает мок;
   - сервер с включённым провайдером и валидным ключом → отвечает ИИ, источники только из переданных;
   - сервер выключен / таймаут / `409` → молча мок.
5. Прогнать на iOS и Android (учесть `10.0.2.2` для Android-эмулятора).

---

## 7. Чек-лист

- [ ] Ключи провайдеров на клиент **не приходят** и не хранятся (только `text` + `citationIds`).
- [ ] `provider` берётся из `GET /api/coach/config`, кэшируется (TTL ~60 с).
- [ ] `message` обрезается/валидируется до 4000 символов; `evidence` ≤ 50.
- [ ] Любая ошибка (`409` / `502` / `400` / сеть / таймаут) → fallback на мок, без видимой ошибки.
- [ ] `citationIds` рендерятся только если id есть в переданном `evidence`.
- [ ] Базовый URL вынесен в env, не захардкожен.
- [ ] (До прода, согласовать с бэком) добавить авторизацию пользователя приложения + rate-limit на `/api/coach/messages` — сейчас эндпоинт открыт для интеграции.
```
