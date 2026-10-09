
import os
import logging
import asyncio
import time
import uuid

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME", "lion12355663"
).strip().lstrip("@").lower()

BANK_CARD = os.getenv("BANK_CARD", "").strip()
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "").strip()

BUY_RATE = 1.70
SELL_RATE = 1.69
ORDER_TIMEOUT = 300

# Sınaq üçün yaddaşda saxlanılır.
ORDERS = {}
USER_ACTIVE_ORDER = {}

BUY_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🟢 USDT alışı", callback_data="buy")],
    [InlineKeyboardButton("🔴 USDT satışı", callback_data="sell")],
])

def is_admin(user):
    return bool(
        user
        and user.username
        and user.username.lower() == ADMIN_USERNAME
    )

def main_menu():
    return BUY_MENU

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user:
        return

    if is_admin(user):
        await update.effective_message.reply_text(
            "👋 Admin paneli.\n\n"
            "Gözləyən sifarişləri görmək üçün /orders yaz."
        )
        return

    await update.effective_message.reply_text(
        "Salam! 👋 USDT mübadilə botuna xoş gəlmisiniz.\n\n"
        f"🟢 USDT alış kursu: 1 USDT = {BUY_RATE:.2f} AZN\n"
        f"🔴 USDT satış kursu: 1 USDT = {SELL_RATE:.2f} AZN\n\n"
        "Davam etmək üçün əməliyyatı seçin:",
        reply_markup=main_menu(),
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    order_id = USER_ACTIVE_ORDER.get(user.id)
    order = ORDERS.get(order_id) if order_id else None

    if order and order["status"] in ("waiting_payment", "waiting_receipt"):
        order["status"] = "cancelled"
        USER_ACTIVE_ORDER.pop(user.id, None)
        await update.effective_message.reply_text(
            "Sifariş ləğv edildi. /start ilə yenidən başlaya bilərsiniz."
        )
    else:
        await update.effective_message.reply_text(
            "Ləğv ediləcək aktiv sifariş tapılmadı."
        )

async def orders_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text("Bu əmr yalnız admin üçündür.")
        return

    pending = [
        order for order in ORDERS.values()
        if order["status"] in (
            "waiting_receipt",
            "checking_payment",
            "waiting_wallet",
            "waiting_usdt",
            "checking_usdt",
            "waiting_card",
            "checking_payout",
        )
    ]

    if not pending:
        await update.effective_message.reply_text(
            "Hazırda gözləyən sifariş yoxdur."
        )
        return

    for order in pending:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Təsdiqlə",
                    callback_data=f"approve:{order['id']}",
                ),
                InlineKeyboardButton(
                    "Rədd et",
                    callback_data=f"reject:{order['id']}",
                ),
            ]
        ])

        await update.effective_message.reply_text(
            f"Sifariş: {order['id']}\n"
            f"Növ: {order['type']}\n"
            f>Məbləğ: {order.get('amount', '—')}\n"
            f"İstifadəçi ID: {order['user_id']}\n"
            f"Status: {order['status']}",
            reply_markup=keyboard,
        )

async def choose_operation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    choice = query.data

    if choice not in ("buy", "sell"):
        return

    existing_id = USER_ACTIVE_ORDER.get(user.id)
    existing = ORDERS.get(existing_id) if existing_id else None

    if existing and existing["status"] not in ("cancelled", "rejected", "completed"):
        await query.message.reply_text(
            "Sizin artıq aktiv sifarişiniz var. Əvvəl onu tamamlayın "
            "və ya /cancel yazın."
        )
        return

    order_id = uuid.uuid4().hex[:8].upper()
    order = {
        "id": order_id,
        "user_id": user.id,
        "username": user.username or "",
        "type": choice,
        "status": "waiting_amount",
        "created": time.time(),
    }
    ORDERS[order_id] = order
    USER_ACTIVE_ORDER[user.id] = order_id
    context.user_data["active_order"] = order_id

    if choice == "buy":
        text = (
            "🟢 USDT alışı\n"
            f"Kurs: 1 USDT = {BUY_RATE:.2f} AZN\n\n"
            "Neçə USDT almaq istəyirsiniz? Məbləği rəqəmlə göndərin."
        )
    else:
        text = (
            "🔴 USDT satışı\n"
            f"Kurs: 1 USDT = {SELL_RATE:.2f} AZN\n\n"
            "Neçə USDT satmaq istəyirsiniz? Məbləği rəqəmlə göndərin."
        )

    await query.message.reply_text(text)

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if is_admin(user):
        await message.reply_text(
            "Admin əmrləri: /orders\n"
            "Sifarişin təsdiqi və rəddi üçün /orders panelindəki düymələrdən istifadə edin."
        )
        return

    order_id = USER_ACTIVE_ORDER.get(user.id)
    order = ORDERS.get(order_id) if order_id else None

    if not order:
        await message.reply_text(
            "Aktiv sifarişiniz yoxdur. /start yazaraq başlayın."
        )
        return

    if order["status"] == "waiting_amount":
        if not message.text:
            await message.reply_text("Zəhmət olmasa məbləği rəqəmlə göndərin.")
            return

        try:
            amount = float(message.text.replace(",", ".").strip())
            if not (0 < amount <= 1000000):
                raise ValueError
        except ValueError:
            await message.reply_text(
                "Düzgün məbləğ daxil edin. Məsələn: 100"
            )
            return

        order["amount"] = round(amount, 4)
        order["azn"] = round(
            amount * (BUY_RATE if order["type"] == "buy" else SELL_RATE),
            2,
        )

        if order["type"] == "buy":
            order["status"] = "waiting_receipt"
            order["deadline"] = time.time() + ORDER_TIMEOUT

            if not BANK_CARD:
                await message.reply_text(
                    "Bank kartı hələ konfiqurasiya edilməyib. "
                    "Zəhmət olmasa sonra yenidən cəhd edin."
                )
                order["status"] = "cancelled"
                USER_ACTIVE_ORDER.pop(user.id, None)
                return

            await message.reply_text(
                f"Sifariş #{order_id}\n"
                f"Məbləğ: {amount:g} USDT\n"
                f"Ödəniş: {order['azn']:.2f} AZN\n\n"
                f"Bank kartı: {BANK_CARD}\n\n"
                "Ödənişi 5 dəqiqə ərzində edin və qəbzin şəklini göndərin. "
                "Ödəniş etmədən qəbz göndərməyin."
            )
        else:
            order["status"] = "waiting_usdt"
            order["deadline"] = time.time() + ORDER_TIMEOUT

            if not USDT_ADDRESS:
                await message.reply_text(
                    "USDT ünvanı hələ konfiqurasiya edilməyib. "
                    "Zəhmət olmasa sonra yenidən cəhd edin."
                )
                order["status"] = "cancelled"
                USER_ACTIVE_ORDER.pop(user.id, None)
                return

            await message.reply_text(
                f"Sifariş #{order_id}\n"
                f"Siz göndərəcəksiniz: {amount:g} USDT\n"
                f"Təxmini ödəniş: {order['azn']:.2f} AZN\n\n"
                f"TRC20 ünvanı: {USDT_ADDRESS}\n\n"
                "Köçürməni 5 dəqiqə ərzində edin. "
                "Sonra əməliyyatın TXID-sini mətnlə göndərin. "
                "Şəbəkədə təsdiq yoxlanmadan sifariş təsdiqlənməyəcək."
            )
        return

    if order["status"] == "waiting_receipt":
        if time.time() > order["deadline"]:
            order["status"] = "cancelled"
            USER_ACTIVE_ORDER.pop(user.id, None)
            await message.reply_text(
                "5 dəqiqəlik müddət bitdi. Sifariş ləğv edildi. /start yazın."
            )
            return

        if not message.photo:
            await message.reply_text("Zəhmət olmasa ödəniş qəbzinin şəklini göndərin.")
            return

        order["status"] = "checking_payment"
        await message.reply_text(
            "Qəbz qəbul edildi. Admin ödənişi real olaraq yoxlayacaq. "
            "Yoxlama bitənədək gözləyin."
        )

        await notify_admin(context, order, message.photo[-1].file_id)
        return

    if order["status"] == "waiting_usdt":
        if time.time() > order["deadline"]:
            order["status"] = "cancelled"
            USER_ACTIVE_ORDER.pop(user.id, None)
            await message.reply_text(
                "5 dəqiqəlik müddət bitdi. Sifariş ləğv edildi. /start yazın."
            )
            return

        txid = (message.text or "").strip()
        if len(txid) < 20 or len(txid) > 150:
            await message.reply_text(
                "Zəhmət olmasa əməliyyatın düzgün TXID-sini göndərin."
            )
            return

        order["txid"] = txid
        order["status"] = "checking_usdt"
        await message.reply_text(
            "TXID qəbul edildi. Admin əməliyyatı yoxlayacaq. "
            "Şəbəkə təsdiqi yoxlanmadan ödəniş təsdiqlənmir."
        )
        await notify_admin(context, order)
        return

    if order["status"] == "waiting_wallet":
        wallet = (message.text or "").strip()
        if not wallet.startswith("T") or len(wallet) < 30 or len(wallet) > 40:
            await message.reply_text(
                "TRC20 ünvanı düzgün görünmür. Ünvanı yenidən göndərin."
            )
            return

        order["wallet"] = wallet
        order["status"] = "checking_payout"
        await message.reply_text(
            "TRC20 ünvanı qəbul edildi. Admin sifarişi yoxlayacaq. "
            "Təsdiq olunmadan USDT göndərilmir."
        )
        await notify_admin(context, order)
        return

    if order["status"] == "waiting_card":
        card = (message.text or "").strip()
        digits = "".join(ch for ch in card if ch.isdigit())
        if len(digits) < 16 or len(digits) > 19:
            await message.reply_text(
                "Zəhmət olmasa bank kartı nömrəsini yenidən yoxlayın."
            )
            return

        order["payout_card"] = digits
        order["status"] = "checking_payout"
        await message.reply_text(
            "Kart məlumatı qəbul edildi. Admin ödənişi yoxlayacaq. "
            "Təsdiq olmadan köçürmə edilməyəcək."
        )
        await notify_admin(context, order)
        return

    await message.reply_text(
        f"Sifariş statusu: {order['status']}. /cancel və ya /start istifadə edin."
    )

async def notify_admin(
    context: ContextTypes.DEFAULT_TYPE,
    order: dict,
    receipt_file_id: str = "",
):
    # Admin istifadəçi adı ilə tapılır; əvvəl botu açıb /start yazmalıdır.
    # Bot Telegram-dan istifadəçi adını axtarıb şəxsi mesaj başlada bilməz.
    for chat_id in context.application.bot_data.get("admin_chat_ids", set()):
        text = (
            f"Yeni yoxlama tələb olunur\n"
            f"Sifariş: {order['id']}\n"
            f"Növ: {order['type']}\n"
            f"Məbləğ: {order.get('amount', '—')}\n"
            f"AZN: {order.get('azn', '—')}\n"
            f"İstifadəçi ID: {order['user_id']}\n"
            f"Status: {order['status']}\n"
            f"TXID: {order.get('txid', '—')}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Təsdiqlə", callback_data=f"approve:{order['id']}"),
                InlineKeyboardButton("Rədd et", callback_data=f"reject:{order['id']}"),
            ]
        ])
        if receipt_file_id:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=receipt_file_id,
                caption=text,
                reply_markup=keyboard,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
            )

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(user):
        context.application.bot_data.setdefault("admin_chat_ids", set()).add(user.id)
        await update.effective_message.reply_text(
            "Admin aktivdir. /orders yazaraq sifarişləri görə bilərsiniz."
        )
    else:
        await start(update, context)

async def admin_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user):
        await query.message.reply_text("Bu əməliyyat yalnız admin üçündür.")
        return

    action, order_id = query.data.split(":", 1)
    order = ORDERS.get(order_id)

    if not order:
        await query.message.reply_text(
            "Sifariş tapılmadı. Bot yenidən başladığı üçün yaddaş təmizlənmiş ola bilər."
        )
        return

    if action == "reject":
        order["status"] = "rejected"
        USER_ACTIVE_ORDER.pop(order["user_id"], None)
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=f"Sifariş #{order_id} admin tərəfindən rədd edildi. /start ilə yenidən cəhd edin.",
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Sifariş rədd edildi.")
        return

    # Təsdiq düyməsi yalnız yoxlama prosesini irəli aparır.
    # Bot özü bank və blockchain ödənişlərini yoxlamır və köçürmə etmir.
    if order["type"] == "buy" and order["status"] == "checking_payment":
        order["status"] = "waiting_wallet"
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(
                "Admin ödənişi yoxladığını təsdiqlədi. "
                "USDT almaq üçün TRC20 cüzdan ünvanınızı göndərin."
            ),
        )
    elif order["type"] == "sell" and order["status"] == "checking_usdt":
        order["status"] = "waiting_card"
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(
                "Admin yoxlama mərhələsini təsdiqlədi. "
                "AZN ödənişi üçün bank kartı nömrənizi göndərin."
            ),
        )
    elif order["status"] == "checking_payout":
        # Real köçürmə həyata keçirilmir. Son təsdiq üçün təhlükəsiz saxlanılır.
        order["status"] = "approved_pending_manual_transfer"
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(
                "Sifariş yoxlamadan keçdi və əl ilə köçürmə üçün növbəyə alındı. "
                "Bu bot avtomatik köçürmə etmir. Köçürmə real olaraq tamamlanandan "
                "sonra admin sifarişi əl ilə bağlamalıdır."
            ),
        )
    else:
        await query.message.reply_text(
            f"Bu status üçün təsdiq mümkün deyil: {order['status']}"
        )
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"Sifariş #{order_id} növbəti mərhələyə keçirildi: {order['status']}"
    )

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logging.exception("Bot xətası", exc_info=context.error)

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN Render Environment Variables bölməsində yoxdur.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", admin_start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CallbackQueryHandler(admin_action, pattern=r"^(approve|reject):"))
    app.add_handler(CallbackQueryHandler(choose_operation, pattern=r"^(buy|sell)$"))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
            handle_message,
        )
    )
    app.add_error_handler(error_handler)

    # Python 3.14-də hadisə dövrəsini əvvəlcədən yaradırıq.
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling()

if __name__ == "__main__":
    main()
