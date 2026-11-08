from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from models.monitored_source import PlatformType


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🔔 Notifications", callback_data="nav_notifications"),
            InlineKeyboardButton("🛒 Marketplace", callback_data="nav_marketplace"),
        ],
        [
            InlineKeyboardButton("📤 Sell Account", callback_data="nav_sell"),
            InlineKeyboardButton("🤝 Active Escrows", callback_data="nav_escrows"),
        ],
        [
            InlineKeyboardButton("📋 My Subscriptions", callback_data="nav_my_subs"),
            InlineKeyboardButton("ℹ️ Help & Safety", callback_data="nav_help"),
        ],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🛡️ Admin Dashboard", callback_data="nav_admin")])
    return InlineKeyboardMarkup(buttons)


def platform_selection_keyboard(prefix: str = "sub_plat") -> InlineKeyboardMarkup:
    """Returns platform selection keyboard."""
    buttons = [
        [
            InlineKeyboardButton("▶️ YouTube", callback_data=f"{prefix}:{PlatformType.YOUTUBE.value}"),
            InlineKeyboardButton("✈️ Telegram", callback_data=f"{prefix}:{PlatformType.TELEGRAM.value}"),
        ],
        [
            InlineKeyboardButton("🎵 TikTok", callback_data=f"{prefix}:{PlatformType.TIKTOK.value}"),
            InlineKeyboardButton("📸 Instagram", callback_data=f"{prefix}:{PlatformType.INSTAGRAM.value}"),
        ],
        [
            InlineKeyboardButton("📘 Facebook", callback_data=f"{prefix}:{PlatformType.FACEBOOK.value}"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_action"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def market_filter_keyboard(current_platform: str = "ALL", page: int = 1, total_pages: int = 1) -> InlineKeyboardMarkup:
    """Filter and navigation bar for marketplace catalog."""
    platform_label = current_platform if current_platform != "ALL" else "All Platforms"
    buttons = [
        [
            InlineKeyboardButton(f"🌐 Platform: {platform_label}", callback_data="market_filter_plat"),
        ],
        [
            InlineKeyboardButton("💰 Price: Any", callback_data="market_filter_price"),
            InlineKeyboardButton("🏷️ Niche: Any", callback_data="market_filter_niche"),
        ],
    ]

    # Pagination buttons
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"market_page:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="market_page_info"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"market_page:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data=f"market_refresh:{page}"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main"),
    ])
    return InlineKeyboardMarkup(buttons)


def listing_detail_keyboard(listing_id: int, price: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💳 Buy via Escrow (${price:.2f})", callback_data=f"buy_listing:{listing_id}")],
        [InlineKeyboardButton("« Back to Catalog", callback_data="market_page:1")],
    ])


def verification_action_keyboard(verification_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Verify Now", callback_data=f"check_verif:{verification_id}")],
        [InlineKeyboardButton("❌ Cancel Listing", callback_data=f"cancel_listing:{verification_id}")],
    ])


def escrow_buyer_keyboard(escrow_ref: str, has_viewed_creds: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if not has_viewed_creds:
        buttons.append([InlineKeyboardButton("👁️ View One-Time Credentials", callback_data=f"view_creds:{escrow_ref}")])
    buttons.extend([
        [InlineKeyboardButton("✅ Confirm Full Control & Release", callback_data=f"buyer_confirm:{escrow_ref}")],
        [InlineKeyboardButton("🚨 Report Problem / Dispute", callback_data=f"raise_dispute:{escrow_ref}")],
        [InlineKeyboardButton("🔄 Refresh Status", callback_data=f"escrow_status:{escrow_ref}")],
    ])
    return InlineKeyboardMarkup(buttons)


def escrow_seller_keyboard(escrow_ref: str, status_str: str) -> InlineKeyboardMarkup:
    buttons = []
    if status_str == "FUNDS_HELD":
        buttons.append([InlineKeyboardButton("🔐 Submit Account Credentials", callback_data=f"submit_creds:{escrow_ref}")])
    buttons.extend([
        [InlineKeyboardButton("🔄 Refresh Status", callback_data=f"escrow_status:{escrow_ref}")],
        [InlineKeyboardButton("🚨 Dispute Deal", callback_data=f"raise_dispute:{escrow_ref}")],
    ])
    return InlineKeyboardMarkup(buttons)


def admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Pending Verifications", callback_data="admin_verifs"),
            InlineKeyboardButton("⚖️ Active Disputes", callback_data="admin_disputes"),
        ],
        [
            InlineKeyboardButton("📊 Platform Stats", callback_data="admin_stats"),
            InlineKeyboardButton("⚡ Trigger Social Poll", callback_data="admin_poll"),
        ],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="nav_main")],
    ])


def admin_dispute_keyboard(escrow_ref: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Release to Seller", callback_data=f"adm_resolve:{escrow_ref}:release_to_seller"),
            InlineKeyboardButton("↩️ Refund Buyer", callback_data=f"adm_resolve:{escrow_ref}:refund_buyer"),
        ],
        [InlineKeyboardButton("« Back to Disputes", callback_data="admin_disputes")],
    ])

