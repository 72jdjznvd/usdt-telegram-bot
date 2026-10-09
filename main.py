
import os
import asyncio
import logging
from itertools import count

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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME", "lion12355663"
).lstrip("@").lower()

BANK_CARD = os.getenv("BANK_CARD", "")
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "")

admin_chat_id = None
orders = {}
order_counter = count(1001)
user_states = {}


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 USDT alışı", callback_data="buy")],
        [InlineKeyboardButton("🔴 USDT satışı", callback_data="sell")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global admin_chat_id

    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.username and user.username.lower() == ADMIN_USERNAME:
        admin_chat_id = chat_id
        await update.message.reply_text(
            "👨‍💻 Admin panelinə xoş gəldin!\n"
            "Yeni sifarişlər bu söhbətə göndəriləcək."
        )
        return

    await update.message.reply_text(
        "Salam, mən USDT kripto ticarət botuyam.\n"
        "Sizə necə kömək edə bilərəm?\n"
        "Alış edəcəksiniz, yoxsa satış?",
        reply_markup=main_menu(),
    )


async def expire_order(order_id: int, context):
    await asyncio.sleep(300)

    order = orders.get(order_id)
    if order and order["status"] == "waiting_receipt":
        order["status"] = "cancelled"
        user_states.pop(order["user_id"], None)

        try:
            await context.bot.send_message(
                order["user_id"],
                f"⌛ {order_id} nömrəli sifarişin müddəti bitdi "
                "və sifariş ləğv edildi."
            )
        except Exception:
            log.warning("Sifarişin ləğv bildirişi göndərilmədi.")


async def choose_trade(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if query.data not in ("buy", "sell"):
        return

    user_id = query.from_user.id
    user_states[user_id] = {
        "step": "amount",
        "side": query.data,
    }

    rate = 1.70 if query.data == "buy" else 1.69
    action = "almaq" if query.data == "buy" else "satmaq"

    await query.message.reply_text(
        f"1 USDT = {rate:.2f} AZN\n"
        f"Nə qədər USDT {action} istəyirsiniz?\n"
        "Məsələn: 50"
    )


async def receive_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    global admin_chat_id

    user = update.effective_user
    chat_id = update.effective_chat.id
    state = user_states.get(user.id)

    if not state:
        await update.message.reply_text(
            "Başlamaq üçün /start yazın."
        )
        return

    step = state["step"]
    text = (update.message.text or "").strip()

    if step == "amount":
        try:
            amount = float(text.replace(",", "."))
            if not 0 < amount <= 100000:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "Düzgün USDT məbləği yazın. Məsələn: 50"
            )
            return

        side = state["side"]
        rate = 1.70 if side == "buy" else 1.69
        total = amount * rate

        order_id = next(order_counter)
        orders[order_id] = {
            "user_id": user.id,
            "username": user.username or "yoxdur",
            "side": side,
            "amount": amount,
            "total": round(total, 2),
            "status": "waiting_receipt",
        }

        state["step"] = "receipt"
        state["order_id"] = order_id

        if side == "buy":
            if not BANK_CARD:
                await update.message.reply_text(
                    "Alış müvəqqəti mümkün deyil. "
                    "Admin bank kartı məlumatlarını qurmalıdır."
                )
                orders[order_id]["status"] = "cancelled"
                user_states.pop(user.id, None)
                return

            details = (
                f"Ödəniş məbləği: {total:.2f} AZN\n"
                f"Bank kartı: {BANK_CARD}\n\n"
                "5 dəqiqə ərzində ödənişi edib qəbzin "
                "şəklini göndərin."
            )
        else:
            if not USDT_ADDRESS:
                await update.message.reply_text(
                    "Satış müvəqqəti mümkün deyil. "
                    "Admin USDT ünvanını qurmalıdır."
                )
                orders[order_id]["status"] = "cancelled"
                user_states.pop(user.id, None)
                return

            details = (
                f"Göndəriləcək məbləğ: {amount:g} USDT\n"
                f"Şəbəkə: TRC-20\n"
                f"USDT ünvanı: {USDT_ADDRESS}\n\n"
                "Düzgün şəbəkədən köçürmə edin və "
                "5 dəqiqə ərzində qəbzin şəklini göndərin."
            )

        await update.message.reply_text(
            f"📋 Sifariş №{order_id}\n"
            f"Məzənnə: {rate:.2f} AZN\n"
            f"Ümumi məbləğ: {total:.2f} AZN\n\n"
            f"{details}"
        )

        if admin_chat_id:
            await context.bot.send_message(
                admin_chat_id,
                f"🆕 Yeni sifariş №{order_id}\n"
                f"Növ: {'USDT alışı' if side == 'buy' else 'USDT satışı'}\n"
                f"Müştəri ID: {user.id}\n"
                f"USDT: {amount:g}\n"
                f"Məbləğ: {total:.2f} AZN\n"
                "Qəbz gözlənilir."
            )

        context.application.create_task(
            expire_order(order_id, context)
        )
        return

    if step == "receipt":
        await update.message.reply_text(
            "Zəhmət olmasa, ödəniş qəbzinin şəklini göndərin."
        )
        return

    if step == "wallet":
        if not text.startswith("T") or len(text) != 34:
            await update.message.reply_text(
                "TRC-20 ünvanı adətən T ilə başlayır "
                "və 34 simvoldan ibarət olur. Ünvanı yoxlayın."
            )
            return

        order_id = state["order_id"]
        order = orders[order_id]
        order["wallet"] = text
        order["status"] = "awaiting_manual_transfer"
        user_states.pop(user.id, None)

        await update.message.reply_text(
            "✅ Pul kisəsi ünvanınız qəbul edildi.\n"
            "Köçürmə admin tərəfindən tamamlanacaq. "
            "USDT faktiki göndərildikdən sonra "
            "əməliyyat təsdiqlənəcək."
        )

        if admin_chat_id:
            await context.bot.send_message(
                admin_chat_id,
                f"📥 Sifariş №{order_id}: müştəri USDT "
                f"ünvanını təqdim etdi.\n"
                f"Ünvan: {text}\n"
                "Köçürməni ayrıca yoxlayıb tamamlayın."
            )
        return

    if step == "bank_card":
        order_id = state["order_id"]
        order = orders[order_id]
        order["status"] = "awaiting_manual_payout"
        user_states.pop(user.id, None)

        await update.message.reply_text(
            "💳 Bank məlumatınız qəbul edildi. "
            "Ödəniş admin tərəfindən yoxlanıb göndəriləcək. "
            "Pul faktiki köçürüləndə sifariş tamamlanacaq."
        )

        if admin_chat_id:
            await context.bot.send_message(
                admin_chat_id,
                f"💳 Sifariş №{order_id}: müştəri bank "
                f"məlumatını təqdim etdi.\n"
                f"Müştəri ID: {user.id}\n"
                f"Məlumat: {text}\n"
                "Bank məlumatını təhlükəsiz kanalda yoxlayın "
                "və ödənişi əl ilə həyata keçirin."
            )
        return


async def receive_receipt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    state = user_states.get(user.id)

    if not state or state.get("step") != "receipt":
        await update.message.reply_text(
            "Hazırda qəbz gözləyən sifarişiniz yoxdur."
        )
        return

    order_id = state["order_id"]
    order = orders.get(order_id)

    if not order or order["status"] != "waiting_receipt":
        await update.message.reply_text(
            "Bu sifariş artıq aktiv deyil."
        )
        return

    order["status"] = "checking_receipt"

    await update.message.reply_text(
        "🧾 Ödəniş qəbziniz yoxlanılır. "
        "Zəhmət olmasa, gözləyin."
    )

    if not admin_chat_id:
        await update.message.reply_text(
            "Admin hələ botu işə salmayıb. "
            "Zəhmət olmasa, bir qədər sonra yenidən əlaqə saxlayın."
        )
        order["status"] = "waiting_admin"
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Təsdiqlə",
                callback_data=f"approve:{order_id}"
            ),
            InlineKeyboardButton(
                "❌ Rədd et",
                callback_data=f"reject:{order_id}"
            ),
        ]
    ])

    caption = (
        f"🧾 Qəbz yoxlanışı — sifariş №{order_id}\n"
        f"Növ: {'USDT alışı' if order['side'] == 'buy' else 'USDT satışı'}\n"
        f"Müştəri ID: {user.id}\n"
        f"USDT: {order['amount']:g}\n"
        f"Məbləğ: {order['total']:.2f} AZN\n\n"
        "Əməliyyatı bankda və ya blokçeyndə yoxlayın. "
        "Təkcə qəbz şəklinə əsasən təsdiqləməyin."
    )

    try:
        photo = update.message.photo[-1].file_id
        await context.bot.send_photo(
            chat_id=admin_chat_id,
            photo=photo,
            caption=caption,
            reply_markup=keyboard,
        )
    except Exception:
        order["status"] = "waiting_admin"
        await update.message.reply_text(
            "Qəbz adminə çatdırılmadı. "
            "Adminlə əlaqə saxlayın."
        )
        return


async def admin_decision(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if not query.from_user.username or (
        query.from_user.username.lower() != ADMIN_USERNAME
    ):
        await query.answer(
            "Bu əməliyyat yalnız admin üçündür.",
            show_alert=True,
        )
        return

    action, order_text = query.data.split(":")
    order_id = int(order_text)
    order = orders.get(order_id)

    if not order or order["status"] not in (
        "checking_receipt", "waiting_admin"
    ):
        await query.message.reply_text(
            "Bu sifariş artıq yoxlanılıb və ya aktiv deyil."
        )
        return

    if action == "reject":
        order["status"] = "rejected"
        user_states.pop(order["user_id"], None)

        await context.bot.send_message(
            order["user_id"],
            f"❌ Sifariş №{order_id} rədd edildi. "
            "Səbəbi öyrənmək üçün adminlə əlaqə saxlayın."
        )
        await query.edit_message_reply_markup(
            reply_markup=None
        )
        await query.message.reply_text(
            f"Sifariş №{order_id} rədd edildi."
        )
        return

    order["status"] = "approved"

    if order["side"] == "buy":
        user_states[order["user_id"]] = {
            "step": "wallet",
            "order_id": order_id,
        }
        message = (
            f"✅ Sifariş №{order_id}: ödəniş admin tərəfindən "
            "təsdiqləndi.\nİndi USDT TRC-20 pul kisəsi "
            "ünvanınızı göndərin."
        )
    else:
        user_states[order["user_id"]] = {
            "step": "bank_card",
            "order_id": order_id,
        }
        message = (
            f"✅ Sifariş №{order_id}: USDT köçürməniz "
            "admin tərəfindən təsdiqləndi.\n"
            "AZN ödənişi üçün bank kartı məlumatınızı göndərin."
        )

    await context.bot.send_message(order["user_id"], message)
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"Sifariş №{order_id} təsdiqləndi."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "Mərhələ dayandırıldı. Yeni sifariş üçün /start yazın.",
        reply_markup=main_menu(),
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN mühiti dəyişəni təyin edilməyib.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(
        CallbackQueryHandler(choose_trade, pattern=r"^(buy|sell)$")
    )
    app.add_handler(
        CallbackQueryHandler(
            admin_decision, pattern=r"^(approve|reject):\d+$"
        )
    )
    app.add_handler(
        MessageHandler(filters.PHOTO, receive_receipt)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message)
    )

    app.run_polling()


if __name__ == "__main__":
    main()

