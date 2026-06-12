"""Точка входа. На Render запускается в режиме webhook, локально — polling."""
import logging

from telegram import Update
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, PreCheckoutQueryHandler, filters)

import config
import db
import handlers
import payments
import reports

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("calbot")


async def _post_init(application: Application) -> None:
    await db.init()
    await reports.schedule_all(application)
    log.info("БД инициализирована, задачи отчётов запланированы.")


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
    app.add_handler(CommandHandler("premium", payments.premium_cmd))
    app.add_handler(CommandHandler("promo", payments.promo_cmd))
    app.add_handler(CommandHandler("addpromo", payments.addpromo_cmd))
    app.add_handler(CommandHandler("terms", payments.terms_cmd))
    app.add_handler(CommandHandler("paysupport", payments.paysupport_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handlers.on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))
    # Платежи Telegram Stars
    app.add_handler(PreCheckoutQueryHandler(payments.on_pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payments.on_successful_payment))
    app.add_handler(CallbackQueryHandler(handlers.on_callback))
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
