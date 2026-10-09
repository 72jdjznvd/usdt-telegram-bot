
import os
import re
import sqlite3
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME", "lion12355663"
).strip().lstrip("@").lower()
BANK_CARD = os.getenv("BANK_CARD", "").strip()
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
DB_PATH = "orders.db"

BUY_RATE = Decimal("1.70")
SELL_RATE = Decimal("1.69")


def db():
    con = sqlite3.connect(DB_PATH)
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
                amount TEXT NOT NULL,
                fiat_amount TEXT NOT NULL,
                status TEXT NOT NULL,
                receipt_message_id INTEGER,
                wallet TEXT,
                txid TEXT,
                bank_card TEXT,
                created_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


def get_order(order_id):
    with db() as con:
        row = con.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        return dict(row) if row else None


def create_order(user, kind, amount, fiat, status):
    with db() as con:
        cur = con.execute("""
            INSERT INTO orders
            (user_id, username, kind, amount, fiat_amount,
             status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            kind,
            str(amount),
            str(fiat),
            status,
            datetime.utcnow().isoformat(),
        ))
        return cur.lastrowid


def change_status(order_id, expected, new_status, **fields):
    allowed_fields = {
        "wallet", "txid", "bank_card", "receipt_message_id"
    }
    if any(key not in allowed_fields for key in fields):
        raise ValueError("Invalid database field")

    assignments = ["status = ?"]
    values = [new_status]

    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        values.append(value)

    values.extend([order_id, expected])

    with db() as con:
        cur = con.execute(
            f"UPDATE orders SET {', '.join(assignments)} "
            "WHERE id = ? AND status = ?",
            values,
        )
        return cur.rowcount == 1


def active_order(user_id):
    with db() as con:
        row = con.execute("""
            SELECT * FROM orders
            WHERE user_id = ?
              AND status NOT IN ('completed', 'rejected')
            ORDER BY id DESC
            LIMIT 1
        """, (user_id,)).fetchone()
        return dict(row) if row else None


def admin_id(context):
    if ADMIN_CHAT_ID.isdigit():
        return int(ADMIN_CHAT_ID)

    with db() as con:
        row = con.execute(
            "SELECT value FROM settings WHERE key = 'admin_chat_id'"
        ).fetchone()

    return int(row["value"]) if row else None


def save_admin_id(chat_id):
    with db() as con:
        con.execute("""
            INSERT INTO settings (key, value)
            VALUES ('admin_chat_id', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (str(chat_id),))


def money(value):
    return f"{Decimal(str(value)):,.2f}"


def order_buttons(order_id, *buttons):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                label,
                callback_data=f"{action}:{order_id}",
            )
        ]
        for label, action in buttons
    ])


async def notify_admin(context, text, markup=None):
    target = admin_id(context)
    if not target:
        logger.warning(
            "Admin chat ID is missing. Admin must send /start to the bot."
        )
        return False

    try:
        await context.bot.send_message(
            chat_id=target,
            text=text,
            reply_markup=markup,
        )
        return True
    except Exception:
        logger.exception("Could not notify admin")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.username and user.username.lower() == ADMIN_USERNAME:
        save_admin_id(chat.id)
        await update.message.reply_text(
            "Salam, admin! Bot hazırdır.\n\n"
            "/orders — aktiv sifarişlərə bax\n"
            "Sifariş bildirişlərindəki düymələrlə sifarişləri idarə et."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("USDT alışı", callback_data="buy"),
            InlineKeyboardButton("USDT satışı", callback_data="sell"),
        ]
    ])

    await update.message.reply_text(
        "Salam! USDT əməliyyat botuna xoş gəlmisiniz.\n\n"
        f"USDT alışı: 1 USDT = {money(BUY_RATE)} AZN\n"
        f"USDT satışı: 1 USDT = {money(SELL_RATE)} AZN\n\n"
        "Əməliyyat növünü seçin:",
        reply_markup=keyboard,
    )


async def orders_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    if not user.username or user.username.lower() != ADMIN_USERNAME:
        await update.message.reply_text("Bu əmr yalnız admin üçündür.")
        return

    with db() as con:
        rows = con.execute("""
            SELECT * FROM orders
            WHERE status NOT IN ('completed', 'rejected')
            ORDER BY id DESC
            LIMIT 30
        """).fetchall()

    if not rows:
        await update.message.reply_text("Aktiv sifariş yoxdur.")
        return

    for row in rows:
        o = dict(row)
        text = (
            f"Sifariş #{o['id']}\n"
            f"Növ: {o['kind']}\n"
            f"Məbləğ: {o['amount']} USDT\n"
            f"AZN: {o['fiat_amount']}\n"
            f"Müştəri ID: {o['user_id']}\n"
            f"Status: {o['status']}\n"
        )
        if o["wallet"]:
            text += f"TRC20 ünvanı: {o['wallet']}\n"
        if o["txid"]:
            text += f"TXID: {o['txid']}\n"
        if o["bank_card"]:
            text += f"Müştərinin kartı: {o['bank_card']}\n"

        await update.message.reply_text(text)


async def callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data in ("buy", "sell"):
        existing = active_order(user.id)
        if existing:
            await query.message.reply_text(
                f"Sizin #{existing['id']} nömrəli aktiv sifarişiniz var. "
                "Yeni sifariş açmazdan əvvəl onu tamamlayın."
            )
            return

        await query.message.reply_text(
            "Məbləği USDT ilə göndərin. Məsələn: 25"
        )
        context.user_data["new_order_kind"] = data
        return

    if ":" not in data:
        return

    action, raw_id = data.split(":", 1)
    if not raw_id.isdigit():
        return

    order_id = int(raw_id)
    o = get_order(order_id)
    if not o:
        await query.message.reply_text("Sifariş tapılmadı.")
        return

    if not user.username or user.username.lower() != ADMIN_USERNAME:
        await query.message.reply_text("Bu düymə yalnız admin üçündür.")
        return

    # Qəbzin admin tərəfindən təsdiqi
    if action == "receipt_ok":
        if o["status"] != "buy_check_receipt":
            await query.message.reply_text(
                "Bu sifariş artıq işlənib və ya statusu dəyişib."
            )
            return

        if not change_status(
            order_id, "buy_check_receipt", "buy_wait_wallet"
        ):
            await query.message.reply_text("Sifariş statusu dəyişib.")
            return

        try:
            await context.bot.send_message(
                o["user_id"],
                f"Qəbz #{order_id} təsdiqləndi.\n"
                "İndi USDT qəbul etmək üçün TRC20 ünvanınızı göndərin.\n\n"
                "Ünvanı diqqətlə yoxlayın.",
            )
        except Exception:
            logger.exception("Could not message customer")

        await query.message.reply_text(
            f"#{order_id}: qəbz təsdiqləndi. Müştəridən TRC20 ünvanı istənildi."
        )
        return

    if action == "reject":
        if o["status"] not in (
            "buy_check_receipt", "sell_check_deposit"
        ):
            await query.message.reply_text(
                "Bu sifariş artıq işlənib və ya statusu dəyişib."
            )
            return

        if not change_status(
            order_id, o["status"], "rejected"
        ):
            await query.message.reply_text("Sifariş statusu dəyişib.")
            return

        try:
            await context.bot.send_message(
                o["user_id"],
                f"#{order_id} nömrəli sifariş təsdiqlənmədi. "
                "Ətraflı məlumat üçün adminlə əlaqə saxlayın.",
            )
        except Exception:
            logger.exception("Could not message customer")

        await query.message.reply_text(
            f"#{order_id} nömrəli sifariş rədd edildi."
        )
        return

    # Satışda USDT depozitinin admin tərəfindən təsdiqi
    if action == "deposit_ok":
        if o["status"] != "sell_check_deposit":
            await query.message.reply_text(
                "Depozit artıq yoxlanıb və ya status dəyişib."
            )
            return

        if not change_status(
            order_id, "sell_check_deposit", "sell_wait_card"
        ):
            await query.message.reply_text("Sifariş statusu dəyişib.")
            return

        try:
            await context.bot.send_message(
                o["user_id"],
                f"#{order_id}: USDT depoziti yoxlanıldı.\n"
                "AZN ödənişi üçün bank kartı məlumatınızı göndərin.",
            )
        except Exception:
            logger.exception("Could not message customer")

        await query.message.reply_text(
            f"#{order_id}: depozit təsdiqləndi. Müştəridən kart istənildi."
        )
        return

    # Alış və satışda adminin son tamamlanma düyməsi
    if action in ("complete_buy", "complete_sell"):
        expected = (
            "buy_payout_pending"
            if action == "complete_buy"
            else "sell_payout_pending"
        )

        if o["status"] != expected:
            await query.message.reply_text(
                "Bu sifariş artıq tamamlanıb və ya statusu dəyişib."
            )
            return

        if not change_status(order_id, expected, "completed"):
            await query.message.reply_text(
                "Sifariş artıq başqa əməliyyatla işlənib."
            )
            return

        try:
            await context.bot.send_message(
                o["user_id"],
                f"✅ #{order_id} nömrəli sifariş uğurla tamamlandı.\n"
                "Əməkdaşlığınız üçün təşəkkür edirik.",
            )
        except Exception:
            logger.exception("Could not message customer")

        await query.message.reply_text(
            f"✅ #{order_id} tamamlandı. Status təkrar dəyişdirilə bilməz."
        )
        return


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    if user.username and user.username.lower() == ADMIN_USERNAME:
        return

    # Yeni sifariş məbləği
    kind = context.user_data.get("new_order_kind")
    if kind:
        if not message.text:
            await message.reply_text(
                "Zəhmət olmasa məbləği rəqəmlə yazın. Məsələn: 25"
            )
            return

        try:
            amount = Decimal(message.text.strip().replace(",", "."))
            if not amount.is_finite() or amount < Decimal("1") or amount > Decimal("100000"):
                raise InvalidOperation
            amount = amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            await message.reply_text(
                "Düzgün məbləğ yazın. Minimum 1 USDT. Məsələn: 25"
            )
            return

        if active_order(user.id):
            context.user_data.pop("new_order_kind", None)
            await message.reply_text(
                "Sizin artıq aktiv sifarişiniz var. Əvvəl onu tamamlayın."
            )
            return

        rate = BUY_RATE if kind == "buy" else SELL_RATE
        fiat = (amount * rate).quantize(Decimal("0.01"))

        if kind == "buy":
            status = "buy_wait_receipt"
        else:
            status = "sell_wait_txid"

        order_id = create_order(user, kind, amount, fiat, status)
        context.user_data.pop("new_order_kind", None)

        if kind == "buy":
            if not BANK_CARD:
                await message.reply_text(
                    "Bank kartı hələ botda qurulmayıb. Adminlə əlaqə saxlayın."
                )
                change_status(
                    order_id, "buy_wait_receipt", "rejected"
                )
                return

            await message.reply_text(
                f"🟢 USDT ALIŞI — sifariş #{order_id}\n\n"
                f"Məbləğ: {amount} USDT\n"
                f"Ödəniləcək: {money(fiat)} AZN\n"
                f"Kurs: 1 USDT = {money(BUY_RATE)} AZN\n\n"
                f"Bank kartı:\n{BANK_CARD}\n\n"
                "Ödəniş etdikdən sonra qəbzin şəklini göndərin."
            )
        else:
            if not USDT_ADDRESS:
                await message.reply_text(
                    "USDT qəbul ünvanı hələ qurulmayıb. Adminlə əlaqə saxlayın."
                )
                change_status(
                    order_id, "sell_wait_txid", "rejected"
                )
                return

            await message.reply_text(
                f"🔵 USDT SATIŞI — sifariş #{order_id}\n\n"
                f"Məbləğ: {amount} USDT\n"
                f"Alacağınız məbləğ: {money(fiat)} AZN\n"
                f"Kurs: 1 USDT = {money(SELL_RATE)} AZN\n\n"
                "Yalnız TRON (TRC20) şəbəkəsindən göndərin:\n"
                f"{USDT_ADDRESS}\n\n"
                "Köçürmədən sonra TXID-ni göndərin. "
                "Depozit yoxlanmadan AZN ödənişi edilmir."
            )
        return

    order = active_order(user.id)
    if not order:
        await message.reply_text(
            "Aktiv sifarişiniz yoxdur. Başlamaq üçün /start yazın."
        )
        return

    order_id = order["id"]
    status = order["status"]

    # Alış: qəbzin qəbulu
    if status == "buy_wait_receipt":
        if not message.photo and not message.document:
            await message.reply_text(
                "Zəhmət olmasa ödəniş qəbzinin şəklini və ya faylını göndərin."
            )
            return

        if not change_status(
            order_id,
            "buy_wait_receipt",
            "buy_check_receipt",
            receipt_message_id=message.message_id,
        ):
            await message.reply_text(
                "Qəbz artıq qəbul edilib. Təkrar göndərməyin."
            )
            return

        markup = order_buttons(
            order_id,
            ("✅ Qəbzi təsdiqlə", "receipt_ok"),
            ("❌ Rədd et", "reject"),
        )

        sent = await notify_admin(
            context,
            f"🟡 USDT ALIŞI — qəbz yoxlanmalıdır\n\n"
            f"Sifariş: #{order_id}\n"
            f"Məbləğ: {order['amount']} USDT\n"
            f"Ödəniş: {order['fiat_amount']} AZN\n"
            f"Müştəri ID: {user.id}\n"
            f"Müştəri username: @{user.username or 'yoxdur'}\n\n"
            "Qəbzi yoxlayın. Pul hesaba daxil olmadan təsdiqləməyin.",
            markup,
        )

        target = admin_id(context)
        if sent and target:
            try:
                await context.bot.copy_message(
                    chat_id=target,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                )
            except Exception:
                logger.exception("Could not copy receipt to admin")

        await message.reply_text(
            "Qəbz adminə göndərildi, yoxlanılır."
            if sent else
            "Qəbz qəbul edildi, amma adminə bildiriş getmədi. "
            "Admin botda /start yazmalıdır."
        )
        return

    # Alış: TRC20 ünvanının qəbulu
    if status == "buy_wait_wallet":
        wallet = (message.text or "").strip()

        if not re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", wallet):
            await message.reply_text(
                "TRC20 ünvanı düzgün görünmür. "
                "Adətən T hərfi ilə başlayır və 34 simvoldan ibarət olur. "
                "Ünvanı yenidən göndərin."
            )
            return

        target = admin_id(context)
        if not target:
            await message.reply_text(
                "Admin hələ botu aktivləşdirməyib. "
                "Admin botda /start yazmalıdır. Ünvanınızı sonra yenidən göndərin."
            )
            return

        if not change_status(
            order_id,
            "buy_wait_wallet",
            "buy_payout_pending",
            wallet=wallet,
        ):
            await message.reply_text(
                "Ünvan artıq qəbul edilib. Təkrar göndərməyin."
            )
            return

        markup = order_buttons(
            order_id,
            ("✅ USDT göndərildi — tamamla", "complete_buy"),
        )

        sent = await notify_admin(
            context,
            f"🟢 USDT ALIŞI — USDT göndərilməlidir\n\n"
            f"Sifariş: #{order_id}\n"
            f"Məbləğ: {order['amount']} USDT\n"
            f"Müştərinin ödədiyi: {order['fiat_amount']} AZN\n"
            f"Müştəri ID: {user.id}\n"
            f"Username: @{user.username or 'yoxdur'}\n\n"
            f"📬 MÜŞTƏRİNİN TRC20 ÜNVANI:\n{wallet}\n\n"
            "Ünvanı diqqətlə yoxlayın. USDT-ni özünüz göndərin. "
            "Yalnız transfer uğurla tamamlandıqdan sonra düyməni basın.",
            markup,
        )

        await message.reply_text(
            "✅ TRC20 ünvanınız qəbul edildi və adminə göndərildi. "
            "Admin köçürməni yoxlayır."
            if sent else
            "Ünvan qəbul edildi, amma adminə bildiriş göndərilmədi. "
            "Adminlə əlaqə saxlayın."
        )
        return

    # Satış: TXID qəbulu
    if status == "sell_wait_txid":
        txid = (message.text or "").strip()

        if len(txid) < 20 or len(txid) > 150:
            await message.reply_text("Zəhmət olmasa düzgün TXID göndərin.")
            return

        if not change_status(
            order_id,
            "sell_wait_txid",
            "sell_check_deposit",
            txid=txid,
        ):
            await message.reply_text(
                "TXID artıq qəbul edilib. Təkrar göndərməyin."
            )
            return

        markup = order_buttons(
            order_id,
            ("✅ Depoziti təsdiqlə", "deposit_ok"),
            ("❌ Rədd et", "reject"),
        )

        sent = await notify_admin(
            context,
            f"🟡 USDT SATIŞI — depozit yoxlanmalıdır\n\n"
            f"Sifariş: #{order_id}\n"
            f"Məbləğ: {order['amount']} USDT\n"
            f"Ödəniləcək: {order['fiat_amount']} AZN\n"
            f"Müştəri ID: {user.id}\n"
            f"TXID: {txid}\n\n"
            "TRON blokçeynində transferi yoxlayın. "
            "Depozit gəlməyibsə təsdiqləməyin.",
            markup,
        )

        await message.reply_text(
            "TXID adminə göndərildi. Depozit yoxlanılır."
            if sent else
            "TXID qəbul edildi, amma adminə bildiriş göndərilmədi."
        )
        return

    # Satış: bank kartının qəbulu
    if status == "sell_wait_card":
        card = (message.text or "").strip()

        if len(card) < 8 or len(card) > 100:
            await message.reply_text(
                "Zəhmət olmasa bank kartı məlumatını düzgün göndərin."
            )
            return

        target = admin_id(context)
        if not target:
            await message.reply_text(
                "Admin botda /start yazmalıdır. Sonra kart məlumatını yenidən göndərin."
            )
            return

        if not change_status(
            order_id,
            "sell_wait_card",
            "sell_payout_pending",
            bank_card=card,
        ):
            await message.reply_text(
                "Kart məlumatı artıq qəbul edilib. Təkrar göndərməyin."
            )
            return

        markup = order_buttons(
            order_id,
            ("✅ AZN göndərildi — tamamla", "complete_sell"),
        )

        sent = await notify_admin(
            context,
            f"🔵 USDT SATIŞI — AZN ödənişi gözlənilir\n\n"
            f"Sifariş: #{order_id}\n"
            f"Məbləğ: {order['amount']} USDT\n"
            f"Ödəniləcək AZN: {order['fiat_amount']}\n"
            f"Müştəri ID: {user.id}\n"
            f"Bank kartı məlumatı: {card}\n\n"
            "AZN-ni özünüz göndərin. Yalnız ödəniş tamamlandıqdan "
            "sonra sifarişi tamamla düyməsinə basın.",
            markup,
        )

        await message.reply_text(
            "Kart məlumatınız adminə göndərildi. AZN ödənişi gözlənilir."
            if sent else
            "Kart məlumatı qəbul edildi, amma adminə bildiriş getmədi."
        )
        return

    if status in ("buy_check_receipt", "sell_check_deposit"):
        await message.reply_text(
            "Sifarişiniz admin tərəfindən yoxlanılır. Zəhmət olmasa gözləyin."
        )
    elif status in ("buy_payout_pending", "sell_payout_pending"):
        await message.reply_text(
            "Sifarişiniz ödəniş mərhələsindədir. Zəhmət olmasa gözləyin."
        )
    else:
        await message.reply_text(
            "Sifarişinizin hazırkı mərhələsi gözlənilir. "
            "Yeni məlumat üçün adminin cavabını gözləyin."
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN Render Environment-də təyin edilməyib.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot başladılır...")
    app.run_polling()


if __name__ == "__main__":
    main()
