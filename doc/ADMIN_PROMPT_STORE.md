# Heracles — Admin Server: каталог промтов коуча (что хранить и как отдавать)

ТЗ-документ для **админ-сервера** (см. [SERVER_ADMIN_PROMPT.md](../SERVER_ADMIN_PROMPT.md)). Описывает, **какие промты сервер должен хранить, редактировать и применять**, чтобы агенты OpenAI и Claude давали ответы одинаковой структуры с подстановкой реальных параметров пациента.

> Источник истины по содержимому промтов — файл [coach-prompts.v1.json](./coach-prompts.v1.json). Этот документ объясняет, как сервер этот каталог хранит, валидирует, редактирует через админку и собирает финальный промт перед вызовом LLM.

---

## 0. Зачем

Раньше сервер хранил **один** промт (`CoachPrompts { system, userTemplate }`, §2.7 SERVER_ADMIN_PROMPT.md). Теперь нужно хранить **каталог из ~40 интент-промтов** + общий системный промт (для OpenAI и Claude отдельно) + fallback для off-topic. Сервер:

1. получает вопрос пациента и его параметры от приложения;
2. **маршрутизирует** вопрос на нужный промт по `intent`/`keywords` (или на off-topic);
3. собирает финальный prompt = `systemPrompt[provider]` + `contextBlockTemplate` (с подставленными параметрами) + `task` выбранного промта;
4. вызывает OpenAI/Claude;
5. возвращает приложению строгий `{ text, citationIds }` (контракт UI не меняется).

Цель — **структурно одинаковые** ответы у обоих агентов и подстановка наших параметров (биомаркеры, биовозраст, Health Score, носимые устройства).

---

## 1. Что именно хранить

Сервер хранит **один JSON-каталог** целиком (структура файла [coach-prompts.v1.json](./coach-prompts.v1.json)). Поля верхнего уровня:

| Поле | Назначение |
|---|---|
| `version` | Версия каталога. Бампать при изменениях. |
| `updatedAt` | Дата последнего изменения. |
| `description` | Назначение каталога (человеку). |
| `placeholders` | Словарь плейсхолдеров и их смысла (`USER_QUESTION`, `PROFILE`, `BIOMARKERS`, `BIO_AGE`, `HEALTH_SCORE`, `WEARABLE`, `TREATMENT`, `EVIDENCE`, `DATE`). |
| `outputContract` | Строгий контракт ответа: JSON `{ text, citationIds[] }`, без markdown. |
| `systemPrompt.openai` | Системный промт для OpenAI (персона + правила). |
| `systemPrompt.claude` | Системный промт для Claude (та же суть, XML-разметка). |
| `contextBlockTemplate` | Шаблон user-блока с плейсхолдерами; в конце дописывается `task` промта. |
| `responseExamples` | Few-shot примеры (иллюстративные, для удержания стиля). |
| `offTopic` | Fallback-промт, когда вопрос не подходит ни под один интент. |
| `routing` | Стратегия выбора промта + `defaultEvidenceLimit`. |
| `prompts[]` | Массив интент-промтов (см. §1.1). |

### 1.1 Элемент `prompts[]`

```jsonc
{
  "id": "testosterone-levels",        // уникальный, стабильный — на него ссылается логирование/аналитика
  "intent": "levels",                  // переиспользует классы вопросов приложения
  "title": "Interpret testosterone / free T / SHBG",
  "keywords": ["testosterone", "free t", "shbg", ...],   // для маршрутизации
  "evidence": {                        // какие источники подтягивать из Evidence Register
    "domains": ["URO", "END-R", "BIO"],
    "tags": ["testosterone", "trt", "hypogonadism"],
    "limit": 3
  },
  "task": "Interpret the patient's total testosterone..."  // дописывается в конец user-промта
}
```

Поддерживаемые `intent` (8 классов, совпадают с приложением): `levels`, `general`, `test`, `train`, `recovery`, `workout`, `eat`, `sleep`. Плюс `off_topic` у fallback.

---

## 2. Модель хранения на сервере

Расширяем `RemoteConfig` из SERVER_ADMIN_PROMPT.md §2.1. **Не ломаем** старое поле — добавляем каталог рядом.

```ts
// types.ts — дополнение
export interface PromptEvidenceQuery {
  domains: string[];
  tags: string[];
  limit: number;
}

export interface CoachPromptEntry {
  id: string;
  intent: string;
  title: string;
  keywords: string[];
  evidence: PromptEvidenceQuery;
  task: string;
}

export interface CoachPromptCatalog {
  version: string;
  updatedAt: string;
  description?: string;
  placeholders: Record<string, string>;
  outputContract: unknown;            // хранится как есть, в LLM не уходит
  systemPrompt: { openai: string; claude: string };
  contextBlockTemplate: string;
  responseExamples?: unknown[];        // few-shot, опционально подмешиваются
  offTopic: { id: string; intent: string; title: string; description?: string; task: string };
  routing: { strategy: string; defaultEvidenceLimit: number };
  prompts: CoachPromptEntry[];
}

export interface RemoteConfig {
  ai: { provider: AiProvider; openai: ProviderConfig; claude: ProviderConfig };
  prompts: CoachPrompts;              // LEGACY single-prompt — оставить для отката
  promptCatalog: CoachPromptCatalog;  // НОВОЕ — каталог из coach-prompts.v1.json
  updatedAt: string;
  updatedBy: string | null;
}
```

### 2.1 Seed / дефолт

- `defaultConfig()` инициализирует `promptCatalog` содержимым файла [coach-prompts.v1.json](./coach-prompts.v1.json) (положить копию в `server/src/data/coach-prompts.v1.json` и импортировать/прочитать на старте).
- Если каталог в store отсутствует (старый store.json) → при чтении подставить seed-каталог и записать обратно (мягкая миграция).

### 2.2 Валидация (zod)

При `PUT` каталога и при загрузке seed проверять:
- `systemPrompt.openai` и `systemPrompt.claude` — непустые строки;
- `contextBlockTemplate` содержит все плейсхолдеры из `placeholders`;
- `prompts[].id` — **уникальны**, непустые;
- `prompts[].intent` ∈ разрешённого набора;
- `prompts[].evidence.limit` ∈ 0..10;
- `offTopic.task` непуст.

---

## 3. Сборка финального промта (`coach.ts`)

При `POST /api/coach/messages`:

1. **Выбор промта** (`selectPrompt(question, questionClass)`):
   - если приложение прислало `context.questionClass`/`promptId` — взять соответствующий промт;
   - иначе подобрать по `keywords`/`intent` (классификатор или эмбеддинги);
   - если уверенность низкая или совпадений нет → `offTopic`.
2. **Системный промт**: `catalog.systemPrompt[provider]` (`openai` или `claude`).
3. **User-блок**: взять `catalog.contextBlockTemplate`, подставить плейсхолдеры из `context` приложения:
   - `USER_QUESTION` ← `message`;
   - `PROFILE`, `BIOMARKERS`, `BIO_AGE`, `HEALTH_SCORE`, `WEARABLE`, `TREATMENT` ← из `context` (см. §5);
   - `EVIDENCE` ← источники, полученные из Evidence Register по `prompt.evidence.{domains,tags,limit}` (или те, что прислало приложение);
   - `DATE` ← сегодня.
   - В конец дописать `prompt.task` (или `offTopic.task`).
4. (Опц.) подмешать 1–2 `responseExamples` как few-shot перед вопросом — для стабильности структуры.
5. Вызвать `callOpenAI`/`callClaude` (как в §2.5 SERVER_ADMIN_PROMPT.md), `response_format: json_object` для OpenAI.
6. `parseReply(raw, allowedIds)` — `text` обязателен; `citationIds` фильтруются по id из переданного `EVIDENCE` (**модель не может выдумать источник**).

### 3.1 Источники (EVIDENCE)

Два варианта, на выбор реализации:
- **Сервер сам** достаёт кандидатов из Evidence Register по `prompt.evidence` (предпочтительно — единая логика);
- **или** доверяет списку `context.evidence[]` от приложения (как сейчас в legacy-контракте).

В обоих случаях `allowedIds` = id фактически переданных в промт источников.

---

## 4. Админка — редактирование каталога

Дополнить Config form (§4 SERVER_ADMIN_PROMPT.md):

- **Системные промты**: две textarea — `systemPrompt.openai`, `systemPrompt.claude`. Показать список плейсхолдеров.
- **Шаблон контекста**: textarea `contextBlockTemplate` (с подсказкой плейсхолдеров).
- **Каталог промтов**: таблица `prompts[]` с CRUD по строкам (`id`, `intent`, `title`, `keywords`, `evidence.domains/tags/limit`, `task`). Запрет дублей `id`.
- **Off-topic**: отдельное поле `offTopic.task`.
- **Импорт/экспорт**: загрузить/скачать весь каталог как JSON (формат = [coach-prompts.v1.json](./coach-prompts.v1.json)) — удобно для версионирования и переноса.
- Save → `PUT /admin/coach/catalog` (валидация zod, проставить `updatedAt`/`updatedBy`).

---

## 5. Контракт с приложением (расширение `context`)

Приложение шлёт в `POST /api/coach/messages` обновлённый `context`. Сейчас оно отдаёт только `metrics` (WHOOP) + `evidence`; для новых промтов нужно добавить параметры пациента:

```jsonc
{
  "message": "How are my testosterone levels?",
  "context": {
    "promptId": "testosterone-levels",     // опц.: если приложение само классифицировало
    "questionClass": "levels",
    "profile":   { "firstName": "Alex", "sex": "male", "ageYears": 36 },
    "biomarkers": [ { "code": "testosterone_nmolL", "value": 17.4, "unit": "nmol/L", "ref": { "min": 8.6, "max": 29 }, "status": "normal" } ],
    "bioAge":    { "phenoAge": 33.2, "chronological": 36, "deltaYears": -2.8 },
    "healthScore": { "hormonal": 88, "fertility": 71, "metabolic": 90, "cardiovascular": 74, "inflammation": 95 },
    "wearable":  { "recovery": 78, "hrv": 64, "rhr": 52, "sleepScore": 81 },
    "treatment": { "plan": "TRT", "nextAppointment": "2026-07-10" },
    "metrics":   { "...": "legacy WHOOP-поля, как сейчас" },
    "evidence":  [ { "id": "URO-002", "title": "...", "summary": "...", "url": "..." } ]
  }
}
```

Сервер маппит эти поля в плейсхолдеры `contextBlockTemplate`. Любое отсутствующее поле → подставить `not yet measured` / `no wearable data` / опустить строку.

> Источники параметров в приложении: `services/lab/mock-lab.ts` (биомаркеры + PhenoAge), `services/health-score/scoring.ts` (Health Score), `stores/whoop-store.ts` (wearable). Сейчас `buildServerContext` в [services/coach.ts](../../services/coach.ts) шлёт только WHOOP — это отдельная задача по интеграции на стороне приложения.

---

## 6. API (дополнение к §2.8 SERVER_ADMIN_PROMPT.md)

**Admin (под `requireAdmin`):**
- `GET /admin/coach/catalog` → текущий `promptCatalog`.
- `PUT /admin/coach/catalog` → заменить каталог целиком (zod-валидация, §2.2). Вернуть сохранённый каталог.
- (Опц.) `PUT /admin/coach/catalog/prompts/:id` → точечное редактирование одного промта.

**Public / приложение:**
- `GET /api/coach/config` → `{ provider }` (без изменений; каталог наружу **не** отдаём).
- `POST /api/coach/messages` → как §3, ответ `{ text, citationIds }`.

Каталог промтов — **внутренний**: публично не раскрывается, уходит только результат.

---

## 7. Чек-лист внедрения

1. Добавить типы `CoachPromptCatalog` и поле `promptCatalog` в `RemoteConfig`.
2. Положить [coach-prompts.v1.json](./coach-prompts.v1.json) в `server/src/data/` и сделать seed + мягкую миграцию старого store.
3. zod-валидация каталога (§2.2).
4. `selectPrompt()` + сборка финального промта (§3); ветка `systemPrompt[provider]`.
5. Маппинг расширенного `context` → плейсхолдеры (§5).
6. Admin endpoints + форма редактирования каталога (§4, §6).
7. Smoke-test: по одному вопросу на каждый `intent` + один off-topic; проверить, что `citationIds` не содержат выдуманных id и структура ответа одинакова на OpenAI и Claude.
