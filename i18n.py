"""Локализация: RU + EN. t(key, lang, **params) с фолбэком на русский.

Динамику от ИИ (название блюда, советы) не держим здесь — её модель отдаёт на
языке пользователя (см. ai.py, параметр lang).
"""

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"


def norm_lang(code: str) -> str:
    """Telegram language_code -> поддерживаемый язык."""
    if not code:
        return DEFAULT_LANG
    code = code.lower()
    if code.startswith("ru") or code.startswith("uk") or code.startswith("be"):
        return "ru"
    return "en"


_WEEKDAYS = {
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


def weekday(i: int, lang: str = DEFAULT_LANG) -> str:
    return (_WEEKDAYS.get(lang) or _WEEKDAYS[DEFAULT_LANG])[i]


def t(key: str, lang: str = DEFAULT_LANG, **params) -> str:
    table = _STR.get(lang) or _STR[DEFAULT_LANG]
    s = table.get(key)
    if s is None:
        s = _STR[DEFAULT_LANG].get(key, key)
    return s.format(**params) if params else s


_STR = {
    "ru": {
        # общее
        "menu": "Главное меню:",
        "done": "Готово!",
        "lang_name": "Русский",
        # меню (кнопки)
        "btn_today": "📊 Сегодня",
        "btn_week": "📅 Неделя",
        "btn_pickdate": "🗓 Добавить за другой день",
        "btn_set_goal": "🎯 Изменить цель",
        "btn_mode": "🏃 Режим цели",
        "btn_profile": "👤 Профиль",
        "btn_premium": "⭐ Premium",
        "btn_invite": "👥 Пригласить друга",
        "btn_settings": "⚙️ Настройки",
        "btn_feedback": "🛟 Обратная связь",
        "btn_back": "⬅️ Назад",
        "btn_back_menu": "⬅️ В меню",
        "btn_lang": "🌐 Язык",
        # онбординг
        "choose_goal": "Для начала выбери свою *цель*:",
        "mode_lose": "🔻 Похудение",
        "mode_maintain": "⚖️ Поддержание",
        "mode_gain": "🔺 Набор массы",
        "setup_q": "Как зададим дневную цель по калориям?",
        "setup_profile": "📊 Настроить профиль (точнее)",
        "setup_trust": "🤝 Довериться нам",
        "setup_manual": "✍️ Ввести цель вручную",
        "ask_calories": "🎯 Пришли число дневной цели (ккал, напр. 2000):",
        "ask_sex": "Укажи пол:",
        "sex_male": "Мужской",
        "sex_female": "Женский",
        "ask_age": "Сколько тебе лет? (напр. 30)",
        "ask_height": "Рост в см? (напр. 175)",
        "ask_weight": "Вес в кг? (напр. 70)",
        "ask_activity": "Уровень активности?",
        "act_sed": "Сидячий образ", "act_light": "Лёгкая (1–3 р/нед)",
        "act_mod": "Средняя (3–5 р/нед)", "act_active": "Высокая (6–7 р/нед)",
        "act_vhigh": "Очень высокая (2 трен./день)",
        "ask_sport": "Каким спортом занимаешься? Напиши вид (напр. «бег», «силовые», "
                     "«футбол 4 раза/нед») — подберу нормы Б/Ж/У точнее. Если нет — напиши «нет».",
        "sport_note": "🏃 Под твой спорт: {note}",
        "btn_mealplan": "🍽 План питания",
        "mp_locked": ("🍽 *Планы питания* — функция Premium.\n\nИИ составит недельный план под "
                      "твою цель и КБЖУ, с рецептами и списком покупок, а приёмы можно "
                      "добавлять в дневник в один тап. Оформи Premium, чтобы открыть."),
        "mp_choose_pattern": "Выбери стиль питания для плана:",
        "mp_pat_balanced": "🥗 Сбалансированный",
        "mp_pat_mediterranean": "🫒 Средиземноморский",
        "mp_pat_high_protein": "🍗 Высокобелковый",
        "mp_pat_low_carb": "🥑 Низкоуглеводный",
        "mp_pat_vegetarian": "🌱 Вегетарианский",
        "mp_ask_restrict": ("Есть ограничения или предпочтения? Напиши одной строкой "
                            "(аллергии, нелюбимые продукты, без свинины и т.п.) — или нажми «Пропустить»."),
        "mp_skip": "Пропустить →",
        "mp_generating": "👨‍🍳 Составляю недельный план под твою цель… это займёт до минуты.",
        "mp_fail": "Не получилось составить план. Попробуй ещё раз чуть позже.",
        "mp_day_header": "🍽 *{day}* — план на день\nИтого ≈ {kcal} ккал · Б {p} · Ж {f} · У {c} г",
        "mp_meal_line": "*{title}* — {grams} г · {kcal} ккал (Б {p}/Ж {f}/У {c})\n_{recipe}_",
        "mp_eat_btn": "✅ {title}",
        "mp_shop_btn": "🛒 Список покупок",
        "mp_regen_btn": "🔄 Перегенерировать",
        "mp_eaten": "✅ Записал: {title} — {kcal} ккал.",
        "mp_shopping_title": "🛒 *Список покупок на неделю:*",
        "mp_disclaimer": "_План — рекомендация, а не диета по медпоказаниям. При заболеваниях обратись к специалисту._",
        "btn_diet": "🥗 Моя диета",
        "diet_locked": ("🥗 *Подбор диеты* — функция Premium.\n\nОтветь на пару вопросов — ИИ "
                        "подберёт научно обоснованный стиль питания под твою цель и даст советы "
                        "по его поддержанию. Оформи Premium, чтобы открыть."),
        "diet_q_focus": "Что для тебя сейчас важнее всего?",
        "dq_focus_lose": "⚖️ Снизить вес",
        "dq_focus_heart": "❤️ Здоровье сердца и сосудов",
        "dq_focus_muscle": "💪 Набрать/сохранить мышцы",
        "dq_focus_balanced": "🥗 Просто питаться сбалансированно",
        "diet_ask_restrict": ("Есть ограничения или предпочтения? Напиши одной строкой "
                              "(аллергии, вегетарианство, без свинины и т.п.) — или нажми «Пропустить»."),
        "diet_generating": "🔬 Подбираю диету под тебя…",
        "diet_fail": "Не получилось подобрать диету. Попробуй ещё раз чуть позже.",
        "diet_to_plan": "🍽 Составить план по этой диете",
        "diet_redo": "🔄 Подобрать заново",
        "diet_disclaimer": "_Это не медицинская рекомендация. При заболеваниях обратись к специалисту._",
        "goal_set": "🎯 Цель установлена: *{goal}* ккал/день.",
        "goal_calc": "📊 Рассчитал под твою цель: *{cal} ккал/день* · Б {p} · Ж {f} · У {c} г.\nПодходит или изменить?",
        "goal_ok": "✅ Подходит",
        "goal_edit": "✏️ Изменить цель",
        "rem_q": "🔔 Включить напоминания? Если засидишься, бот мягко напомнит записать приём пищи.",
        "rem_on_btn": "🔔 Включить напоминания",
        "rem_off_btn": "🔕 Без напоминаний",
        "rem_done_on": "🔔 Напоминания включены. Готово! 🍽 Пришли фото еды или опиши блюдо. Меню — /menu.",
        "rem_done_off": "🔕 Без напоминаний (включить можно в Настройках). 🍽 Пришли фото еды или опиши блюдо. Меню — /menu.",
        # запись приёма
        "logged": "✅ Записал: *{item}* — {cal} ккал.",
        "logged_back": "✅ Записал за *{date}*: *{item}* — {cal} ккал.",
        "today_progress": "Сегодня: *{total}* / {goal} ккал",
        "left": "Осталось *{n}* ккал.",
        "over": "⚠️ Превышение на *{n}* ккал.",
        "no_goal": "Сегодня всего: *{total}* ккал. Цель не задана — /menu.",
        "btn_fix": "✏️ Исправить",
        "btn_del": "🗑 Удалить",
        # инвайт
        "invite_title": "👥 *Приглашай друзей*",
        "invite_body": "Друг получает *{days} дней Premium* при первом запуске по твоей ссылке, а ты — *{days} дней Premium* {cond}.\n\nТвоя ссылка:\n{link}\n\nУже приглашено: *{cnt}*",
        "invite_cond_each": "за каждого друга",
        "invite_cond_n": "за каждых {n} друзей",
        "invite_off": "Реферальная программа сейчас недоступна.",
        # ресет
        "reset_confirm": "⚠️ *Начать заново?*\nСотрём всю историю приёмов пищи и сбросим цель и профиль. Подписка сохранится. Действие необратимо.",
        "reset_yes": "✅ Да, стереть всё",
        "reset_done": "🗑 История очищена. Начнём заново!",
        # отчёты
        "daily_title": "📊 *Дневной отчёт за {date}*",
        "weekly_title": "📅 *Недельный отчёт*",
        "no_records": "_Записей за день нет._",
        # язык
        "lang_q": "🌐 Выбери язык / Choose language:",
        "lang_set": "Язык переключён на русский.",
        # приветствие
        "welcome": (
            "👋 Привет! Я *Жиромер* — помогу считать калории.\n\n"
            "Что я умею:\n"
            "• 📷 Пришли *фото еды* — оценю калорийность.\n"
            "• 📷 + подпись — оценю точнее (например: «куриная грудка 200 г»).\n"
            "• ✍️ Просто текст блюда — оценю по описанию.\n"
            "• 🔢 Просто число (напр. `350`) — добавлю вручную.\n\n"
            "Ошибся? Под каждой записью кнопки *✏️ Исправить* и *🗑 Удалить*.\n"
            "🥗 *КБЖУ* считаю по научным нормам (ВОЗ/DRI, для спорта — ACSM/ISSN) "
            "под твою цель и активность. *Занимаешься спортом?* Укажи свой вид спорта "
            "в профиле — подберу нормы белков/жиров/углеводов точнее.\n"
            "⚙️ Цель, режим и профиль — в /menu → Настройки.\n"
            "Меню — /menu."),
        "plans_title": "Тарифы:",
        "plans_tail": "Premium — {price}★/мес. Подробнее: /premium",
        "plans_tail_macros": "Premium — {price}★/мес, Premium+КБЖУ — {mprice}★/мес. /premium",
        # настройки
        "settings_title": "⚙️ Настройки:",
        "set_goal_prompt": "🎯 Пришли новое число цели (ккал/день):",
        "s_goal": "🎯 Цель: {v} ккал",
        "s_daily_time": "🕘 Время дн. отчёта: {v}",
        "s_weekly_day": "📆 День нед. отчёта: {v}",
        "s_tz": "🌍 Часовой пояс: {v}",
        "s_daily": "Дневной отчёт: {v}",
        "s_weekly": "Недельный: {v}",
        "s_reminders": "⏰ Напоминания: {v}",
        "s_every": "каждые {n}ч",
        "s_mode": "🏃 Режим: {v}",
        "s_profile": "👤 Профиль",
        "s_reset": "🗑 Начать заново",
        "on": "🔔 вкл", "off": "🔕 выкл",
        "hour_q": "🕘 Час дневного отчёта:",
        "dow_q": "📆 День недельного отчёта:",
        "tz_q": "🌍 Текущий пояс: *{v}*.\nВыбери смещение от UTC — по нему считается «день» и отчёты:",
        "rem_int_q": "⏰ Как часто напоминать?",
        "mode_q": "🏃 Выбери режим цели:",
        # режимы (для подписи в настройках)
        "m_lose": "Похудение", "m_maintain": "Поддержание", "m_gain": "Набор массы",
        # оплата
        "pay_limit": "🚫 Дневной лимит бесплатных анализов исчерпан ({n}/день).",
        "pay_period": "🚫 Бесплатный период ({n} дн.) закончился.",
        "pay_offer": "\n\nОформи *Premium* за {price}★/мес — безлимитные анализы. Или пакет анализов / промокод.",
        "buy_premium": "⭐ Premium — {price}★/мес",
        "buy_macros": "🥗 Premium+КБЖУ — {price}★/мес",
        "buy_pack": "📦 {credits} анализов — {stars}★",
        "enter_promo": "🎟 Ввести промокод",
        "opening_pay": "Открываю оплату звёздами…",
        "pay_open_fail": "Не получилось открыть оплату. Попробуй ещё раз чуть позже или напиши в поддержку.",
        "premium_active": "⭐ Premium активен до *{date}* (автопродление).\nОтменить — /cancelsub.",
        "premium_offer": "{remaining}\n\n*Premium* — {price}★/мес (автопродление), безлимитные анализы. Или разовый пакет.",
        "free_all": "Сейчас все функции бесплатны и без лимитов.",
        "rem_text_premium": "Premium активен — безлимит.",
        "rem_text_period": "Бесплатный период ({n} дн.) закончился — оформи Premium.{credits}",
        "rem_text_left": "Сегодня осталось бесплатных анализов: {left}/{total}. Бесплатно — первые {days} дней.{credits}",
        "credits_suffix": " Доступно кредитов: {n}.",
        "pay_off_msg": "Сейчас все функции бесплатны 🎉 Оплата отключена.",
        "sub_msg": "⭐ *Premium* — {price}★/мес, автопродление.\nОтменить — /cancelsub.",
        "sub_macros_msg": "🥗 *Premium+КБЖУ* — {price}★/мес, автопродление.\nОтменить — /cancelsub.",
        "sub_btn": "Оформить за {price}★/мес",
        "pay_thanks": "✅ Спасибо! *{name}* активен до *{date}* (автопродление). Анализы без лимита 🎉{extra}",
        "pay_thanks_macros_extra": " Теперь в анализах и отчётах есть Б/Ж/У 🥗",
        "pay_renewed": "🔄 Подписка продлена. *{name}* активен до *{date}*.",
        "pack_added": "✅ Спасибо! Начислено *{n}* анализов. Тратятся после дневного лимита.",
        "cancel_none": "Активной автоподписки нет.",
        "cancel_ok": "✅ Автопродление отменено. Premium действует до конца оплаченного периода.",
        "cancel_fail": ("Отменить автопродление можно прямо в Telegram за пару тапов:\n"
                        "• открой сообщение-чек об оплате ⭐ и нажми «Отменить подписку»,\n"
                        "• или Настройки → Telegram Star → Мои подписки.\n\n"
                        "Premium останется активным до конца уже оплаченного периода."),
        "promo_premium_days": "🎉 Промокод активирован: +{n} дней Premium!",
        "promo_premium_plus_days": "🎉 Промокод активирован: +{n} дней Premium+КБЖУ!",
        "promo_credits": "🎉 Промокод активирован: +{n} анализов!",
        "alpha_gift": ("🎉 *Спасибо за участие в альфа-тесте Жиромера!*\n\n"
                       "Мы включили платные тарифы. За помощь в разработке дарим тебе "
                       "*3 месяца Premium+КБЖУ* — безлимитные анализы и расчёт белков, "
                       "жиров и углеводов.\n\nУже активно, ничего делать не нужно. "
                       "Спасибо, что был с нами с самого начала ❤️"),
        "promo_err_not_found": "Код не найден или неактивен.",
        "promo_err_expired": "Срок действия кода истёк.",
        "promo_err_limit": "Лимит активаций кода исчерпан.",
        "promo_err_already": "Ты уже активировал этот код.",
        "byok_off": "Свой ключ сейчас не поддерживается.",
        "byok_usage": "Использование: /setkey sk-...",
        "byok_checking": "Проверяю ключ…",
        "byok_bad": "❌ Ключ не прошёл проверку. Убедись, что он рабочий.",
        "byok_saved": "✅ Ключ сохранён (шифрованно). Анализы теперь безлимитны и за твой счёт OpenAI.\nУдалить ключ — /delkey.",
        "byok_deleted": "Ключ удалён. Бот снова работает на общих условиях.",
        "terms_text": (
            "📄 *Условия использования*\n\n"
            "Бот оценивает калорийность по фото/описанию с помощью ИИ — это приблизительная "
            "оценка, не медицинская рекомендация. Premium даёт безлимитные ИИ-анализы на "
            "{days} дней. Оплата — Telegram Stars. Возврат возможен через поддержку. "
            "Оформляя покупку, вы соглашаетесь с этими условиями.\n\nПоддержка: {support} или /paysupport."),
        "paysupport_text": (
            "🛟 *Поддержка по платежам*\n\n"
            "Вопрос по оплате или нужен возврат — напишите {support}, укажите дату и сумму "
            "платежа. Ответим как можно скорее.\n\n"
            "_Поддержка Telegram не помогает с покупками внутри бота._"),
        # запись/правка
        "fixed": "✏️ Обновил: *{item}* — {cal} ккал.",
        "back_today": "↩️ Вернуться к сегодня",
        # отчёты (недельный)
        "week_total": "Сумма за неделю: *{v}* ккал",
        "week_avg": "Среднее в день (по дням с записями): *{v}* ккал",
        "week_within": "Дней в пределах цели: {a}/{b}",
        # обратная связь
        "fb_title": "🛟 *Обратная связь*\n\nВыбери, о чём сообщить:",
        "fb_bug": "🐞 Сообщить о баге",
        "fb_cal": "🍽 Неверные калории",
        "fb_bug_desc": "🐞 Опиши проблему текстом: что произошло и что ожидалось.\n_Ссылки и файлы нельзя._",
        "fb_bug_media": "📎 Прикрепи скриншот или видео — или напиши «пропустить».",
        "fb_cal_desc": "🍽 Опиши блюдо и что не так с калориями.\n_Без ссылок и файлов._",
        "fb_cal_value": "Сколько калорий должно быть? Пришли число или «не знаю».",
        "fb_cal_media": "📎 Можешь приложить фото блюда — или напиши «пропустить».",
        "fb_no_links": "🚫 Ссылки нельзя. Опиши словами.",
        "fb_short": "Слишком коротко — опиши подробнее.",
        "fb_need_photo": "Пришли фото/видео либо напиши «пропустить». Файлы и ссылки не принимаются.",
        "fb_no_files": "🚫 Файлы нельзя. Пришли фото/видео или «пропустить».",
        "fb_bug_done": "✅ Спасибо! Баг-репорт #{id} принят.",
        "fb_cal_done": "✅ Спасибо! Замечание #{id} принято — поможет улучшить распознавание.",
        # колбэки/прочее
        "entry_deleted": "🗑 Запись удалена.",
        "entry_gone": "🗑 Запись уже была удалена.",
        "entry_missing": "Эта запись уже удалена.",
        "fix_prompt": "✏️ Правлю «{item}» ({cal} ккал).\nПришли *правильное число калорий* или *уточни блюдо текстом* — пересчитаю без списания лимита.",
        "fix_not_found": "Не нашёл запись для правки — возможно, она удалена.",
        "fix_recalc_fail": "Не получилось пересчитать 😕 Пришли правильное число калорий.",
        "promo_prompt": "🎟 Пришли промокод одним сообщением:",
        "pack_unavailable": "Пакет недоступен.",
        "pickdate_q": "🗓 За какой день добавить? Выбери дату — следующие фото/текст пойдут в неё:",
        "back_to_today_msg": "↩️ Снова работаем с сегодняшней датой.",
        "great": "Отлично! 👍",
        "trust_set": "🤝 Стандартная цель под твой режим: *{goal} ккал/день* (Б {p} · Ж {f} · У {c} г).\nПодходит или изменить?",
        "enter_goal_num": "Введи число, например 2000.",
        "goal_range": "Цель должна быть в диапазоне 500–10000 ккал.",
        "enter_num": "Введи число.",
        "age_range": "Возраст должен быть 10–100.",
        "height_range": "Рост должен быть 120–230 см.",
        "weight_range": "Вес должен быть 30–300 кг.",
        "photo_fail": "Не удалось распознать фото 😕 Попробуй ещё раз или пришли описание текстом.",
        "text_fail": "Не получилось оценить 😕 Попробуй иначе или пришли фото.",
        "byok_fallback": "⚠️ Твой ключ OpenAI не сработал — считаю на общем. Проверь ключ или /delkey.",
        "premium_until_short": "⭐ Premium активен до *{date}*.",
        "video_no": "Видео я пока не распознаю. Пришли фото блюда 📷",
        "note_prefix": "🔎 {note}",
        "advice_prefix": "💡 {advice}",
        "trial_note": "🎁 Первые {n} дня — безлимитный доступ!",
        "ref_friend_bonus": "🎁 Ты пришёл по приглашению — тебе *{days} дней Premium* в подарок!",
        "ref_got_bonus": "🎉 По твоей ссылке пришёл друг — тебе *{days} дней Premium*! Спасибо 🙌",
        "ref_progress": "👥 По твоей ссылке пришёл друг! Ещё {n} — и бонус Premium.",
        "ver_changes": "Последние изменения:",
        "manual_item": "ручной ввод",
        "photo_item_default": "блюдо с фото",
        "day_back_note": "\n\n🗓 Это прошлый день. Фото/текст, отправленные сейчас, добавятся в эту дату.",
        # меню-кнопки новых фич
        "btn_favorites": "⭐ Избранное",
        "btn_barcode": "📷 Штрих-код",
        "btn_fav_add": "⭐",
        # избранное
        "fav_added": "⭐ Добавлено в избранное.",
        "fav_empty": "В избранном пока пусто. Под любой записью нажми ⭐, чтобы сохранить.",
        "fav_title": "⭐ *Избранное* — нажми, чтобы добавить сегодня:",
        # голос
        "voice_busy": "Заверши текущий шаг текстом 🙂",
        "voice_fail": "Не удалось распознать голос 😕 Попробуй ещё раз или напиши текстом.",
        "voice_empty": "Ничего не расслышал 😕 Попробуй ещё раз.",
        "voice_heard": "🎤 Распознал: _{text}_",
        # штрих-код
        "bc_ask_photo": "📷 Пришли фото штрих-кода продукта (или пришли цифры под ним).",
        "bc_not_found": "Не вижу штрих-код на фото 😕 Сфотографируй ближе или пришли цифры текстом.",
        "bc_off_none": "Не нашёл продукт в базе Open Food Facts. Опиши его текстом или пришли фото еды.",
        "bc_ask_grams": "Нашёл: *{name}* — {kcal} ккал/100 г.\nСколько граммов ты съел? (напр. 150)",
    },
    "en": {
        "menu": "Main menu:",
        "done": "Done!",
        "lang_name": "English",
        "btn_today": "📊 Today",
        "btn_week": "📅 Week",
        "btn_pickdate": "🗓 Add for another day",
        "btn_set_goal": "🎯 Change goal",
        "btn_mode": "🏃 Goal mode",
        "btn_profile": "👤 Profile",
        "btn_premium": "⭐ Premium",
        "btn_invite": "👥 Invite a friend",
        "btn_settings": "⚙️ Settings",
        "btn_feedback": "🛟 Feedback",
        "btn_back": "⬅️ Back",
        "btn_back_menu": "⬅️ To menu",
        "btn_lang": "🌐 Language",
        "choose_goal": "First, choose your *goal*:",
        "mode_lose": "🔻 Lose weight",
        "mode_maintain": "⚖️ Maintain",
        "mode_gain": "🔺 Gain muscle",
        "setup_q": "How should we set your daily calorie goal?",
        "setup_profile": "📊 Set up profile (more accurate)",
        "setup_trust": "🤝 Let us decide",
        "setup_manual": "✍️ Enter goal manually",
        "ask_calories": "🎯 Send your daily goal (kcal, e.g. 2000):",
        "ask_sex": "Your sex:",
        "sex_male": "Male",
        "sex_female": "Female",
        "ask_age": "How old are you? (e.g. 30)",
        "ask_height": "Height in cm? (e.g. 175)",
        "ask_weight": "Weight in kg? (e.g. 70)",
        "ask_activity": "Activity level?",
        "act_sed": "Sedentary", "act_light": "Light (1–3/wk)",
        "act_mod": "Moderate (3–5/wk)", "act_active": "High (6–7/wk)",
        "act_vhigh": "Very high (2 sessions/day)",
        "ask_sport": "What sport do you do? Type it (e.g. \"running\", \"strength\", "
                     "\"soccer 4x/wk\") — I'll tune your protein/fat/carb targets. If none, type \"no\".",
        "sport_note": "🏃 For your sport: {note}",
        "btn_mealplan": "🍽 Meal plan",
        "mp_locked": ("🍽 *Meal plans* is a Premium feature.\n\nThe AI builds a weekly plan for "
                      "your goal and macros, with recipes and a shopping list, and you can log "
                      "meals to your diary in one tap. Go Premium to unlock."),
        "mp_choose_pattern": "Choose an eating style for your plan:",
        "mp_pat_balanced": "🥗 Balanced",
        "mp_pat_mediterranean": "🫒 Mediterranean",
        "mp_pat_high_protein": "🍗 High-protein",
        "mp_pat_low_carb": "🥑 Low-carb",
        "mp_pat_vegetarian": "🌱 Vegetarian",
        "mp_ask_restrict": ("Any restrictions or preferences? Write them in one line "
                            "(allergies, disliked foods, no pork, etc.) — or tap “Skip”."),
        "mp_skip": "Skip →",
        "mp_generating": "👨‍🍳 Building your weekly plan… this can take up to a minute.",
        "mp_fail": "Couldn't build the plan. Please try again a bit later.",
        "mp_day_header": "🍽 *{day}* — daily plan\nTotal ≈ {kcal} kcal · P {p} · F {f} · C {c} g",
        "mp_meal_line": "*{title}* — {grams} g · {kcal} kcal (P {p}/F {f}/C {c})\n_{recipe}_",
        "mp_eat_btn": "✅ {title}",
        "mp_shop_btn": "🛒 Shopping list",
        "mp_regen_btn": "🔄 Regenerate",
        "mp_eaten": "✅ Logged: {title} — {kcal} kcal.",
        "mp_shopping_title": "🛒 *Shopping list for the week:*",
        "mp_disclaimer": "_This plan is guidance, not a medical diet. If you have health conditions, consult a professional._",
        "btn_diet": "🥗 My diet",
        "diet_locked": ("🥗 *Diet matching* is a Premium feature.\n\nAnswer a couple of questions — "
                        "the AI picks a science-based eating style for your goal and gives tips to "
                        "maintain it. Go Premium to unlock."),
        "diet_q_focus": "What matters most to you right now?",
        "dq_focus_lose": "⚖️ Lose weight",
        "dq_focus_heart": "❤️ Heart & vascular health",
        "dq_focus_muscle": "💪 Build/keep muscle",
        "dq_focus_balanced": "🥗 Just eat balanced",
        "diet_ask_restrict": ("Any restrictions or preferences? Write them in one line "
                              "(allergies, vegetarian, no pork, etc.) — or tap “Skip”."),
        "diet_generating": "🔬 Matching a diet for you…",
        "diet_fail": "Couldn't match a diet. Please try again a bit later.",
        "diet_to_plan": "🍽 Build a meal plan for this diet",
        "diet_redo": "🔄 Match again",
        "diet_disclaimer": "_This is not medical advice. If you have health conditions, consult a professional._",
        "goal_set": "🎯 Goal set: *{goal}* kcal/day.",
        "goal_calc": "📊 Based on your goal: *{cal} kcal/day* · P {p} · F {f} · C {c} g.\nLooks good or change it?",
        "goal_ok": "✅ Looks good",
        "goal_edit": "✏️ Change goal",
        "rem_q": "🔔 Enable reminders? The bot will gently remind you to log meals.",
        "rem_on_btn": "🔔 Enable reminders",
        "rem_off_btn": "🔕 No reminders",
        "rem_done_on": "🔔 Reminders on. Done! 🍽 Send a food photo or describe a dish. Menu — /menu.",
        "rem_done_off": "🔕 No reminders (enable in Settings). 🍽 Send a food photo or describe a dish. Menu — /menu.",
        "logged": "✅ Logged: *{item}* — {cal} kcal.",
        "logged_back": "✅ Logged for *{date}*: *{item}* — {cal} kcal.",
        "today_progress": "Today: *{total}* / {goal} kcal",
        "left": "*{n}* kcal left.",
        "over": "⚠️ Over by *{n}* kcal.",
        "no_goal": "Today total: *{total}* kcal. No goal set — /menu.",
        "btn_fix": "✏️ Fix",
        "btn_del": "🗑 Delete",
        "invite_title": "👥 *Invite friends*",
        "invite_body": "Your friend gets *{days} days of Premium* on first launch via your link, and you get *{days} days of Premium* {cond}.\n\nYour link:\n{link}\n\nInvited so far: *{cnt}*",
        "invite_cond_each": "for each friend",
        "invite_cond_n": "for every {n} friends",
        "invite_off": "The referral program is currently unavailable.",
        "reset_confirm": "⚠️ *Start over?*\nThis erases all meal history and resets your goal and profile. Subscription is kept. This cannot be undone.",
        "reset_yes": "✅ Yes, erase everything",
        "reset_done": "🗑 History cleared. Let's start over!",
        "daily_title": "📊 *Daily report for {date}*",
        "weekly_title": "📅 *Weekly report*",
        "no_records": "_No entries for the day._",
        "lang_q": "🌐 Choose language / Выбери язык:",
        "lang_set": "Language switched to English.",
        "welcome": (
            "👋 Hi! I'm *Zhiromer* — I help you count calories.\n\n"
            "What I can do:\n"
            "• 📷 Send a *food photo* — I'll estimate calories.\n"
            "• 📷 + caption — more accurate (e.g. 'chicken breast 200 g').\n"
            "• ✍️ Just describe the dish in text.\n"
            "• 🔢 Just a number (e.g. `350`) — I'll add it manually.\n\n"
            "Mistake? Each entry has *✏️ Fix* and *🗑 Delete* buttons.\n"
            "🥗 *Protein/fat/carbs* are calculated from science-based references "
            "(WHO/DRI, and ACSM/ISSN for sport) to match your goal and activity. "
            "*Do you play a sport?* Add it in your profile — I'll tune your macro targets.\n"
            "⚙️ Goal, mode and profile — in /menu → Settings.\n"
            "Menu — /menu."),
        "plans_title": "Plans:",
        "plans_tail": "Premium — {price}★/mo. Details: /premium",
        "plans_tail_macros": "Premium — {price}★/mo, Premium+Macros — {mprice}★/mo. /premium",
        "settings_title": "⚙️ Settings:",
        "set_goal_prompt": "🎯 Send a new daily goal (kcal):",
        "s_goal": "🎯 Goal: {v} kcal",
        "s_daily_time": "🕘 Daily report time: {v}",
        "s_weekly_day": "📆 Weekly report day: {v}",
        "s_tz": "🌍 Time zone: {v}",
        "s_daily": "Daily report: {v}",
        "s_weekly": "Weekly: {v}",
        "s_reminders": "⏰ Reminders: {v}",
        "s_every": "every {n}h",
        "s_mode": "🏃 Mode: {v}",
        "s_profile": "👤 Profile",
        "s_reset": "🗑 Start over",
        "on": "🔔 on", "off": "🔕 off",
        "hour_q": "🕘 Daily report hour:",
        "dow_q": "📆 Weekly report day:",
        "tz_q": "🌍 Current zone: *{v}*.\nPick your UTC offset — it defines your “day” and reports:",
        "rem_int_q": "⏰ How often to remind?",
        "mode_q": "🏃 Choose your goal mode:",
        "m_lose": "Lose weight", "m_maintain": "Maintain", "m_gain": "Gain muscle",
        "pay_limit": "🚫 Daily free analyses limit reached ({n}/day).",
        "pay_period": "🚫 Free period ({n} days) has ended.",
        "pay_offer": "\n\nGet *Premium* for {price}★/mo — unlimited analyses. Or a pack / promo code.",
        "buy_premium": "⭐ Premium — {price}★/mo",
        "buy_macros": "🥗 Premium+Macros — {price}★/mo",
        "buy_pack": "📦 {credits} analyses — {stars}★",
        "enter_promo": "🎟 Enter promo code",
        "opening_pay": "Opening Stars payment…",
        "pay_open_fail": "Couldn't open the payment. Please try again later or contact support.",
        "premium_active": "⭐ Premium active until *{date}* (auto-renew).\nCancel — /cancelsub.",
        "premium_offer": "{remaining}\n\n*Premium* — {price}★/mo (auto-renew), unlimited analyses. Or a one-time pack.",
        "free_all": "Everything is free with no limits right now.",
        "rem_text_premium": "Premium active — unlimited.",
        "rem_text_period": "Free period ({n} days) ended — get Premium.{credits}",
        "rem_text_left": "Free analyses left today: {left}/{total}. Free for the first {days} days.{credits}",
        "credits_suffix": " Credits available: {n}.",
        "pay_off_msg": "Everything is free right now 🎉 Payments are off.",
        "sub_msg": "⭐ *Premium* — {price}★/mo, auto-renew.\nCancel — /cancelsub.",
        "sub_macros_msg": "🥗 *Premium+Macros* — {price}★/mo, auto-renew.\nCancel — /cancelsub.",
        "sub_btn": "Subscribe for {price}★/mo",
        "pay_thanks": "✅ Thanks! *{name}* active until *{date}* (auto-renew). Unlimited analyses 🎉{extra}",
        "pay_thanks_macros_extra": " Now analyses and reports include P/F/C 🥗",
        "pay_renewed": "🔄 Subscription renewed. *{name}* active until *{date}*.",
        "pack_added": "✅ Thanks! Added *{n}* analyses. Used after the daily limit.",
        "cancel_none": "No active auto-subscription.",
        "cancel_ok": "✅ Auto-renew canceled. Premium stays until the end of the paid period.",
        "cancel_fail": ("You can cancel auto-renewal right inside Telegram in a couple of taps:\n"
                        "• open the ⭐ payment receipt message and tap “Cancel subscription”,\n"
                        "• or Settings → Telegram Star → My Subscriptions.\n\n"
                        "Premium stays active until the end of the period you already paid for."),
        "promo_premium_days": "🎉 Promo activated: +{n} days of Premium!",
        "promo_premium_plus_days": "🎉 Promo activated: +{n} days of Premium+Macros!",
        "promo_credits": "🎉 Promo activated: +{n} analyses!",
        "alpha_gift": ("🎉 *Thanks for taking part in the Жиромер alpha test!*\n\n"
                       "We've switched on paid plans. As a thank-you for helping us build "
                       "the bot, here are *3 months of Premium+Macros* — unlimited analyses "
                       "and protein/fat/carb tracking.\n\nIt's already active, nothing to do. "
                       "Thanks for being with us from the start ❤️"),
        "promo_err_not_found": "Code not found or inactive.",
        "promo_err_expired": "This code has expired.",
        "promo_err_limit": "This code's activation limit is reached.",
        "promo_err_already": "You've already used this code.",
        "byok_off": "Bring-your-own-key isn't available right now.",
        "byok_usage": "Usage: /setkey sk-...",
        "byok_checking": "Checking the key…",
        "byok_bad": "❌ The key failed validation. Make sure it works.",
        "byok_saved": "✅ Key saved (encrypted). Analyses are now unlimited and billed to your OpenAI account.\nRemove it — /delkey.",
        "byok_deleted": "Key removed. The bot works on the shared terms again.",
        "terms_text": (
            "📄 *Terms of Use*\n\n"
            "The bot estimates calories from a photo/description using AI — it's an approximate "
            "estimate, not medical advice. Premium gives unlimited AI analyses for {days} days. "
            "Payment is via Telegram Stars. Refunds are possible through support. By purchasing "
            "you agree to these terms.\n\nSupport: {support} or /paysupport."),
        "paysupport_text": (
            "🛟 *Payment support*\n\n"
            "For a payment question or refund, message {support} with the date and amount. "
            "We'll reply as soon as possible.\n\n"
            "_Telegram support cannot help with in-bot purchases._"),
        "fixed": "✏️ Updated: *{item}* — {cal} kcal.",
        "back_today": "↩️ Back to today",
        "week_total": "Week total: *{v}* kcal",
        "week_avg": "Daily average (days with entries): *{v}* kcal",
        "week_within": "Days within goal: {a}/{b}",
        "fb_title": "🛟 *Feedback*\n\nWhat would you like to report?",
        "fb_bug": "🐞 Report a bug",
        "fb_cal": "🍽 Wrong calories",
        "fb_bug_desc": "🐞 Describe the problem: what happened and what you expected.\n_No links or files._",
        "fb_bug_media": "📎 Attach a screenshot or video — or type “skip”.",
        "fb_cal_desc": "🍽 Describe the dish and what's wrong with the calories.\n_No links or files._",
        "fb_cal_value": "What should the calories be? Send a number or “don't know”.",
        "fb_cal_media": "📎 You can attach a photo of the dish — or type “skip”.",
        "fb_no_links": "🚫 Links are not allowed. Describe it in words.",
        "fb_short": "Too short — please add more detail.",
        "fb_need_photo": "Send a photo/video or type “skip”. Files and links are not accepted.",
        "fb_no_files": "🚫 Files are not allowed. Send a photo/video or “skip”.",
        "fb_bug_done": "✅ Thanks! Bug report #{id} received.",
        "fb_cal_done": "✅ Thanks! Note #{id} received — it helps improve recognition.",
        "entry_deleted": "🗑 Entry deleted.",
        "entry_gone": "🗑 Entry was already deleted.",
        "entry_missing": "This entry was already deleted.",
        "fix_prompt": "✏️ Editing «{item}» ({cal} kcal).\nSend the *correct calorie number* or *clarify the dish in text* — I'll recalc without using your limit.",
        "fix_not_found": "Couldn't find the entry — it may have been deleted.",
        "fix_recalc_fail": "Couldn't recalc 😕 Send the correct calorie number.",
        "promo_prompt": "🎟 Send your promo code in one message:",
        "pack_unavailable": "Pack unavailable.",
        "pickdate_q": "🗓 Which day to add to? Pick a date — next photos/text go there:",
        "back_to_today_msg": "↩️ Back to today's date.",
        "great": "Great! 👍",
        "trust_set": "🤝 Standard goal for your mode: *{goal} kcal/day* (P {p} · F {f} · C {c} g).\nLooks good or change it?",
        "enter_goal_num": "Enter a number, e.g. 2000.",
        "goal_range": "Goal must be between 500 and 10000 kcal.",
        "enter_num": "Enter a number.",
        "age_range": "Age must be 10–100.",
        "height_range": "Height must be 120–230 cm.",
        "weight_range": "Weight must be 30–300 kg.",
        "photo_fail": "Couldn't recognize the photo 😕 Try again or send a text description.",
        "text_fail": "Couldn't estimate 😕 Try differently or send a photo.",
        "byok_fallback": "⚠️ Your OpenAI key failed — using the shared one. Check the key or /delkey.",
        "premium_until_short": "⭐ Premium active until *{date}*.",
        "video_no": "I can't analyze video yet. Send a food photo 📷",
        "note_prefix": "🔎 {note}",
        "advice_prefix": "💡 {advice}",
        "trial_note": "🎁 First {n} days — unlimited access!",
        "ref_friend_bonus": "🎁 You joined via an invite — *{days} days of Premium* as a gift!",
        "ref_got_bonus": "🎉 A friend joined via your link — *{days} days of Premium* for you! Thanks 🙌",
        "ref_progress": "👥 A friend joined via your link! {n} more for a Premium bonus.",
        "ver_changes": "Latest changes:",
        "manual_item": "manual entry",
        "photo_item_default": "dish from photo",
        "day_back_note": "\n\n🗓 This is a past day. Photos/text you send now go to this date.",
        "btn_favorites": "⭐ Favorites",
        "btn_barcode": "📷 Barcode",
        "btn_fav_add": "⭐",
        "fav_added": "⭐ Added to favorites.",
        "fav_empty": "No favorites yet. Tap ⭐ under any entry to save it.",
        "fav_title": "⭐ *Favorites* — tap to add to today:",
        "voice_busy": "Please finish the current step with text 🙂",
        "voice_fail": "Couldn't recognize the voice 😕 Try again or type it.",
        "voice_empty": "Didn't catch anything 😕 Try again.",
        "voice_heard": "🎤 Heard: _{text}_",
        "bc_ask_photo": "📷 Send a photo of the product barcode (or send the digits under it).",
        "bc_not_found": "I don't see a barcode 😕 Take a closer photo or send the digits as text.",
        "bc_off_none": "Product not found in Open Food Facts. Describe it in text or send a food photo.",
        "bc_ask_grams": "Found: *{name}* — {kcal} kcal/100 g.\nHow many grams did you eat? (e.g. 150)",
    },
}


def lang_menu_keyboard():
    """Возвращает данные для клавиатуры выбора языка (строится в keyboards.py)."""
    return [(t("lang_name", l), f"setlang:{l}") for l in LANGS]
