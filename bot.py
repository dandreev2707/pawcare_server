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
PROXY_URL  = os.getenv("PROXY_URL", None)

# Часовой пояс для отображения (Москва UTC+3)
MSK_OFFSET = datetime.timezone(datetime.timedelta(hours=3))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Хранение токенов пользователей (chat_id -> jwt_token)
user_tokens: dict = {}

# Дедупликация уведомлений за час: {reminder_id} — сбрасывается каждые сутки
_sent_hour_before: set = set()
_sent_hour_before_date: datetime.date = datetime.date.today()


def _format_remind_time(remind_at: str) -> str:
    """Парсит UTC ISO строку и возвращает московское время в формате HH:MM."""
    if 'T' not in remind_at:
        return ''
    try:
        s = remind_at.strip().replace('Z', '+00:00')
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt_msk = dt.astimezone(MSK_OFFSET)
        return f" в {dt_msk.strftime('%H:%M')}"
    except Exception:
        return ''


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
        "• /health — медкарта питомца\n"
        "• /pdf — скачать медкарту в PDF\n"
        "• /vets <город> — ветклиники рядом\n\n"
        "Для начала привяжите ваш аккаунт PawCare:",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Доступные команды:*\n\n"
        "/login — Войти в приложение PawCare\n"
        "/pets — Мои питомцы\n"
        "/remind — Ближайшие напоминания\n"
        "/health — Медкарта питомца\n"
        "/pdf — Скачать медкарту в PDF\n"
        "/vets <город> — Ветклиники в городе\n"
        "/link — Привязать аккаунт\n"
        "/unlink — Отвязать аккаунт\n"
        "/help — Справка",
        parse_mode="Markdown"
    )

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерирует одноразовый код для входа в приложение PawCare."""
    chat_id    = str(update.effective_chat.id)
    first_name = update.effective_user.first_name or ""
    username   = update.effective_user.username or ""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{API_URL}/api/v1/telegram/generate-login-code",
                json={
                    "chat_id":    chat_id,
                    "bot_secret": os.getenv("BOT_SECRET", ""),
                    "first_name": first_name,
                    "username":   username,
                },
            )
            if resp.status_code == 200:
                code = resp.json()["code"]
                await update.message.reply_text(
                    f"🔑 *Код для входа в PawCare:*\n\n"
                    f"`{code}`\n\n"
                    f"Введите этот код в приложении PawCare на экране входа.\n"
                    f"⏱ Код действителен *15 минут*.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ Ошибка генерации кода. Попробуйте позже.")
        except Exception as e:
            logging.error(f"login_command error: {e}")
            await update.message.reply_text("❌ Сервер недоступен. Попробуйте позже.")


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
                    time_str = _format_remind_time(remind_at)
                    try:
                        s = remind_at.strip().replace('Z', '+00:00')
                        dt = datetime.datetime.fromisoformat(s)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                        dt_msk = dt.astimezone(MSK_OFFSET)
                        date_str = dt_msk.strftime('%d.%m.%Y')
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
                    text += f"  🐾 {r.get('pet_name', '')} · 📅 {date_str}{time_str}\n\n"

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


async def _show_pet_keyboard(update: Update, chat_id: str, callback_prefix: str, prompt: str):
    """Загружает список питомцев и показывает инлайн-кнопки."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                f"{API_URL}/api/v1/telegram/pets",
                params={"chat_id": chat_id}
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
            return

    if response.status_code == 404:
        await update.message.reply_text("❌ Аккаунт не привязан. Используйте /link.")
        return
    if response.status_code != 200:
        await update.message.reply_text("❌ Ошибка получения данных.")
        return

    pets = response.json()
    if not pets:
        await update.message.reply_text(
            "🐾 У вас пока нет питомцев. Добавьте питомца в приложении PawCare!"
        )
        return

    buttons = [
        [InlineKeyboardButton(
            f"{'♂' if p.get('sex') == 'male' else '♀' if p.get('sex') == 'female' else '🐾'} {p['name']}",
            callback_data=f"{callback_prefix}{p['id']}"
        )]
        for p in pets
    ]
    await update.message.reply_text(
        prompt,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await _show_pet_keyboard(
        update, chat_id,
        callback_prefix="health_",
        prompt="🏥 *Медкарта питомца*\nВыберите питомца:",
    )


async def pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await _show_pet_keyboard(
        update, chat_id,
        callback_prefix="pdf_",
        prompt="📄 *Скачать медкарту PDF*\nВыберите питомца:",
    )


async def _send_health_records(query, chat_id: str, pet_id: str):
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            response = await client.get(
                f"{API_URL}/api/v1/telegram/health-by-id",
                params={"chat_id": chat_id, "pet_id": pet_id}
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Ошибка: {e}")
            return

    if response.status_code == 403:
        await query.message.reply_text("❌ Аккаунт не привязан. Используйте /link.")
        return
    if response.status_code == 404:
        await query.message.reply_text("❌ Питомец не найден.")
        return
    if response.status_code != 200:
        await query.message.reply_text("❌ Ошибка получения данных.")
        return

    data = response.json()
    records = data.get("records", [])
    name = data.get("pet_name", "Питомец")

    if not records:
        await query.message.reply_text(
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
        text += f"_...и ещё {len(records) - 10} записей_\n\n"

    # Кнопка скачать PDF
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Скачать PDF", callback_data=f"pdf_{pet_id}")]
    ])
    await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def _send_health_pdf(query, chat_id: str, pet_id: str):
    await query.message.reply_text("⏳ Формирую PDF...")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                f"{API_URL}/api/v1/telegram/pdf",
                params={"chat_id": chat_id, "pet_id": pet_id}
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Ошибка: {e}")
            return

    if response.status_code == 403:
        await query.message.reply_text("❌ Аккаунт не привязан. Используйте /link.")
        return
    if response.status_code == 404:
        await query.message.reply_text("❌ Питомец не найден.")
        return
    if response.status_code != 200:
        await query.message.reply_text(f"❌ Не удалось создать PDF. Код: {response.status_code}\n{response.text[:200]}")
        return

    cd = response.headers.get("content-disposition", "")
    filename = "health.pdf"
    if 'filename="' in cd:
        filename = cd.split('filename="')[1].rstrip('"')

    await query.message.reply_document(
        document=response.content,
        filename=filename,
        caption="📄 Медицинская карта",
    )


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
    data = query.data
    chat_id = str(query.message.chat_id)

    if data == "link":
        await query.message.reply_text(
            "🔗 Для привязки аккаунта:\n\n"
            "1. Откройте приложение PawCare\n"
            "2. Профиль → Telegram → Получить код\n"
            "3. Отправьте: `/code XXXXXX`",
            parse_mode="Markdown"
        )
    elif data.startswith("health_"):
        pet_id = data[len("health_"):]
        await _send_health_records(query, chat_id, pet_id)
    elif data.startswith("pdf_"):
        pet_id = data[len("pdf_"):]
        await _send_health_pdf(query, chat_id, pet_id)

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
    'chronic_disease': '❤️',
    'medication': '💊',
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
        time_str = _format_remind_time(notif.get('remind_at', ''))
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


async def send_hour_before_notifications(context: ContextTypes.DEFAULT_TYPE):
    global _sent_hour_before, _sent_hour_before_date

    # Сбрасываем набор отправленных в начале нового дня
    today = datetime.date.today()
    if today != _sent_hour_before_date:
        _sent_hour_before = set()
        _sent_hour_before_date = today

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_URL}/api/v1/telegram/due-in-hour", timeout=10
            )
            if response.status_code != 200:
                return
            notifications = response.json()
        except Exception as e:
            logging.error(f"Ошибка получения уведомлений (за час): {e}")
            return

    for notif in notifications:
        reminder_id = notif.get('id')
        if reminder_id and reminder_id in _sent_hour_before:
            continue

        emoji = EMOJI_MAP.get(notif.get('record_type', ''), '🔔')
        time_str = _format_remind_time(notif.get('remind_at', ''))
        text = (
            f"{emoji} *Напоминание через 1 час!*\n\n"
            f"🐾 {notif['pet_name']}\n"
            f"📋 {notif['title']}{time_str}"
        )
        try:
            await context.bot.send_message(
                chat_id=notif['chat_id'],
                text=text,
                parse_mode="Markdown",
            )
            if reminder_id:
                _sent_hour_before.add(reminder_id)
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление (за час) {notif['chat_id']}: {e}")


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
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("pets", pets_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("pdf", pdf_command))
    app.add_handler(CommandHandler("vets", vets_command))
    app.add_handler(CommandHandler("unlink", unlink_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Ежедневные уведомления в 9:00 по московскому времени (= 06:00 UTC)
    app.job_queue.run_daily(
        send_daily_notifications,
        time=datetime.time(6, 0, tzinfo=datetime.timezone.utc),
    )

    # Уведомления за час до напоминания (проверка каждые 5 минут)
    app.job_queue.run_repeating(
        send_hour_before_notifications,
        interval=300,
        first=10,
    )

    print("🤖 PawCare Bot запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
