import os
import sqlite3
import logging
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME", "lion12355663"
).lstrip("@").lower()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
BANK_CARD = os.getenv("BANK_CARD", "")
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "")
BUY_RATE = 1.70
SELL_RATE = 1.69
DB_FILE = "orders.db"
def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con
def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                kind TEXT NOT NULL,
                amount TEXT,
                wallet TEXT,
                txid TEXT,
                card TEXT,
                status TEXT NOT NULL,
                created TEXT NOT NULL
            )
        """)
def new_order(user, kind):
    with db() as con:
        cur = con.execute("""
            INSERT INTO orders
            (user_id, username, kind, status, created)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            kind,
            "enter_amount",
            datetime.now().isoformat(timespec="seconds"),
        ))
        return cur.lastrowid
def get_order(order_id):
    with db() as con:
        return con.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
def update_order(order_id, **fields):
    if not fields:
        return
    allowed = {
        "amount", "wallet", "txid", "card", "status"
    }
    if any(k not in allowed for k in fields):
        raise ValueError("Invalid field")
    sql = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [order_id]
    with db() as con:
        con.execute(
            f"UPDATE orders SET {sql} WHERE id = ?", values
        )
def is_admin(update):
    user = update.effective_user
    return bool(
        user
        and user.username
        and user.username.lower() == ADMIN_USERNAME
    )
async def notify_admin(context, text, keyboard=None):
    chat_id = ADMIN_CHAT_ID or context.application.bot_data.get(
        "admin_chat_id"
    )
    if not chat_id:
        logging.warning(
            "Admin chat ID yoxdur. Admin botda /start etməlidir."
        )
        return False
    await context.bot.send_message(
        chat_id=int(chat_id),
        text=text,
        reply_markup=keyboard,
    )
    return True
def admin_buttons(order_id, action):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Təsdiqlə / tamamla",
            callback_data=f"{action}:{order_id}"
        ),
        InlineKeyboardButton(
            "❌ Rədd et",
            callback_data=f"reject:{order_id}"
        ),
    ]])
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(update):
        context.application.bot_data["admin_chat_id"] = user.id
        await update.message.reply_text(
            "Admin panelinə xoş gəldin.\n"
            "Sifarişləri görmək üçün /orders yaz."
        )
        return
    keyboard = ReplyKeyboardMarkup(
        [["🟢 USDT alışı", "🔴 USDT satışı"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "Salam! USDT mübadilə botuna xoş gəlmisiniz.\n"
        f"USDT alışı: 1 USDT = {BUY_RATE} AZN\n"
        f"USDT satışı: 1 USDT = {SELL_RATE} AZN\n\n"
        "Davam etmək üçün seçim edin.",
        reply_markup=keyboard,
    )
async def orders_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update):
        await update.message.reply_text("Bu əmr yalnız admin üçündür.")
        return
    with db() as con:
        rows = con.execute("""
            SELECT * FROM orders
            WHERE status NOT IN ('completed', 'rejected')
            ORDER BY id DESC LIMIT 20
        """).fetchall()
    if not rows:
        await update.message.reply_text("Aktiv sifariş yoxdur.")
        return
    for o in rows:
        text = (
            f"Sifariş: #{o['id']}\n"
            f"Növ: {o['kind']}\n"
            f"Məbləğ: {o['amount'] or 'hələ daxil edilməyib'}\n"
            f"Müştəri ID: {o['user_id']}\n"
            f"İstifadəçi: @{o['username'] or 'yoxdur'}\n"
            f"TRC20 ünvanı: {o['wallet'] or 'yoxdur'}\n"
            f"TXID: {o['txid'] or 'yoxdur'}\n"
            f"Bank kartı: {o['card'] or 'yoxdur'}\n"
            f"Status: {o['status']}"
        )
        await update.message.reply_text(text)
async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    message = update.effective_message
    text = (message.text or "").strip() if message else ""
    if not text:
        return
    if text in ("🟢 USDT alışı", "🔴 USDT satışı"):
        kind = "buy" if text == "🟢 USDT alışı" else "sell"
        order_id = new_order(user, kind)
        context.user_data["active_order"] = order_id
        if kind == "buy":
            update_order(order_id, status="enter_amount")
            await message.reply_text(
                f"USDT alışı seçildi. Kurs: {BUY_RATE} AZN.\n"
                "Neçə USDT almaq istəyirsiniz? Məbləği rəqəmlə yazın."
            )
        else:
            update_order(order_id, status="enter_amount")
            await message.reply_text(
                f"USDT satışı seçildi. Kurs: {SELL_RATE} AZN.\n"
                "Neçə USDT satmaq istəyirsiniz? Məbləği rəqəmlə yazın."
            )
        return
    order_id = context.user_data.get("active_order")
    if not order_id:
        await message.reply_text(
            "Başlamaq üçün /start yazın və seçim edin."
        )
        return
    order = get_order(order_id)
    if not order or order["user_id"] != user.id:
        context.user_data.pop("active_order", None)
        await message.reply_text("Sifariş tapılmadı. /start yazın.")
        return
    status = order["status"]
    if status == "enter_amount":
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0 or amount > 100000000:
                raise ValueError
        except ValueError:
            await message.reply_text("Zəhmət olmasa düzgün məbləğ yazın.")
            return
        update_order(order_id, amount=f"{amount:g}")
        if order["kind"] == "buy":
            if not BANK_CARD:
                await message.reply_text(
                    "Ödəniş kartı hələ konfiqurasiya edilməyib. Adminlə əlaqə saxlayın."
                )
                return
            update_order(order_id, status="waiting_receipt")
            await message.reply_text(
                f"{amount:g} USDT üçün məbləğ: "
                f"{amount * BUY_RATE:.2f} AZN.\n"
                f"Ödəniş kartı: {BANK_CARD}\n"
                "5 dəqiqə ərzində ödəniş edin və qəbzin şəklini göndərin."
            )
        else:
            if not USDT_ADDRESS:
                await message.reply_text(
                    "USDT ünvanı hələ konfiqurasiya edilməyib. Adminlə əlaqə saxlayın."
                )
                return
            update_order(order_id, status="waiting_txid")
            await message.reply_text(
                f"{amount:g} USDT göndərin bu TRC20 ünvanına:\n"
                f"{USDT_ADDRESS}\n\n"
                "Transfer tamamlandıqdan sonra TXID-ni göndərin. "
                "Göndərişi admin yoxlayacaq."
            )
        return
    if status == "waiting_wallet" and order["kind"] == "buy":
        wallet = text
        if not wallet.startswith("T") or len(wallet) != 34:
            await message.reply_text(
                "Bu, düzgün TRON/TRC20 ünvanına oxşamır. "
                "Ünvan adətən T ilə başlayır və 34 simvol olur. Yenidən göndərin."
            )
            return
        update_order(
            order_id, wallet=wallet, status="checking_payout"
        )
        o = get_order(order_id)
        sent = await notify_admin(
            context,
            "🟡 USDT ALIŞI — köçürmə gözləyir\n\n"
            f"Sifariş: #{o['id']}\n"
            f"Məbləğ: {o['amount']} USDT\n"
            f"Müştəri ID: {o['user_id']}\n"
            f"TRC20 ünvanı: {wallet}\n\n"
            "Köçürməni əl ilə yoxlayın. Yalnız göndərdikdən sonra təsdiqləyin.",
            admin_buttons(order_id, "buy_paid"),
        )
        await message.reply_text(
            "TRC20 ünvanınız adminə göndərildi. "
            "Köçürmə yoxlanılır."
            if sent else
            "Ünvan qəbul edildi, amma adminə bildiriş göndərilmədi. "
            "Zəhmət olmasa adminlə əlaqə saxlayın."
        )
        return
    if status == "waiting_txid" and order["kind"] == "sell":
        txid = text
        if len(txid) < 20 or len(txid) > 150:
            await message.reply_text("Zəhmət olmasa düzgün TXID göndərin.")
            return
        update_order(order_id, txid=txid, status="checking_usdt")
        o = get_order(order_id)
        sent = await notify_admin(
            context,
            "🟡 USDT SATIŞI — depozit yoxlanmalıdır\n\n"
            f"Sifariş: #{o['id']}\n"
            f"Məbləğ: {o['amount']} USDT\n"
            f"Müştəri ID: {o['user_id']}\n"
            f"TXID: {txid}\n"
            "Blockchain-də transferi yoxlayın. "
            "Depozit təsdiqlənmədən təsdiq düyməsinə basmayın.",
            admin_buttons(order_id, "sell_deposit"),
        )
        await message.reply_text(
            "TXID adminə göndərildi. Depozit yoxlanılır."
            if sent else
            "TXID qəbul edildi, amma adminə bildiriş göndərilmədi."
        )
        return
    if status == "waiting_card" and order["kind"] == "sell":
        update_order(order_id, card=text, status="checking_payout")
        o = get_order(order_id)
        sent = await notify_admin(
            context,
            "🟡 USDT SATIŞI — bank ödənişi gözləyir\n\n"
            f"Sifariş: #{o['id']}\n"
            f"Məbləğ: {o['amount']} USDT\n"
            f"Ödəniləcək: {float(o['amount']) * SELL_RATE:.2f} AZN\n"
            f"Müştəri ID: {o['user_id']}\n"
            f"TXID: {o['txid']}\n"
            f"Bank kartı: {text}\n\n"
            "Bank köçürməsini etdikdən sonra təsdiqləyin.",
            admin_buttons(order_id, "sell_paid"),
        )
        await message.reply_text(
            "Bank kartı adminə göndərildi. Ödəniş yoxlanılır."
            if sent else
            "Kart məlumatı qəbul edildi, amma adminə bildiriş göndərilmədi."
        )
        return
    await message.reply_text(
        "Sifarişinizin hazırkı statusu: "
        f"{status}. Yeni seçim üçün /start yazın."
    )
async def handle_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    order_id = context.user_data.get("active_order")
    if not order_id:
        await update.effective_message.reply_text(
            "Əvvəl /start yazıb sifariş yaradın."
        )
        return
    order = get_order(order_id)
    if (
        not order
        or order["user_id"] != user.id
        or order["kind"] != "buy"
        or order["status"] != "waiting_receipt"
    ):
        await update.effective_message.reply_text(
            "Hazırda qəbz gözləyən alış sifarişiniz yoxdur."
        )
        return
    update_order(order_id, status="checking_receipt")
    o = get_order(order_id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Qəbzi təsdiqlə",
            callback_data=f"receipt_ok:{order_id}"
        ),
        InlineKeyboardButton(
            "❌ Rədd et",
            callback_data=f"reject:{order_id}"
        ),
    ]])
    chat_id = ADMIN_CHAT_ID or context.application.bot_data.get(
        "admin_chat_id"
    )
    if not chat_id:
        update_order(order_id, status="waiting_receipt")
        await update.effective_message.reply_text(
            "Admin botu açıb /start yazmalıdır. Sonra qəbzi yenidən göndərin."
        )
        return
    await context.bot.send_photo(
        chat_id=int(chat_id),
        photo=update.effective_message.photo[-1].file_id,
        caption=(
            f"🧾 ÖDƏNİŞ QƏBZİ\nSifariş: #{o['id']}\n"
            f"Məbləğ: {o['amount']} USDT\n"
            f"Müştəri ID: {o['user_id']}\n"
            "Ödənişi bankdan yoxlayın."
        ),
        reply_markup=keyboard,
    )
    await update.effective_message.reply_text(
        "Qəbz adminə göndərildi. Ödəniş yoxlanılır."
    )
async def admin_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()
    if not is_admin(update):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Bu düymə yalnız admin üçündür.")
        return
    action, order_id_text = query.data.split(":")
    order_id = int(order_id_text)
    o = get_order(order_id)
    if not o:
        await query.message.reply_text("Sifariş tapılmadı.")
        return
    if action == "reject":
        update_order(order_id, status="rejected")
        await context.bot.send_message(
            chat_id=o["user_id"],
            text=f"❌ Sifariş #{order_id} rədd edildi. Adminlə əlaqə saxlayın."
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"Sifariş #{order_id} rədd edildi."
        )
        return
    if action == "receipt_ok":
        if o["status"] != "checking_receipt":
            await query.message.reply_text("Bu qəbz artıq işlənib.")
            return
        update_order(order_id, status="waiting_wallet")
        context.application.bot_data.setdefault(
            "user_order", {}
        )[o["user_id"]] = order_id
        await context.bot.send_message(
            chat_id=o["user_id"],
            text=(
                f"✅ Sifariş #{order_id} üçün qəbz admin tərəfindən təsdiqləndi.\n"
                "İndi USDT almaq istədiyiniz TRC20 pul kisəsi ünvanını göndərin."
            )
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"Qəbz təsdiqləndi. Sifariş #{order_id}: TRC20 ünvanı gözlənilir."
        )
        return
    if action == "sell_deposit":
        if o["status"] != "checking_usdt":
            await query.message.reply_text("Bu sifariş artıq işlənib.")
            return
        update_order(order_id, status="waiting_card")
        await context.bot.send_message(
            chat_id=o["user_id"],
            text=(
                f"✅ Sifariş #{order_id}: depozit admin tərəfindən təsdiqləndi.\n"
                "Bank köçürməsi üçün kart nömrənizi göndərin."
            )
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"Depozit təsdiqləndi. Sifariş #{order_id}: bank kartı gözlənilir."
        )
        return
    if action in ("buy_paid", "sell_paid"):
        if o["status"] != "checking_payout":
            await query.message.reply_text(
                "Sifariş köçürmə gözləyən statusda deyil."
            )
            return
        update_order(order_id, status="completed")
        await context.bot.send_message(
            chat_id=o["user_id"],
            text=(
                f"✅ Sifariş #{order_id} admin tərəfindən tamamlandı.\n"
                "Admin köçürmənin tamamlandığını təsdiqlədi."
            )
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"✅ Sifariş #{order_id} tamamlandı. Müştəriyə bildiriş göndərildi."
        )
        return
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("active_order", None)
    await update.effective_message.reply_text(
        "Aktiv sifariş seçimi sıfırlandı. /start yazaraq yenidən başlayın."
    )
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.run_polling()
if __name__ == "__main__":
    main()
