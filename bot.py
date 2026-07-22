import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F
from supabase import create_client, Client

# ---------- Переменные окружения ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# ---------- Supabase ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logging.info("Supabase connected for analytics")
else:
    logging.warning("Supabase not configured, analytics disabled")

# ---------- Дельта (скрыта от клиента) ----------
def get_delta_from_env(key, default):
    try:
        val = os.environ.get(key)
        if val is not None:
            return float(val)
    except:
        pass
    return default

deltas = {
    "delta_rub_to_usdt": get_delta_from_env("DELTA_RUB_USDT", 0.30),
    "delta_usdt_to_rub": get_delta_from_env("DELTA_USDT_RUB", 0.20),
    "delta_cny_rub": get_delta_from_env("DELTA_CNY_RUB", 0.10),
    "delta_cny_rub_buy": get_delta_from_env("DELTA_CNY_RUB_BUY", 0.50),
}

# ---------- Кеш курсов ----------
_cache = {
    "usdt_rub": None,
    "cny_rub": None,
    "timestamp": None,
}
CACHE_TTL = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Бот ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- Функция логирования ----------
def log_event(user_id: int, username: str, action: str, amount=None, currency=None, source=None):
    if supabase is None:
        return
    try:
        data = {
            "user_id": user_id,
            "username": username or "",
            "action": action,
            "amount": amount,
            "currency": currency,
            "source": source,
        }
        supabase.table("analytics").insert(data).execute()
    except Exception as e:
        logger.error(f"Analytics log error: {e}")

# ---------- Получение курсов ----------
def get_usdt_rub_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usdt_rub"] is not None:
            return _cache["usdt_rub"]
    # 1) Rapira
    try:
        url = "https://api.rapira.net/open/market/rates"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("data", []):
                if item.get("symbol") == "USDT/RUB":
                    rate = float(item.get("askPrice", 0))
                    _cache["usdt_rub"] = rate
                    _cache["timestamp"] = now
                    logger.info(f"USDT/RUB from Rapira: {rate}")
                    return rate
    except Exception as e:
        logger.warning(f"Rapira USDT/RUB failed: {e}")
    # 2) CoinGecko (резерв)
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            rate = data["tether"]["rub"]
            _cache["usdt_rub"] = rate
            _cache["timestamp"] = now
            logger.info(f"USDT/RUB from CoinGecko: {rate}")
            return rate
    except Exception as e:
        logger.warning(f"CoinGecko USDT/RUB failed: {e}")
    return None

def get_cny_rub_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["cny_rub"] is not None:
            return _cache["cny_rub"]
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        rate = data["Valute"]["CNY"]["Value"]
        _cache["cny_rub"] = rate
        _cache["timestamp"] = now
        logger.info(f"CNY/RUB: {rate}")
        return rate
    except Exception as e:
        logger.error(f"CBR error: {e}")
        return None

def get_usdt_sell_rate():
    rate = get_usdt_rub_rate()
    return rate + deltas["delta_rub_to_usdt"] if rate else None

def get_usdt_buy_rate():
    rate = get_usdt_rub_rate()
    return rate - deltas["delta_usdt_to_rub"] if rate else None

def get_cny_sell_rate():
    rate = get_cny_rub_rate()
    return rate + deltas["delta_cny_rub"] if rate else None

def get_cny_buy_rate():
    rate = get_cny_rub_rate()
    return rate - deltas["delta_cny_rub_buy"] if rate else None

# ---------- Форматирование текста ----------
def format_main_menu():
    usdt = get_usdt_sell_rate()
    cny = get_cny_sell_rate()
    date = datetime.now().strftime("%d.%m.%Y")
    lines = [
        f"📅 {date}",
        "🏦 **OnlineMena**",
        "━━━━━━━━━━━━━━",
    ]
    if usdt is not None:
        lines += [f"💵 USDT", f"**{usdt:.2f}** ₽"]
    else:
        lines += ["💵 USDT", "⚠️ Временно недоступен"]
    lines.append("")
    if cny is not None:
        lines += [f"🇨🇳 CNY", f"**{cny:.2f}** ₽"]
    else:
        lines += ["🇨🇳 CNY", "⚠️ Временно недоступен"]
    lines += [
        "━━━━━━━━━━━━━━",
        "",
        "✅ Актуальный биржевой курс",
        "💬 Ответ менеджера: 2–5 минут",
        "━━━━━━━━━━━━━━",
        "Выберите действие 👇"
    ]
    return "\n".join(lines)

def format_course_text():
    usdt = get_usdt_sell_rate()
    cny = get_cny_sell_rate()
    date = datetime.now().strftime("%d.%m.%Y")
    lines = [
        f"📅 {date}",
        "📈 **Актуальные курсы**",
        "━━━━━━━━━━━━━━",
    ]
    if usdt is not None:
        lines += [f"💵 USDT", f"**{usdt:.2f}** ₽"]
    else:
        lines += ["💵 USDT", "⚠️ Временно недоступен"]
    lines.append("")
    if cny is not None:
        lines += [f"🇨🇳 CNY", f"**{cny:.2f}** ₽"]
    else:
        lines += ["🇨🇳 CNY", "⚠️ Временно недоступен"]
    lines += [
        "━━━━━━━━━━━━━━",
        "",
        "✅ Актуальный биржевой курс",
        "💬 Ответ менеджера: 2–5 минут"
    ]
    return "\n".join(lines)

def format_convert_result(amount_rub, usdt, cny):
    lines = [
        "💱 **Результат расчёта**",
        "━━━━━━━━━━━━━━",
        "Вы отдаёте",
        f"**{amount_rub:,.0f}** ₽",
        "━━━━━━━━━━━━━━",
        "Получаете",
        f"💵 **{usdt:.4f}** USDT" if usdt is not None else "💵 USDT: ❌",
        f"🇨🇳 **{cny:.2f}** CNY" if cny is not None else "🇨🇳 CNY: ❌",
        "━━━━━━━━━━━━━━",
        f"Курс USDT: **{get_usdt_sell_rate():.2f}** ₽" if get_usdt_sell_rate() else "",
        f"Курс CNY: **{get_cny_sell_rate():.2f}** ₽" if get_cny_sell_rate() else ""
    ]
    return "\n".join(lines)

def format_convert_usdt_result(amount_usdt, rub):
    lines = [
        "💱 **Результат расчёта**",
        "━━━━━━━━━━━━━━",
        "Вы отдаёте",
        f"💵 **{amount_usdt:.2f}** USDT",
        "━━━━━━━━━━━━━━",
        "Получаете",
        f"**{rub:,.2f}** ₽" if rub is not None else "❌",
        "━━━━━━━━━━━━━━",
        f"Курс покупки: **{get_usdt_buy_rate():.2f}** ₽" if get_usdt_buy_rate() else ""
    ]
    return "\n".join(lines)

def format_convert_cny_result(amount_cny, rub):
    lines = [
        "💱 **Результат расчёта**",
        "━━━━━━━━━━━━━━",
        "Вы отдаёте",
        f"🇨🇳 **{amount_cny:.2f}** CNY",
        "━━━━━━━━━━━━━━",
        "Получаете",
        f"**{rub:,.2f}** ₽" if rub is not None else "❌",
        "━━━━━━━━━━━━━━",
        f"Курс покупки: **{get_cny_buy_rate():.2f}** ₽" if get_cny_buy_rate() else ""
    ]
    return "\n".join(lines)

# ---------- Клавиатуры ----------
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Купить", callback_data="buy"),
         InlineKeyboardButton(text="💸 Продать", callback_data="sell")],
        [InlineKeyboardButton(text="📈 Курсы", callback_data="course"),
         InlineKeyboardButton(text="💱 Калькулятор", callback_data="convert")],
        [InlineKeyboardButton(text="📋 Услуги", callback_data="services"),
         InlineKeyboardButton(text="ℹ️ О нас", callback_data="about")]
    ])

def contact_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться со мной", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продолжить", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def services_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать мне", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def convert_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="RUB → USDT", callback_data="conv_RUB_USDT"),
         InlineKeyboardButton(text="RUB → CNY", callback_data="conv_RUB_CNY")],
        [InlineKeyboardButton(text="USDT → RUB", callback_data="conv_USDT_RUB")],
        [InlineKeyboardButton(text="CNY → RUB", callback_data="conv_CNY_RUB")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

# ---------- Обработчики команд ----------
waiting_for_rub = {}
waiting_for_usdt = {}
waiting_for_cny = {}

@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    # Получаем источник (параметр start)
    source = None
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("start="):
        source = args[1].split("=", 1)[1]
    log_event(user_id, username, "start", source=source)
    text = format_main_menu()
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("course"))
async def course_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    log_event(user_id, username, "course")
    text = format_course_text()
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

@dp.message(Command("convert_rub"))
async def convert_rub_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    log_event(user_id, username, "convert_rub")
    args = message.text.split()
    if len(args) > 1:
        try:
            amount = float(args[1].replace(',', '.'))
            if amount <= 0:
                raise ValueError
            await process_rub_conversion(message, amount)
        except:
            await message.answer("❌ Введите корректное положительное число.", reply_markup=contact_keyboard())
    else:
        await message.answer("💱 Введите сумму в рублях (например, 10000):", reply_markup=contact_keyboard())
        waiting_for_rub[user_id] = True

@dp.message(Command("convert_usdt"))
async def convert_usdt_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    log_event(user_id, username, "convert_usdt")
    args = message.text.split()
    if len(args) > 1:
        try:
            amount = float(args[1].replace(',', '.'))
            if amount <= 0:
                raise ValueError
            await process_usdt_conversion(message, amount)
        except:
            await message.answer("❌ Введите корректное положительное число.", reply_markup=contact_keyboard())
    else:
        await message.answer("💱 Введите сумму в USDT (например, 100):", reply_markup=contact_keyboard())
        waiting_for_usdt[user_id] = True

@dp.message(Command("convert_cny"))
async def convert_cny_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    log_event(user_id, username, "convert_cny")
    args = message.text.split()
    if len(args) > 1:
        try:
            amount = float(args[1].replace(',', '.'))
            if amount <= 0:
                raise ValueError
            await process_cny_conversion(message, amount)
        except:
            await message.answer("❌ Введите корректное положительное число.", reply_markup=contact_keyboard())
    else:
        await message.answer("💱 Введите сумму в CNY (например, 500):", reply_markup=contact_keyboard())
        waiting_for_cny[user_id] = True

@dp.message(Command("help"))
async def help_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    log_event(user_id, username, "help")
    await message.answer(
        "📋 **Доступные команды:**\n"
        "/start – Главное меню\n"
        "/course – Показать курсы\n"
        "/convert_rub [сумма] – Конвертировать рубли в USDT и CNY\n"
        "/convert_usdt [сумма] – Конвертировать USDT в рубли\n"
        "/convert_cny [сумма] – Конвертировать CNY в рубли\n"
        "/help – Эта справка\n\n"
        "Для связи используйте кнопку «Связаться» под любым сообщением.",
        reply_markup=contact_keyboard()
    )

# ---------- Админ-команды статистики ----------
@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("⛔ Только для администратора.")
        return
    if supabase is None:
        await message.answer("❌ Аналитика отключена (Supabase не настроен).")
        return
    # Парсим период
    args = message.text.split()
    period = "all"  # по умолчанию всё время
    if len(args) > 1:
        if args[1] == "today":
            period = "today"
        elif args[1] == "week":
            period = "week"
    await message.answer("⏳ Собираю статистику...")
    stats = build_stats(period)
    await message.answer(stats, parse_mode="Markdown")

def build_stats(period: str) -> str:
    # Определяем временной фильтр
    now = datetime.now()
    if period == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        since = now - timedelta(days=7)
    else:
        since = None  # все время

    # Запросы к Supabase
    try:
        query = supabase.table("analytics").select("*")
        if since:
            query = query.gte("created_at", since.isoformat())
        resp = query.execute()
        rows = resp.data
    except Exception as e:
        logger.error(f"Stats query error: {e}")
        return "❌ Ошибка при получении статистики."

    if not rows:
        return "📊 Нет данных за выбранный период."

    # Базовая статистика
    total_users = len(set(r["user_id"] for r in rows))
    total_actions = len(rows)

    # Источники
    sources = {}
    for r in rows:
        src = r.get("source")
        if src:
            sources[src] = sources.get(src, 0) + 1

    # Действия
    actions = {}
    for r in rows:
        a = r["action"]
        actions[a] = actions.get(a, 0) + 1

    # Конверсии
    buy_clicks = actions.get("buy_click", 0)
    sell_clicks = actions.get("sell_click", 0)
    contact_clicks = actions.get("contact_click", 0)

    # Конвертации по валютам
    conv_counts = {"RUB_USDT": 0, "RUB_CNY": 0, "USDT_RUB": 0, "CNY_RUB": 0}
    conv_sums = {"RUB_USDT": 0, "RUB_CNY": 0, "USDT_RUB": 0, "CNY_RUB": 0}
    for r in rows:
        act = r["action"]
        if act in conv_counts:
            conv_counts[act] += 1
            if r.get("amount"):
                conv_sums[act] += float(r["amount"])

    # Среднее время между /start и contact_click
    # Найдём всех пользователей, у которых есть start и contact_click
    user_times = {}
    for r in rows:
        uid = r["user_id"]
        if r["action"] == "start":
            user_times.setdefault(uid, {})["start"] = r["created_at"]
        elif r["action"] == "contact_click":
            user_times.setdefault(uid, {})["contact"] = r["created_at"]
    deltas = []
    for uid, times in user_times.items():
        if "start" in times and "contact" in times:
            start_dt = datetime.fromisoformat(times["start"].replace("Z", "+00:00"))
            contact_dt = datetime.fromisoformat(times["contact"].replace("Z", "+00:00"))
            diff = (contact_dt - start_dt).total_seconds()
            if diff > 0:
                deltas.append(diff)
    avg_time = sum(deltas) / len(deltas) if deltas else None

    # Повторные визиты: пользователи с более чем одним действием
    user_action_counts = {}
    for r in rows:
        uid = r["user_id"]
        user_action_counts[uid] = user_action_counts.get(uid, 0) + 1
    repeat_users = sum(1 for v in user_action_counts.values() if v > 1)

    # Отток: пользователи, у которых есть start, но нет никаких других действий (course, convert, buy, sell, contact)
    users_with_start = set()
    users_with_actions = set()
    for r in rows:
        uid = r["user_id"]
        if r["action"] == "start":
            users_with_start.add(uid)
        elif r["action"] not in ("start", "help"):
            users_with_actions.add(uid)
    churned = users_with_start - users_with_actions

    # Популярные валюты
    popular_currencies = {}
    for r in rows:
        if r.get("currency"):
            popular_currencies[r["currency"]] = popular_currencies.get(r["currency"], 0) + 1

    # Формируем текст
    period_label = {"today": "сегодня", "week": "за неделю", "all": "за всё время"}[period]
    text = f"📊 **Статистика {period_label}**\n\n"
    text += f"👥 Уникальных пользователей: {total_users}\n"
    text += f"📌 Всего действий: {total_actions}\n"
    text += f"🔄 Повторных визитов: {repeat_users}\n"
    text += f"📉 Отток (только /start): {len(churned)}\n\n"

    if sources:
        text += "📎 **Источники:**\n"
        for src, count in sources.items():
            text += f"  {src}: {count}\n"
        text += "\n"

    text += "📈 **Популярные команды:**\n"
    for act, count in sorted(actions.items(), key=lambda x: -x[1]):
        text += f"  {act}: {count}\n"
    text += "\n"

    text += "💱 **Конверсии:**\n"
    text += f"  Купить: {buy_clicks}\n"
    text += f"  Продать: {sell_clicks}\n"
    text += f"  Связаться: {contact_clicks}\n"
    if avg_time is not None:
        minutes = int(avg_time // 60)
        seconds = int(avg_time % 60)
        text += f"  Среднее время до связи: {minutes} мин {seconds} сек\n"
    text += "\n"

    if popular_currencies:
        text += "🪙 **Популярные валюты:**\n"
        for cur, cnt in popular_currencies.items():
            text += f"  {cur}: {cnt}\n"
        text += "\n"

    text += "💰 **Средние суммы конвертации:**\n"
    for cur, cnt in conv_counts.items():
        if cnt > 0:
            avg = conv_sums[cur] / cnt
            if cur.startswith("RUB"):
                text += f"  {cur}: {avg:,.2f} ₽\n"
            elif cur.startswith("USDT"):
                text += f"  {cur}: {avg:,.2f} USDT\n"
            elif cur.startswith("CNY"):
                text += f"  {cur}: {avg:,.2f} CNY\n"
    text += "\n"

    text += "⏱ **Последние действия (3):**\n"
    last_actions = rows[-3:] if len(rows) >= 3 else rows
    for r in reversed(last_actions):
        dt = r["created_at"][:16].replace("T", " ")
        user = r.get("username") or str(r["user_id"])
        text += f"  @{user}: {r['action']} ({dt})\n"

    return text

# ---------- Вспомогательные функции конвертации ----------
async def process_rub_conversion(message: Message, amount_rub):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    usdt = convert_rub_to_usdt(amount_rub)
    cny = convert_rub_to_cny(amount_rub)
    if usdt is None or cny is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
        return
    log_event(user_id, username, "convert_rub_done", amount=amount_rub, currency="RUB")
    text = format_convert_result(amount_rub, usdt, cny)
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

async def process_usdt_conversion(message: Message, amount_usdt):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    rub = convert_usdt_to_rub(amount_usdt)
    if rub is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
        return
    log_event(user_id, username, "convert_usdt_done", amount=amount_usdt, currency="USDT")
    text = format_convert_usdt_result(amount_usdt, rub)
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

async def process_cny_conversion(message: Message, amount_cny):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    rub = convert_cny_to_rub(amount_cny)
    if rub is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
        return
    log_event(user_id, username, "convert_cny_done", amount=amount_cny, currency="CNY")
    text = format_convert_cny_result(amount_cny, rub)
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

# ---------- Конвертеры ----------
def convert_rub_to_usdt(amount):
    rate = get_usdt_sell_rate()
    return amount / rate if rate else None

def convert_rub_to_cny(amount):
    rate = get_cny_sell_rate()
    return amount / rate if rate else None

def convert_usdt_to_rub(amount):
    rate = get_usdt_buy_rate()
    return amount * rate if rate else None

def convert_cny_to_rub(amount):
    rate = get_cny_buy_rate()
    return amount * rate if rate else None

# ---------- Обработка чисел ----------
@dp.message(F.text.regexp(r'^\d+([,.]\d+)?$'))
async def handle_number(message: Message):
    user_id = message.from_user.id
    if user_id in waiting_for_rub:
        try:
            amount = float(message.text.replace(',', '.'))
            if amount <= 0:
                raise ValueError
            del waiting_for_rub[user_id]
            await process_rub_conversion(message, amount)
        except:
            await message.answer("❌ Введите положительное число.", reply_markup=contact_keyboard())
        return
    if user_id in waiting_for_usdt:
        try:
            amount = float(message.text.replace(',', '.'))
            if amount <= 0:
                raise ValueError
            del waiting_for_usdt[user_id]
            await process_usdt_conversion(message, amount)
        except:
            await message.answer("❌ Введите положительное число.", reply_markup=contact_keyboard())
        return
    if user_id in waiting_for_cny:
        try:
            amount = float(message.text.replace(',', '.'))
            if amount <= 0:
                raise ValueError
            del waiting_for_cny[user_id]
            await process_cny_conversion(message, amount)
        except:
            await message.answer("❌ Введите положительное число.", reply_markup=contact_keyboard())
        return
    await message.answer("Используйте кнопки меню или команды /start, /course, /convert_rub, /convert_usdt, /convert_cny")

# ---------- Коллбэки ----------
@dp.callback_query(F.data == "back_to_course")
async def back_to_course_callback(callback: CallbackQuery):
    await callback.answer()
    text = format_main_menu()
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "course")
async def course_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, "course_click")
    await callback.answer()
    text = format_course_text()
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=contact_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

@dp.callback_query(F.data == "convert")
async def convert_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, "convert_menu_open")
    await callback.answer()
    try:
        await callback.message.edit_text("💱 Выберите направление:", parse_mode="Markdown", reply_markup=convert_menu_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer("💱 Выберите направление:", parse_mode="Markdown", reply_markup=convert_menu_keyboard())

@dp.callback_query(F.data.startswith("conv_"))
async def convert_pair_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, callback.data)
    await callback.answer()
    pair = callback.data.split("_")[1:]
    if len(pair) != 2:
        await callback.message.answer("Ошибка.", reply_markup=contact_keyboard())
        return
    from_cur, to_cur = pair
    if from_cur == "RUB" and to_cur == "USDT":
        await callback.message.answer("💱 Введите сумму в рублях:", reply_markup=contact_keyboard())
        waiting_for_rub[user_id] = True
    elif from_cur == "RUB" and to_cur == "CNY":
        await callback.message.answer("💱 Введите сумму в рублях:", reply_markup=contact_keyboard())
        waiting_for_rub[user_id] = True
    elif from_cur == "USDT" and to_cur == "RUB":
        await callback.message.answer("💱 Введите сумму в USDT:", reply_markup=contact_keyboard())
        waiting_for_usdt[user_id] = True
    elif from_cur == "CNY" and to_cur == "RUB":
        await callback.message.answer("💱 Введите сумму в CNY:", reply_markup=contact_keyboard())
        waiting_for_cny[user_id] = True
    else:
        await callback.message.answer("❌ Неизвестная пара.", reply_markup=contact_keyboard())

@dp.callback_query(F.data == "buy")
async def buy_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, "buy_click")
    await callback.answer()
    text = (
        "📩 Вы выбрали **покупку USDT**.\n\n"
        "Условия сделки:\n"
        "• Оплата наличными\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=action_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=action_keyboard())

@dp.callback_query(F.data == "sell")
async def sell_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, "sell_click")
    await callback.answer()
    text = (
        "📩 Вы выбрали **продажу USDT**.\n\n"
        "Условия сделки:\n"
        "• Сделка за наличные\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=action_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=action_keyboard())

@dp.callback_query(F.data == "services")
async def services_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, "services_click")
    await callback.answer()
    text = (
        "📋 **Наши услуги:**\n\n"
        "• Покупка и продажа USDT (наличные)\n"
        "• Работа с юанями (CNY)\n"
        "• Оплата товаров в Китае\n"
        "• Пополнение WeChat и Alipay\n"
        "• Переводы по Китаю\n"
        "• Оплата на юр. счета\n"
        "• Консультации по расчётам с Китаем\n\n"
        "Для подробностей напишите мне в личный чат."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=services_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=services_keyboard())

@dp.callback_query(F.data == "about")
async def about_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, "about_click")
    await callback.answer()
    text = (
        "ℹ️ **О нас**\n\n"
        "🏦 OnlineMena — это надёжный обменник USDT и CNY.\n\n"
        "✅ Актуальные биржевые курсы\n"
        "⚡ Мгновенный расчёт\n"
        "💬 Личный менеджер\n"
        "🏢 Сделки проходят в офисе\n\n"
        "Свяжитесь со мной для сделки:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=contact_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

@dp.callback_query(F.data == "refresh")
async def refresh_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    log_event(user_id, username, "refresh_click")
    await callback.answer()
    get_usdt_rub_rate(force=True)
    get_cny_rub_rate(force=True)
    text = format_main_menu()
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Edit error: {e}")
        else:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ---------- Запуск ----------
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏦 Главное меню"),
        BotCommand(command="course", description="📈 Текущие курсы"),
        BotCommand(command="convert_rub", description="💱 Конвертировать рубли → USDT/CNY"),
        BotCommand(command="convert_usdt", description="💱 Конвертировать USDT → рубли"),
        BotCommand(command="convert_cny", description="💱 Конвертировать CNY → рубли"),
        BotCommand(command="help", description="❓ Помощь"),
        BotCommand(command="stats", description="📊 Статистика (админ)")
    ])
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())