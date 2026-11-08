import asyncio
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)
from core.config import settings
from core.logger import logger
from bot.handlers import (
    start_command,
    help_command,
    get_subscribe_conversation_handler,
    my_subscriptions_command,
    unsubscribe_callback,
    market_catalog_command,
    market_pagination_callback,
    market_filter_platform_callback,
    buy_listing_callback,
    get_sell_conversation_handler,
    check_verification_callback,
    my_listings_command,
    escrow_list_command,
    escrow_detail_callback,
    view_credentials_callback,
    get_escrow_credential_handler,
    buyer_confirm_callback,
    get_escrow_dispute_handler,
    admin_command,
    admin_stats_callback,
    admin_verifications_callback,
    admin_approve_verification_callback,
    admin_disputes_callback,
    admin_arbitrate_deal_callback,
    admin_resolve_dispute_callback,
    admin_trigger_poll_callback,
    global_error_handler,
)


def create_bot_application() -> Application:
    """Builds and configures the python-telegram-bot v21 Application."""
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # 1. Conversation Handlers (High priority)
    app.add_handler(get_subscribe_conversation_handler())
    app.add_handler(get_sell_conversation_handler())
    app.add_handler(get_escrow_credential_handler())
    app.add_handler(get_escrow_dispute_handler())

    # 2. Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("market", market_catalog_command))
    app.add_handler(CommandHandler("my_subscriptions", my_subscriptions_command))
    app.add_handler(CommandHandler("unsubscribe", my_subscriptions_command))
    app.add_handler(CommandHandler("my_listings", my_listings_command))
    app.add_handler(CommandHandler("escrow", escrow_list_command))
    app.add_handler(CommandHandler("admin", admin_command))

    # 3. Navigation & General Callback Query Handlers
    app.add_handler(CallbackQueryHandler(start_command, pattern="^nav_main$"))
    app.add_handler(CallbackQueryHandler(help_command, pattern="^nav_help$"))
    app.add_handler(CallbackQueryHandler(market_catalog_command, pattern="^nav_marketplace$"))
    app.add_handler(CallbackQueryHandler(my_subscriptions_command, pattern="^nav_my_subs$"))
    app.add_handler(CallbackQueryHandler(escrow_list_command, pattern="^nav_escrows$"))
    app.add_handler(CallbackQueryHandler(admin_command, pattern="^nav_admin$"))

    # 4. Marketplace & Listing Callbacks
    app.add_handler(CallbackQueryHandler(market_pagination_callback, pattern="^market_page:"))
    app.add_handler(CallbackQueryHandler(market_filter_platform_callback, pattern="^market_filter_plat$"))
    app.add_handler(CallbackQueryHandler(buy_listing_callback, pattern="^buy_listing:"))
    app.add_handler(CallbackQueryHandler(check_verification_callback, pattern="^check_verif:"))
    app.add_handler(CallbackQueryHandler(unsubscribe_callback, pattern="^unsub:"))

    # 5. Escrow Callbacks
    app.add_handler(CallbackQueryHandler(escrow_detail_callback, pattern="^escrow_status:"))
    app.add_handler(CallbackQueryHandler(view_credentials_callback, pattern="^view_creds:"))
    app.add_handler(CallbackQueryHandler(buyer_confirm_callback, pattern="^buyer_confirm:"))

    # 6. Admin Callbacks
    app.add_handler(CallbackQueryHandler(admin_stats_callback, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_verifications_callback, pattern="^admin_verifs$"))
    app.add_handler(CallbackQueryHandler(admin_approve_verification_callback, pattern="^adm_appr_verif:"))
    app.add_handler(CallbackQueryHandler(admin_disputes_callback, pattern="^admin_disputes$"))
    app.add_handler(CallbackQueryHandler(admin_arbitrate_deal_callback, pattern="^adm_arb:"))
    app.add_handler(CallbackQueryHandler(admin_resolve_dispute_callback, pattern="^adm_resolve:"))
    app.add_handler(CallbackQueryHandler(admin_trigger_poll_callback, pattern="^admin_poll$"))

    # 7. Global Error Handler
    app.add_error_handler(global_error_handler)

    return app


def run_polling():
    """Runs the bot in standard long-polling mode (ideal for local dev / sandbox)."""
    logger.info("Initializing Telegram bot in polling mode...")
    app = create_bot_application()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_polling()

