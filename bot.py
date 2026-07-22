import asyncio
import logging
import os
import time
from datetime import datetime

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F

# ---------- Переменные окружения ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

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
    "usdt_cny": None,
    "timestamp": None,
}
CACHE_TTL = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Бот ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- Получение курсов ----------
def get_usdt_rub_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usdt_rub"] is not None:
            return _cache["usdt_rub"]
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
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            rate = resp.json()["tether"]["rub"]
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
        logger.info(f"CNY/RUB from CBR: {rate}")
        return rate
    except Exception as e:
        logger.error(f"CBR error: {e}")
        return None

def get_usdt_cny_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usdt_cny"] is not None:
            return _cache["usdt_cny"]
    try:
        url = "https://api.frankfurter.app/latest?from=USD&to=CNY"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            rate = resp.json()["rates"]["CNY"]
            _cache["usdt_cny"] = rate
            _cache["timestamp"] = now
            logger.info(f"USDT/CNY from Frankfurter: {rate}")
            return rate
    except Exception as e:
        logger.warning(f"Frankfurter USDT/CNY failed: {e}")
    try:
        url = "https://api.exchangerate.host/convert?from=USD&to=CNY"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                rate = data["result"]
                _cache["usdt_cny"] = rate
                _cache["timestamp"] = now
                logger.info(f"USDT/CNY from exchangerate.host: {rate}")
                return rate
    except Exception as e:
        logger.warning(f"exchangerate.host USDT/CNY failed: {e}")
    return None

# ---------- Курсы для операций ----------
def get_usdt_sell_rate():
    rate = get_usdt_rub_rate()
    return rate + deltas["delta_rub_to_usdt"] if rate else None

def get_usdt_buy_rate():
    rate = get_usdt_rub_rate()
    return rate - deltas["delta_usdt_to_rub"] if rate else None

def get_cny_sell_rate():
    usdt_rub = get_usdt_rub_rate()
    usdt_cny = get_usdt_cny_rate()
    if usdt_rub is not None and usdt_cny is not None and usdt_cny != 0:
        rate = (usdt_rub + deltas["delta_rub_to_usdt"]) / (usdt_cny - deltas["delta_cny_rub"])
        logger.info(f"CNY sell rate (cross): {rate:.4f}")
        return rate
    direct = get_cny_rub_rate()
    if direct is not None:
        return direct + deltas["delta_cny_rub"]
    return None

def get_cny_buy_rate():
    usdt_rub = get_usdt_rub_rate()
    usdt_cny = get_usdt_cny_rate()
    if usdt_rub is not None and usdt_cny is not None and usdt_cny != 0:
        rate = (usdt_rub - deltas["delta_usdt_to_rub"]) / (usdt_cny + deltas["delta_cny_rub_buy"])
        if rate <= 0:
            logger.warning("Negative buy rate, using fallback")
            direct = get_cny_rub_rate()
            if direct is not None:
                return direct - deltas["delta_cny_rub_buy"]
            return None
        logger.info(f"CNY buy rate (cross): {rate:.4f}")
        return rate
    direct = get_cny_rub_rate()
    if direct is not None:
        return direct - deltas["delta_cny_rub_buy"]
    return None

# ---------- Форматирование текста ----------
def format_main_menu():
    usdt = get_usdt_sell_rate()
    cny = get_cny_sell_rate()
    usdt_cny = get_usdt_cny_rate()
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
    lines.append("")
    if usdt_cny is not None:
        lines += [f"🇺🇸 USDT/CNY", f"**{usdt_cny:.2f}** ¥"]
    else:
        lines += ["🇺🇸 USDT/CNY", "⚠️ Временно недоступен"]
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
    usdt_cny = get_usdt_cny_rate()
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
    lines.append("")
    if usdt_cny is not None:
        lines += [f"🇺🇸 USDT/CNY", f"**{usdt_cny:.2f}** ¥"]
    else:
        lines += ["🇺🇸 USDT/CNY", "⚠️ Временно недоступен"]
    lines += [
        "━━━━━━━━━━━━━━",
        "",
        "✅ Актуальный биржевой курс",
        "💬 Ответ менеджера: 2–5 минут"
    ]
    return "\n".join(lines)

def format_convert_rub_result(amount_rub, usdt, cny):
    sell_usdt = get_usdt_sell_rate()
    sell_cny = get_cny_sell_rate()
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
        f"Курс продажи USDT: **{sell_usdt:.2f}** ₽" if sell_usdt else "",
        f"Курс продажи CNY: **{sell_cny:.2f}** ₽" if sell_cny else ""
    ]
    return "\n".join(lines)

def format_convert_usdt_result(amount_usdt, rub):
    buy_usdt = get_usdt_buy_rate()
    lines = [
        "💱 **Результат расчёта**",
        "━━━━━━━━━━━━━━",
        "Вы отдаёте",
        f"💵 **{amount_usdt:.2f}** USDT",
        "━━━━━━━━━━━━━━",
        "Получаете",
        f"**{rub:,.2f}** ₽" if rub is not None else "❌",
        "━━━━━━━━━━━━━━",
        f"Курс покупки USDT: **{buy_usdt:.2f}** ₽" if buy_usdt else ""
    ]
    return "\n".join(lines)

def format_convert_cny_result(amount_cny, rub):
    buy_cny = get_cny_buy_rate()
    lines = [
        "💱 **Результат расчёта**",
        "━━━━━━━━━━━━━━",
        "Вы отдаёте",
        f"🇨🇳 **{amount_cny:.2f}** CNY",
        "━━━━━━━━━━━━━━",
        "Получаете",
        f"**{rub:,.2f}** ₽" if rub is not None else "❌",
        "━━━━━━━━━━━━━━",
        f"Курс покупки CNY: **{buy_cny:.2f}** ₽" if buy_cny else ""
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
    text = format_main_menu()
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("course"))
async def course_cmd(message: Message):
    text = format_course_text()
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

@dp.message(Command("convert_rub"))
async def convert_rub_cmd(message: Message):
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
        waiting_for_rub[message.from_user.id] = True

@dp.message(Command("convert_usdt"))
async def convert_usdt_cmd(message: Message):
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
        waiting_for_usdt[message.from_user.id] = True

@dp.message(Command("convert_cny"))
async def convert_cny_cmd(message: Message):
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
        waiting_for_cny[message.from_user.id] = True

@dp.message(Command("help"))
async def help_cmd(message: Message):
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

# ---------- Конвертация ----------
async def process_rub_conversion(message: Message, amount_rub):
    usdt = convert_rub_to_usdt(amount_rub)
    cny = convert_rub_to_cny(amount_rub)
    if usdt is None or cny is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
        return
    text = format_convert_rub_result(amount_rub, usdt, cny)
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

async def process_usdt_conversion(message: Message, amount_usdt):
    rub = convert_usdt_to_rub(amount_usdt)
    if rub is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
        return
    text = format_convert_usdt_result(amount_usdt, rub)
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

async def process_cny_conversion(message: Message, amount_cny):
    rub = convert_cny_to_rub(amount_cny)
    if rub is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
        return
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
            return
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
            return
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
            return
        except:
            await message.answer("❌ Введите положительное число.", reply_markup=contact_keyboard())
            return
    await message.answer("Используйте кнопки меню или команды /start, /course, /convert_rub, /convert_usdt, /convert_cny")

# ---------- Коллбэки ----------
@dp.callback_query(F.data == "back_to_course")
async def back_to_course_callback(callback: CallbackQuery):
    await callback.answer()
    text = format_main_menu()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "course")
async def course_callback(callback: CallbackQuery):
    await callback.answer()
    text = format_course_text()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

@dp.callback_query(F.data == "convert")
async def convert_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("💱 Выберите направление:", parse_mode="Markdown", reply_markup=convert_menu_keyboard())

@dp.callback_query(F.data.startswith("conv_"))
async def convert_pair_callback(callback: CallbackQuery):
    await callback.answer()
    pair = callback.data.split("_")[1:]
    if len(pair) != 2:
        await callback.message.answer("Ошибка.", reply_markup=contact_keyboard())
        return
    from_cur, to_cur = pair
    if from_cur == "RUB" and to_cur == "USDT":
        await callback.message.answer("💱 Введите сумму в рублях:", reply_markup=contact_keyboard())
        waiting_for_rub[callback.from_user.id] = True
    elif from_cur == "RUB" and to_cur == "CNY":
        await callback.message.answer("💱 Введите сумму в рублях:", reply_markup=contact_keyboard())
        waiting_for_rub[callback.from_user.id] = True
    elif from_cur == "USDT" and to_cur == "RUB":
        await callback.message.answer("💱 Введите сумму в USDT:", reply_markup=contact_keyboard())
        waiting_for_usdt[callback.from_user.id] = True
    elif from_cur == "CNY" and to_cur == "RUB":
        await callback.message.answer("💱 Введите сумму в CNY:", reply_markup=contact_keyboard())
        waiting_for_cny[callback.from_user.id] = True
    else:
        await callback.message.answer("❌ Неизвестная пара.", reply_markup=contact_keyboard())

@dp.callback_query(F.data == "buy")
async def buy_callback(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📩 Вы выбрали **покупку USDT**.\n\n"
        "Условия сделки:\n"
        "• Оплата наличными\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=action_keyboard())

@dp.callback_query(F.data == "sell")
async def sell_callback(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📩 Вы выбрали **продажу USDT**.\n\n"
        "Условия сделки:\n"
        "• Сделка за наличные\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=action_keyboard())

@dp.callback_query(F.data == "services")
async def services_callback(callback: CallbackQuery):
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
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=services_keyboard())

@dp.callback_query(F.data == "about")
async def about_callback(callback: CallbackQuery):
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
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

@dp.callback_query(F.data == "refresh")
async def refresh_callback(callback: CallbackQuery):
    await callback.answer()
    get_usdt_rub_rate(force=True)
    get_cny_rub_rate(force=True)
    get_usdt_cny_rate(force=True)
    text = format_main_menu()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ---------- Запуск ----------
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏦 Главное меню"),
        BotCommand(command="course", description="📈 Текущие курсы"),
        BotCommand(command="convert_rub", description="💱 Конвертировать рубли → USDT/CNY"),
        BotCommand(command="convert_usdt", description="💱 Конвертировать USDT → рубли"),
        BotCommand(command="convert_cny", description="💱 Конвертировать CNY → рубли"),
        BotCommand(command="help", description="❓ Помощь")
    ])
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())