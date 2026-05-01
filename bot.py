import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
import httpx

# ── Настройки ──────────────────────────────────────────
BOT_TOKEN  = "8653199525:AAEu7bQ9-x7yMYTMRz2_IKo7HWGx0gScNUk"
API_URL    = "http://192.168.86.27:8001"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Хранение токенов пользователей (chat_id -> jwt_token)
user_tokens: dict = {}

# ── Команды ────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 Привязать аккаунт PawCare", callback_data="link")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🐾 *Добро пожаловать в PawCare Bot!*\n\n"
        "Я помогу вам:\n"
        "• Просматривать питомцев\n"
        "• Получать напоминания о процедурах\n"
        "• Узнавать о ближайших ветклиниках\n\n"
        "Для начала привяжите ваш аккаунт PawCare:",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Доступные команды:*\n\n"
        "/start — Главное меню\n"
        "/pets — Мои питомцы\n"
        "/reminders — Ближайшие напоминания\n"
        "/link — Привязать аккаунт\n"
        "/unlink — Отвязать аккаунт\n"
        "/help — Справка",
        parse_mode="Markdown"
    )

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔗 *Привязка аккаунта*\n\n"
        "1. Откройте приложение PawCare\n"
        "2. Перейдите в Профиль → Telegram\n"
        "3. Нажмите «Получить код»\n"
        "4. Отправьте мне код командой:\n\n"
        "`/code XXXXXX`",
        parse_mode="Markdown"
    )

async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username

    if not context.args:
        await update.message.reply_text(
            "❌ Укажите код: `/code XXXXXX`",
            parse_mode="Markdown"
        )
        return

    code = context.args[0].strip()

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_URL}/api/v1/telegram/link",
                json={
                    "chat_id": chat_id,
                    "username": username,
                    "link_code": code,
                }
            )
            if response.status_code == 200:
                await update.message.reply_text(
                    "✅ *Аккаунт успешно привязан!*\n\n"
                    "Теперь вы будете получать уведомления о предстоящих процедурах.\n\n"
                    "Используйте /pets чтобы посмотреть питомцев.",
                    parse_mode="Markdown"
                )
            else:
                data = response.json()
                await update.message.reply_text(
                    f"❌ Ошибка: {data.get('detail', 'Неверный код')}",
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка подключения: {e}")

async def pets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient() as client:
        try:
            # Получаем питомцев через chat_id
            response = await client.get(
                f"{API_URL}/api/v1/telegram/pets",
                params={"chat_id": chat_id}
            )
            if response.status_code == 200:
                pets = response.json()
                if not pets:
                    await update.message.reply_text(
                        "🐾 У вас пока нет питомцев.\n"
                        "Добавьте питомца в приложении PawCare!"
                    )
                    return

                text = "🐾 *Ваши питомцы:*\n\n"
                for pet in pets:
                    sex = "♂" if pet.get('sex') == 'male' else "♀" if pet.get('sex') == 'female' else ""
                    breed = pet.get('breed') or 'Порода не указана'
                    text += f"• *{pet['name']}* {sex}\n"
                    text += f"  📋 {breed}\n\n"

                await update.message.reply_text(text, parse_mode="Markdown")
            elif response.status_code == 404:
                await update.message.reply_text(
                    "❌ Аккаунт не привязан.\n"
                    "Используйте /link для привязки."
                )
            else:
                await update.message.reply_text("❌ Ошибка получения данных.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_URL}/api/v1/telegram/reminders",
                params={"chat_id": chat_id}
            )
            if response.status_code == 200:
                reminders = response.json()
                if not reminders:
                    await update.message.reply_text(
                        "✅ Нет предстоящих напоминаний!\n"
                        "Все процедуры выполнены вовремя 🎉"
                    )
                    return

                text = "⏰ *Ближайшие напоминания:*\n\n"
                for r in reminders[:10]:
                    remind_at = r.get('remind_at', '')
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(remind_at)
                        date_str = dt.strftime('%d.%m.%Y')
                    except Exception:
                        date_str = remind_at

                    emoji = {
                        'vaccination': '💉',
                        'deworming': '💊',
                        'antiparasitic': '🐛',
                        'vet_visit': '🏥',
                        'custom': '🔔',
                    }.get(r.get('record_type', ''), '🔔')

                    text += f"{emoji} *{r['title']}*\n"
                    text += f"  🐾 {r.get('pet_name', '')} · 📅 {date_str}\n\n"

                await update.message.reply_text(text, parse_mode="Markdown")
            elif response.status_code == 404:
                await update.message.reply_text(
                    "❌ Аккаунт не привязан.\n"
                    "Используйте /link для привязки."
                )
            else:
                await update.message.reply_text("❌ Ошибка получения данных.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{API_URL}/api/v1/telegram/unlink-by-chat",
                params={"chat_id": chat_id}
            )
            if response.status_code == 200:
                await update.message.reply_text(
                    "✅ Аккаунт отвязан.\n"
                    "Уведомления больше не будут приходить."
                )
            else:
                await update.message.reply_text("❌ Аккаунт не был привязан.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "link":
        await query.message.reply_text(
            "🔗 Для привязки аккаунта:\n\n"
            "1. Откройте приложение PawCare\n"
            "2. Профиль → Telegram → Получить код\n"
            "3. Отправьте: `/code XXXXXX`",
            parse_mode="Markdown"
        )

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Неизвестная команда. Используйте /help для справки."
    )

# ── Запуск ─────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("pets", pets_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("unlink", unlink_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("🤖 PawCare Bot запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()