import asyncio
import sys
import logging
import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# На Windows httpx требует SelectorEventLoop (по умолчанию стоит ProactorEventLoop)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from telegram.request import HTTPXRequest
import httpx

# ── Настройки ──────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN")
API_URL    = os.getenv("API_URL", "http://localhost:8001")

# Прокси для доступа к api.telegram.org (нужен если Telegram заблокирован)
# Формат: "socks5://host:port" или "http://host:port"
# Можно задать через .env: PROXY_URL=socks5://127.0.0.1:1080
PROXY_URL  = os.getenv("PROXY_URL", None)

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
        "• /pets — просмотреть питомцев\n"
        "• /remind — ближайшие напоминания\n"
        "• /health <кличка> — медкарта питомца\n"
        "• /vets <город> — ветклиники рядом\n\n"
        "Для начала привяжите ваш аккаунт PawCare:",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Доступные команды:*\n\n"
        "/pets — Мои питомцы\n"
        "/remind — Ближайшие напоминания\n"
        "/health <кличка> — Медкарта питомца\n"
        "/vets <город> — Ветклиники в городе\n"
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

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient(timeout=15) as client:
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
                        dt = datetime.datetime.fromisoformat(remind_at)
                        date_str = dt.strftime('%d.%m.%Y')
                        time_str = dt.strftime('%H:%M') if 'T' in remind_at else ''
                    except Exception:
                        date_str = remind_at
                        time_str = ''

                    emoji = {
                        'vaccination': '💉',
                        'deworming': '💊',
                        'antiparasitic': '🐛',
                        'vet_visit': '🏥',
                        'custom': '🔔',
                    }.get(r.get('record_type', ''), '🔔')

                    text += f"{emoji} *{r['title']}*\n"
                    text += f"  🐾 {r.get('pet_name', '')} · 📅 {date_str} {time_str}\n\n"

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


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text(
            "🏥 Укажите кличку питомца:\n`/health Барсик`",
            parse_mode="Markdown"
        )
        return

    pet_name = " ".join(context.args).strip()

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            response = await client.get(
                f"{API_URL}/api/v1/telegram/health",
                params={"chat_id": chat_id, "pet_name": pet_name}
            )
            if response.status_code == 200:
                data = response.json()
                records = data.get("records", [])
                name = data.get("pet_name", pet_name)

                if not records:
                    await update.message.reply_text(
                        f"📋 У *{name}* пока нет медицинских записей.",
                        parse_mode="Markdown"
                    )
                    return

                type_emoji = {
                    'vaccination': '💉',
                    'deworming': '💊',
                    'antiparasitic': '🐛',
                    'vet_visit': '🏥',
                    'chronic': '🩺',
                    'medication': '💊',
                }
                text = f"🏥 *Медкарта: {name}*\n\n"
                for r in records[:10]:
                    emoji = type_emoji.get(r.get('record_type', ''), '📋')
                    text += f"{emoji} *{r['title']}*\n"
                    text += f"  📅 {r.get('record_date', '')}"
                    if r.get('next_date'):
                        text += f" → {r['next_date']}"
                    text += "\n"
                    if r.get('description'):
                        text += f"  _{r['description']}_\n"
                    text += "\n"

                if len(records) > 10:
                    text += f"_...и ещё {len(records) - 10} записей_"

                await update.message.reply_text(text, parse_mode="Markdown")
            elif response.status_code == 404:
                await update.message.reply_text(
                    f"❌ Питомец с кличкой *{pet_name}* не найден.\n"
                    "Проверьте написание или используйте /pets.",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Аккаунт не привязан. Используйте /link.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")


async def vets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🗺 Укажите город:\n`/vets Москва`",
            parse_mode="Markdown"
        )
        return

    city = " ".join(context.args).strip()

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            # Геокодируем город через Nominatim
            geo = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": "PawCareBot/1.0"}
            )
            if geo.status_code != 200 or not geo.json():
                await update.message.reply_text(f"❌ Город «{city}» не найден.")
                return

            loc = geo.json()[0]
            lat, lon = float(loc["lat"]), float(loc["lon"])

            # Ищем ветклиники через наш API
            resp = await client.get(
                f"{API_URL}/api/v1/map/vets-public",
                params={"lat": lat, "lon": lon}
            )
            if resp.status_code != 200:
                await update.message.reply_text("❌ Не удалось получить список клиник.")
                return

            clinics = resp.json()
            if not clinics:
                await update.message.reply_text(
                    f"🏥 Ветклиники в городе *{city}* не найдены.",
                    parse_mode="Markdown"
                )
                return

            text = f"🏥 *Ветклиники в городе {city}:*\n\n"
            for c in clinics[:8]:
                name = c.get('name', 'Без названия')
                address = c.get('address', '')
                text += f"• *{name}*\n"
                if address:
                    text += f"  📍 {address}\n"
                text += "\n"

            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.delete(
                f"{API_URL}/api/v1/telegram/unlink-by-chat",
                params={"chat_id": chat_id}
            )
            text = ("✅ Аккаунт отвязан.\nУведомления больше не будут приходить."
                    if response.status_code == 200 else "❌ Аккаунт не был привязан.")
        except Exception:
            text = "❌ Ошибка подключения к серверу."
    try:
        await update.message.reply_text(text)
    except Exception:
        pass

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

# ── Авто-уведомления ───────────────────────────────────

EMOJI_MAP = {
    'vaccination': '💉',
    'deworming': '💊',
    'antiparasitic': '🐛',
    'vet_visit': '🏥',
    'custom': '🔔',
}

async def send_daily_notifications(context: ContextTypes.DEFAULT_TYPE):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_URL}/api/v1/telegram/all-due", timeout=10
            )
            if response.status_code != 200:
                return
            notifications = response.json()
        except Exception as e:
            logging.error(f"Ошибка получения уведомлений: {e}")
            return

    for notif in notifications:
        emoji = EMOJI_MAP.get(notif.get('record_type', ''), '🔔')
        remind_at = notif.get('remind_at', '')
        time_str = ''
        try:
            if 'T' in remind_at:
                dt = datetime.datetime.fromisoformat(remind_at)
                time_str = f" в {dt.strftime('%H:%M')}"
        except Exception:
            pass
        text = (
            f"{emoji} *Напоминание на сегодня!*\n\n"
            f"🐾 {notif['pet_name']}\n"
            f"📋 {notif['title']}{time_str}"
        )
        try:
            await context.bot.send_message(
                chat_id=notif['chat_id'],
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление {notif['chat_id']}: {e}")


# ── Запуск ─────────────────────────────────────────────

def main():
    request = HTTPXRequest(
        http_version="1.1",
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
    )
    if PROXY_URL:
        builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
    app = builder.build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("pets", pets_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("vets", vets_command))
    app.add_handler(CommandHandler("unlink", unlink_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Ежедневные уведомления в 9:00 утра
    app.job_queue.run_daily(
        send_daily_notifications,
        time=datetime.time(9, 0, tzinfo=datetime.timezone.utc),
    )

    print("🤖 PawCare Bot запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()