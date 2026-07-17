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

# ---------- Дельта ----------
def get_delta_from_env(key, default):
    try:
        val = os.environ.get(key)
        if val is not None:
            return float(val)
    except:
        pass
    return default

delta_rub_to_usdt = get_delta_from_env("DELTA_RUB_USDT", 0.30)   # для USDT/RUB
delta_cny_rub = get_delta_from_env("DELTA_CNY_RUB", 0.00)       # для CNY/RUB (если хотите наценку на юань)

# ---------- Кеш ----------
_cache = {
    "usdt_rub": None,
    "usd_rub": None,
    "usd_cny": None,
    "timestamp": None,
}
CACHE_TTL = 30

logging.basicConfig(level=logging.INFO)

# ---------- Бот ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- Получение курсов ----------
def get_usdt_rub_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] is not None and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usdt_rub"] is not None:
            return _cache["usdt_rub"]
    url = "https://api.rapira.net/open/market/rates"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            if item.get("symbol") == "USDT/RUB":
                rate = float(item.get("askPrice", 0))
                _cache["usdt_rub"] = rate
                _cache["timestamp"] = now
                return rate
        return None
    except Exception as e:
        logging.error(f"Rapira error: {e}")
        return None

def get_usd_rub_rate(force=False):
    """Курс USD/RUB с ЦБ РФ"""
    now = datetime.now()
    if not force and _cache["timestamp"] is not None and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usd_rub"] is not None:
            return _cache["usd_rub"]
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        rate = data["Valute"]["USD"]["Value"]
        _cache["usd_rub"] = rate
        _cache["timestamp"] = now
        return rate
    except Exception as e:
        logging.error(f"ЦБ РФ USD/RUB error: {e}")
        return None

def get_usd_cny_rate(force=False):
    """Курс USD/CNY с Bybit (или CoinGecko как резерв)"""
    now = datetime.now()
    if not force and _cache["timestamp"] is not None and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usd_cny"] is not None:
            return _cache["usd_cny"]
    # 1) Bybit
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=spot&symbol=USDCNY"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("retCode") == 0:
                rate = float(data["result"]["list"][0]["lastPrice"])
                _cache["usd_cny"] = rate
                _cache["timestamp"] = now
                return rate
    except Exception as e:
        logging.warning(f"Bybit USD/CNY failed: {e}")
    # 2) CoinGecko
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=usd&vs_currencies=cny"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            rate = float(resp.json()["usd"]["cny"])
            _cache["usd_cny"] = rate
            _cache["timestamp"] = now
            return rate
    except Exception as e:
        logging.warning(f"CoinGecko USD/CNY failed: {e}")
    return None

def get_final_usdt_rub_rate():
    rate = get_usdt_rub_rate()
    if rate is None:
        return None
    return rate + delta_rub_to_usdt

def get_cny_rub_rate():
    """Вычисляем CNY/RUB = (USD/RUB) / (USD/CNY)"""
    usd_rub = get_usd_rub_rate()
    usd_cny = get_usd_cny_rate()
    if usd_rub is None or usd_cny is None or usd_cny == 0:
        return None
    return (usd_rub / usd_cny) + delta_cny_rub   # добавляем дельту для юаня

def get_usdt_cny_rate():
    """Вычисляем USDT/CNY = (USDT/RUB) / (CNY/RUB)"""
    usdt_rub = get_final_usdt_rub_rate()
    cny_rub = get_cny_rub_rate()
    if usdt_rub is None or cny_rub is None or cny_rub == 0:
        return None
    return usdt_rub / cny_rub

# ---------- Клавиатуры ----------
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Купить USDT", callback_data="buy"),
         InlineKeyboardButton(text="💳 Продать USDT", callback_data="sell")],
        [InlineKeyboardButton(text="📋 Услуги", callback_data="services"),
         InlineKeyboardButton(text="🔄 Обновить курс", callback_data="refresh")]
    ])

def action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продолжить", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def services_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать мне", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def get_course_text():
    usdt_rub = get_final_usdt_rub_rate()
    cny_rub = get_cny_rub_rate()
    usdt_cny = get_usdt_cny_rate()
    if usdt_rub is None:
        return "❌ Не удалось получить курс USDT. Попробуйте позже."
    text = "💰 **Текущие курсы**\n\n"
    text += f"🪙 USDT/RUB: **{usdt_rub:.2f}** ₽\n"
    if cny_rub is not None:
        text += f"🇨🇳 CNY/RUB: **{cny_rub:.2f}** ₽\n"
    else:
        text += "🇨🇳 CNY/RUB: ❌\n"
    if usdt_cny is not None:
        text += f"🪙 USDT/CNY: **{usdt_cny:.2f}** ¥"
    else:
        text += "🪙 USDT/CNY: ❌ (не хватает данных)"
    return text

# ---------- Конвертация RUB → USDT ----------
def convert_rub_to_usdt(amount_rub):
    rate = get_final_usdt_rub_rate()
    if rate is None:
        return None
    return amount_rub / rate

# ---------- Обработчики ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    text = get_course_text()
    await message.answer(
        f"🏦 Добро пожаловать в обменник!\n\n{text}\n\n"
        "Введите сумму в рублях (например, 1000) для конвертации в USDT, "
        "или используйте /convert для справки.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("course"))
async def course_cmd(message: Message):
    text = get_course_text()
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("convert"))
async def convert_cmd(message: Message):
    args = message.text.split()
    if len(args) > 1:
        try:
            amount = float(args[1].replace(',', '.'))
            if amount <= 0:
                raise ValueError
            result = convert_rub_to_usdt(amount)
            if result is None:
                await message.answer("❌ Не удалось получить курс. Попробуйте позже.")
                return
            await message.answer(
                f"💱 **{amount:.2f} ₽ ≈ {result:.4f} USDT**\n"
                f"(по курсу {get_final_usdt_rub_rate():.2f} ₽ за 1 USDT)",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        except:
            await message.answer("❌ Введите корректное положительное число.\nПример: `/convert 1000`", parse_mode="Markdown")
    else:
        await message.answer(
            "💱 **Конвертация RUB ↔ USDT**\n\n"
            "Введите сумму в рублях, чтобы узнать, сколько USDT вы получите.\n"
            "Пример: `/convert 1000`\n\n"
            "Или просто напишите число (например, `5000`) и я покажу конвертацию.",
            parse_mode="Markdown"
        )

# ---------- Обработка текстовых сообщений (ввод числа) ----------
@dp.message(F.text.regexp(r'^\d+([,.]\d+)?$'))
async def handle_number(message: Message):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Введите положительное число.")
            return
        result = convert_rub_to_usdt(amount)
        if result is None:
            await message.answer("❌ Не удалось получить курс. Попробуйте позже.")
            return
        rate = get_final_usdt_rub_rate()
        await message.answer(
            f"💱 **{amount:.2f} ₽ ≈ {result:.4f} USDT**\n"
            f"(по курсу {rate:.2f} ₽ за 1 USDT)",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    except:
        await message.answer("❌ Не удалось распознать число.")

# ---------- Коллбэки ----------
@dp.callback_query(F.data == "refresh")
async def refresh_callback(callback: CallbackQuery):
    await callback.answer("Обновляю курс...")
    get_usdt_rub_rate(force=True)
    get_usd_rub_rate(force=True)
    get_usd_cny_rate(force=True)
    text = get_course_text()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "back_to_course")
async def back_to_course_callback(callback: CallbackQuery):
    await callback.answer()
    text = get_course_text()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

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
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=action_keyboard())

@dp.callback_query(F.data == "sell")
async def sell_callback(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📩 Вы выбрали **продажу USDT**.\n\n"
        "Условия сделки:\n"
        "• Получение наличных\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=action_keyboard())

@dp.callback_query(F.data == "services")
async def services_callback(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📋 **Наши услуги:**\n\n"
        "• Покупка и продажа USDT (наличные)\n"
        "• Работа с юанями (CNY) – консультации и обмен\n"
        "• Оплата товаров в Китае\n"
        "• Пополнение WeChat и Alipay\n"
        "• Переводы между крупными городами Китая\n"
        "• Оплата на юридические счета\n"
        "• Консультации по расчётам с Китаем\n\n"
        "Для подробностей и оформления — напишите мне в личный чат."
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=services_keyboard())

# ---------- Запуск ----------
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏦 Главное меню"),
        BotCommand(command="course", description="💰 Текущие курсы"),
        BotCommand(command="convert", description="💱 Конвертация RUB → USDT")
    ])
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())