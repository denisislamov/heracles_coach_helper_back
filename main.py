"""Точка входа. На Render запускается в режиме webhook, локально — polling."""
import asyncio
import logging
import traceback

from telegram import BotCommand, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, PreCheckoutQueryHandler, filters)

import config
import db
import fasting
import handlers
import payments
import reminders
import reports
import version

PUBLIC_COMMANDS = [
    BotCommand("start", "Запуск и настройка"),
    BotCommand("menu", "Меню и настройки"),
    BotCommand("premium", "Premium-подписка"),
    BotCommand("promo", "Активировать промокод"),
    BotCommand("invite", "Пригласить друга (бонус обоим)"),
    BotCommand("feedback", "Сообщить о проблеме"),
    BotCommand("reset", "Начать заново (стереть историю)"),
    BotCommand("help", "Как пользоваться"),
    BotCommand("terms", "Условия"),
    BotCommand("paysupport", "Поддержка по оплате"),
]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("calbot")


async def _post_init(application: Application) -> None:
    await db.init()
    await payments.refresh_settings()
    await application.bot.set_my_commands(PUBLIC_COMMANDS)
    await reports.schedule_all(application)
    await reminders.schedule_all(application)
    await fasting.reschedule_all(application)
    await _maybe_announce_changelog(application)
    # подхватывать смену настроек (монетизация/лимиты) из админки раз в минуту
    application.job_queue.run_repeating(payments.refresh_settings_job, interval=60, first=60)
    log.info("БД инициализирована, отчёты запланированы. Монетизация: %s, free=%s/день %s дней",
             payments.monetization_enabled(), payments.free_daily_ai(), payments.free_period_days())


async def _broadcast_changelog(context) -> None:
    """Разослать заметки об обновлении всем пользователям (бережно к лимитам)."""
    notes = context.job.data
    text = (f"🆕 *Жиромер обновился до v{version.VERSION}*\n\nЧто нового:\n"
            + "\n".join(f"• {n}" for n in notes))
    sent = 0
    for user in await db.active_users():
        try:
            await context.bot.send_message(user["user_id"], text, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)  # ~20 сообщений/сек — в пределах лимитов
        except Forbidden:
            await db.set_blocked(user["user_id"], True)  # заблокировал бота — помечаем
        except Exception:
            pass  # прочие сбои — пропускаем
    log.info("Changelog v%s разослан %s пользователям", version.VERSION, sent)


async def _maybe_announce_changelog(application: Application) -> None:
    last = await db.get_setting("announced_version")
    if last == version.VERSION:
        return
    notes = version.latest_notes()
    # Первый запуск с этой системой (нет записи) — не спамим, просто фиксируем версию.
    if last is not None and notes:
        application.job_queue.run_once(_broadcast_changelog, when=10, data=notes)
    await db.set_setting("announced_version", version.VERSION)


async def _on_error(update: object, context) -> None:
    """Глобальный перехват ошибок: лог + уведомление админу + мягкий ответ юзеру."""
    err = context.error
    # Безобидные случаи: повторный тап по кнопке (контент тот же) — игнорируем тихо.
    if isinstance(err, BadRequest) and "not modified" in str(err).lower():
        return
    if isinstance(err, Forbidden):
        return  # пользователь заблокировал бота — уже помечается в местах рассылки
    log.exception("Необработанная ошибка", exc_info=context.error)
    tb = "".join(traceback.format_exception(
        type(context.error), context.error, getattr(context.error, "__traceback__", None)))
    info = ""
    try:
        if isinstance(update, Update):
            if update.effective_user:
                info += f"user={update.effective_user.id} "
            if update.callback_query:
                info += f"callback={update.callback_query.data!r} "
            elif update.effective_message and (update.effective_message.text or "").strip():
                info += f"text={update.effective_message.text[:60]!r} "
    except Exception:
        pass
    admin_text = f"⚠️ Ошибка бота\n{info}\n\n{tb[-3200:]}"
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, admin_text[:4096])
        except Exception:
            pass
    # мягкое сообщение пользователю, чтобы не было «ничего не происходит»
    try:
        if isinstance(update, Update) and update.effective_message:
            lang = "ru"
            if update.effective_user:
                u = await db.get_user(update.effective_user.id)
                lang = u["lang"] if u else "ru"
            await update.effective_message.reply_text(handlers.t("generic_error", lang))
    except Exception:
        pass


async def _post_shutdown(application: Application) -> None:
    await db.close()


def build_app() -> Application:
    if config.TELEGRAM_TEST_ENV:
        log.info("РЕЖИМ ТЕСТОВОЙ СРЕДЫ Telegram включён (звёзды бесплатные).")
    app = (
        Application.builder()
        .token(config.EFFECTIVE_TOKEN)   # +"/test" в тестовой среде
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler(["menu", "settings"], handlers.menu))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    app.add_handler(CommandHandler("version", handlers.version_cmd))
    app.add_handler(CommandHandler("myid", handlers.myid_cmd))
    app.add_handler(CommandHandler("invite", handlers.invite_cmd))
    app.add_handler(CommandHandler("reset", handlers.reset_cmd))
    app.add_handler(CommandHandler("feedback", handlers.feedback_cmd))
    app.add_handler(CommandHandler("premium", payments.premium_cmd))
    app.add_handler(CommandHandler("cancelsub", payments.cancelsub_cmd))
    app.add_handler(CommandHandler("promo", payments.promo_cmd))
    app.add_handler(CommandHandler("addpromo", payments.addpromo_cmd))
    app.add_handler(CommandHandler("refund", payments.refund_cmd))
    app.add_handler(CommandHandler("stats", payments.stats_cmd))
    app.add_handler(CommandHandler("alpha_grant", payments.alpha_grant_cmd))
    app.add_handler(CommandHandler("setkey", payments.setkey_cmd))
    app.add_handler(CommandHandler("delkey", payments.delkey_cmd))
    app.add_handler(CommandHandler("terms", payments.terms_cmd))
    app.add_handler(CommandHandler("paysupport", payments.paysupport_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handlers.on_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handlers.on_voice))
    app.add_handler(MessageHandler(filters.VIDEO, handlers.on_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handlers.on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))
    # Платежи Telegram Stars
    app.add_handler(PreCheckoutQueryHandler(payments.on_pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payments.on_successful_payment))
    app.add_handler(CallbackQueryHandler(handlers.on_callback))
    app.add_error_handler(_on_error)
    return app


def main() -> None:
    app = build_app()

    if config.RUN_MODE == "webhook":
        if not config.WEBHOOK_URL:
            raise RuntimeError(
                "Для webhook нужен WEBHOOK_URL (или RENDER_EXTERNAL_URL). "
                "Локально используйте RUN_MODE=polling."
            )
        url = config.WEBHOOK_URL.rstrip("/")
        log.info("Запуск в режиме webhook на :%s", config.PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path=config.WEBHOOK_SECRET,
            webhook_url=f"{url}/{config.WEBHOOK_SECRET}",
            secret_token=None,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        log.info("Запуск в режиме polling")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
