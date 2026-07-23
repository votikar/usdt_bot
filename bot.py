import asyncio
import logging
import os
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

# ---------- Форматирование ----------
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

def format_purchase_result(amount, currency, rate, total_rub):
    lines = [
        "💱 **Стоимость покупки**",
        "━━━━━━━━━━━━━━",
        f"Вы хотите получить: **{amount:,.2f} {currency}**",
        f"Курс: **{rate:.2f}** ₽ за 1 {currency}",
        "━━━━━━━━━━━━━━━━━━━",
        f"💰 **Итого: {total_rub:,.2f} ₽**"
    ]
    return "\n".join(lines)

def format_sale_result(amount, currency, rate, total_rub):
    lines = [
        "💸 **Стоимость продажи**",
        "━━━━━━━━━━━━━━",
        f"Вы продаёте: **{amount:,.2f} {currency}**",
        f"Курс: **{rate:.2f}** ₽ за 1 {currency}",
        "━━━━━━━━━━━━━━━━━━━",
        f"💰 **Вы получите: {total_rub:,.2f} ₽**"
    ]
    return "\n".join(lines)

def format_services():
    text = (
        "📋 **Услуги и условия**\n\n"
        "• Покупка и продажа USDT и CNY (наличные)\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n"
        "• Дополнительные услуги: оплата товаров в Китае, пополнение WeChat/Alipay, переводы по Китаю, оплата на юр. счета\n\n"
        "Для оформления сделки или вопросов — нажмите «Связаться»."
    )
    return text

def format_about():
    text = (
        "ℹ️ **О нас**\n\n"
        "🏦 OnlineMena — надёжный обменник USDT и CNY.\n"
        "✅ Актуальные биржевые курсы\n"
        "⚡ Мгновенный расчёт\n"
        "💬 Личный менеджер\n"
        "🏢 Сделки проходят в моём офисе\n\n"
        "Для связи нажмите кнопку ниже."
    )
    return text

def format_course_text():
    usdt = get_usdt_sell_rate()
    cny = get_cny_sell_rate()
    date = datetime.now().strftime("%d.%m.%Y")
    lines = [
        f"📅 {date}",
        "📈 **Текущие курсы**",
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

# ---------- Клавиатуры ----------
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Стоимость покупки", callback_data="purchase")],
        [InlineKeyboardButton(text="💸 Стоимость продажи", callback_data="sale")],
        [InlineKeyboardButton(text="💬 Связаться со мной", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="📋 Услуги", callback_data="services")],
        [InlineKeyboardButton(text="🔄 Обновить курс", callback_data="refresh")]
    ])

def currency_keyboard(action):
    # action: 'purchase' или 'sale'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="USDT", callback_data=f"{action}_USDT"),
         InlineKeyboardButton(text="CNY", callback_data=f"{action}_CNY")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def contact_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться со мной", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def services_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться со мной", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def about_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться со мной", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

# ---------- Состояния ----------
waiting_for_amount = {}  # user_id -> {'action': 'purchase'/'sale', 'currency': 'USDT'/'CNY'}

# ---------- Обработчики команд ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    text = format_main_menu()
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("course"))
async def course_cmd(message: Message):
    text = format_course_text()
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("contact"))
async def contact_cmd(message: Message):
    await message.answer(
        "💬 **Связь со мной**\n\n"
        "Напишите мне в личные сообщения, я отвечу в течение 2–5 минут.",
        parse_mode="Markdown",
        reply_markup=contact_keyboard()
    )

@dp.message(Command("about"))
async def about_cmd(message: Message):
    text = format_about()
    await message.answer(text, parse_mode="Markdown", reply_markup=about_keyboard())

# ---------- Обработка кнопок ----------
@dp.callback_query(F.data == "back_to_course")
async def back_to_course(callback: CallbackQuery):
    await callback.answer()
    text = format_main_menu()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "refresh")
async def refresh_callback(callback: CallbackQuery):
    await callback.answer("Обновляю...")
    get_usdt_rub_rate(force=True)
    get_cny_rub_rate(force=True)
    get_usdt_cny_rate(force=True)
    text = format_main_menu()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "services")
async def services_callback(callback: CallbackQuery):
    await callback.answer()
    text = format_services()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=services_keyboard())

@dp.callback_query(F.data == "purchase")
async def purchase_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("💱 Что вы хотите получить?", reply_markup=currency_keyboard("purchase"))

@dp.callback_query(F.data == "sale")
async def sale_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("💱 Что вы хотите продать?", reply_markup=currency_keyboard("sale"))

@dp.callback_query(F.data.startswith("purchase_"))
async def purchase_currency_callback(callback: CallbackQuery):
    await callback.answer()
    currency = callback.data.split("_")[1]
    user_id = callback.from_user.id
    waiting_for_amount[user_id] = {"action": "purchase", "currency": currency}
    await callback.message.edit_text(f"💱 Введите сумму в {currency} (только число):")

@dp.callback_query(F.data.startswith("sale_"))
async def sale_currency_callback(callback: CallbackQuery):
    await callback.answer()
    currency = callback.data.split("_")[1]
    user_id = callback.from_user.id
    waiting_for_amount[user_id] = {"action": "sale", "currency": currency}
    await callback.message.edit_text(f"💱 Введите сумму в {currency} (только число):")

# ---------- Обработка чисел ----------
@dp.message(F.text.regexp(r'^\d+([,.]\d+)?$'))
async def handle_amount(message: Message):
    user_id = message.from_user.id
    if user_id not in waiting_for_amount:
        await message.answer("Сначала выберите действие через меню.")
        return

    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число.", reply_markup=contact_keyboard())
        return

    state = waiting_for_amount.pop(user_id)
    action = state["action"]
    currency = state["currency"]

    if action == "purchase":
        if currency == "USDT":
            rate = get_usdt_sell_rate()
        else:  # CNY
            rate = get_cny_sell_rate()
        if rate is None:
            await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
            return
        total = amount * rate
        text = format_purchase_result(amount, currency, rate, total)
        await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

    elif action == "sale":
        if currency == "USDT":
            rate = get_usdt_buy_rate()
        else:  # CNY
            rate = get_cny_buy_rate()
        if rate is None:
            await message.answer("❌ Не удалось получить курс. Попробуйте позже.", reply_markup=contact_keyboard())
            return
        total = amount * rate
        text = format_sale_result(amount, currency, rate, total)
        await message.answer(text, parse_mode="Markdown", reply_markup=contact_keyboard())

# ---------- Игнорирование остальных текстовых сообщений ----------
@dp.message(F.text)
async def ignore_other_text(message: Message):
    await message.answer("Используйте кнопки меню или команды /start, /course, /contact, /about")

# ---------- Запуск ----------
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏦 Главное меню"),
        BotCommand(command="course", description="📈 Текущий курс"),
        BotCommand(command="contact", description="💬 Связаться со мной"),
        BotCommand(command="about", description="ℹ️ О нас")
    ])
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())