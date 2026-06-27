# Heracles Coach — Изменения контракта: расширенный `context` коуча (v1.13)

Доп-документ к [SERVER_ADMIN_PROMPT.md](../SERVER_ADMIN_PROMPT.md) и [ADMIN_PROMPT_STORE.md](./ADMIN_PROMPT_STORE.md). Фиксирует, что приложение **уже отправляет** на сервер в `POST /api/coach/messages` начиная с версии **1.13**. Сервер обновлён под этот контракт.

> TL;DR: к старым полям `metrics / questionClass / evidence` добавились параметры пациента — `profile`, `biomarkers`, `bioAge`, `healthScore`. Старые поля не менялись (обратная совместимость сохранена).

---

## 1. Что изменилось в приложении

| Файл | Изменение |
|---|---|
| `services/coach-patient-context.ts` | **Новый.** `buildPatientContext()` собирает параметры пациента из мок-панели + PhenoAge + Health Score. |
| `services/coach.ts` | `CoachServerContext` расширен; `buildServerContext()` подмешивает контекст пациента; `askCoach()` `await`-ит его перед запросом. |
| `app.json` | `version` 1.12 → **1.13**. |

Источник данных пока мок (`services/lab/mock-lab.ts`). При появлении реального авторизованного эндпоинта меняется только `fetchMockLabPanel` — форма payload остаётся прежней.

---

## 2. Новый payload `POST /api/coach/messages`

```jsonc
{
  "message": "How are my testosterone levels?",
  "context": {
    // --- НОВОЕ (v1.13) ---
    "profile": { "sex": "male", "ageYears": 36 },

    "biomarkers": [
      {
        "code": "testosterone_nmolL",
        "label": "Testosterone",
        "value": 17.4,
        "unit": "nmol/L",
        "ref": { "min": 8.6, "max": 29 },
        "status": "normal",          // "normal" | "high" | "low"
        "pillar": "hormonal"         // hormonal|fertility|metabolic|cardiovascular|inflammation
      }
      // ... только ИЗМЕРЕННЫЕ маркеры (без not_measured)
    ],

    "bioAge": {                       // null, если PhenoAge посчитать нельзя
      "phenoAge": 33.2,               // округлено до 0.1
      "chronological": 36,
      "deltaYears": -2.8              // отрицательное = биологически моложе
    },

    "healthScore": {
      "pillars": [
        { "pillar": "hormonal", "label": "Hormonal",
          "state": "complete",        // complete|partial|not_yet_measured
          "score": 88 }               // 0..100 или null
        // ... 5 пилларов
      ],
      "notYetMeasured": ["lh_IUL", "fsh_IUL"]   // коды кодов без значения
    },

    // --- БЕЗ ИЗМЕНЕНИЙ (legacy) ---
    "questionClass": "levels",
    "metrics": { "connected": false, "...": "WHOOP/Health, как раньше" },
    "evidence": [
      { "id": "URO-002", "title": "...", "summary": "...", "url": "..." }
    ]
  }
}
```

Ответ — без изменений: `200 { "text": string, "citationIds": string[] }`.

---

## 3. Маппинг в плейсхолдеры промтов

Сервер кладёт поля `context` в плейсхолдеры `contextBlockTemplate` (см. [coach-prompts.v1.json](./coach-prompts.v1.json)):

| Плейсхолдер | Источник в `context` | Если пусто |
|---|---|---|
| `PROFILE` | `profile` (`firstName` пока не шлётся) | по имеющимся полям |
| `BIOMARKERS` | `biomarkers[]` → строки `Label: value unit (ref min–max, status)` | `not yet measured` |
| `BIO_AGE` | `bioAge` | строку опустить |
| `HEALTH_SCORE` | `healthScore.pillars` + `notYetMeasured` | `not yet measured` |
| `WEARABLE` | `metrics` (legacy) | `no wearable data` |
| `EVIDENCE` | `evidence[]` (или серверная выборка по `prompt.evidence`) | пустой список |
| `USER_QUESTION` | `message` | — |
| `DATE` | серверная дата | — |

`citationIds` в ответе модели фильтруются по id из фактически переданного `EVIDENCE` — выдуманные источники отбрасываются.

---

## 4. Совместимость

- **Старые клиенты (≤1.12)** не присылают `profile/biomarkers/bioAge/healthScore` — сервер обязан подставлять `not yet measured` и работать как раньше.
- **Новые клиенты (≥1.13)** присылают эти поля всегда, когда мок-панель доступна; при сбое загрузки панели поля просто отсутствуют (коуч отвечает без параметров).
- Все новые поля **опциональны** в zod-схеме сервера.

---

## 5. Открытые пункты

- `profile.firstName` пока не передаётся (мок-панель его не содержит) — добавится вместе с реальным профилем пациента.
- `treatment` (план/назначения/следующий приём) из ТЗ §5 ещё не шлётся — появится после интеграции эндпоинта подписки/назначений.
- `promptId` со стороны приложения не передаётся: маршрутизацию по интенту делает сервер. `questionClass` отправляется как подсказка.
