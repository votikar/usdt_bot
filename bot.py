import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional

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
    "delta_usdt_to_cny": get_delta_from_env("DELTA_USDT_CNY", 0.10),
    "delta_usdt_to_rub": get_delta_from_env("DELTA_USDT_RUB", 0.20),
}

# ---------- Кеш курсов ----------
_cache = {
    "usdt_rub": None,
    "usdt_cny": None,
    "timestamp": None,
    "last_successful_cny": None
}
CACHE_TTL = 60

logging.basicConfig(level=logging.INFO)

# ---------- Инициализация бота ----------
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
        resp = requests.get(url, timeout=10)
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

def get_usdt_cny_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] is not None and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usdt_cny"] is not None:
            return _cache["usdt_cny"]

    # Bybit
    try:
        url = "https://api.bybit.com/v5/market/tickers?category=spot&symbol=USDTCNY"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("retCode") == 0:
                rate = float(data["result"]["list"][0]["lastPrice"])
                _cache["usdt_cny"] = rate
                _cache["last_successful_cny"] = rate
                _cache["timestamp"] = now
                return rate
    except Exception as e:
        logging.warning(f"Bybit USDT/CNY failed: {e}")

    # CoinGecko
    url = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=cny"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 429:
                time.sleep(3)
                continue
            resp.raise_for_status()
            rate = float(resp.json()["tether"]["cny"])
            _cache["usdt_cny"] = rate
            _cache["last_successful_cny"] = rate
            _cache["timestamp"] = now
            return rate
        except Exception as e:
            logging.warning(f"CoinGecko attempt {attempt+1} failed: {e}")
            time.sleep(2)

    if _cache["last_successful_cny"] is not None:
        return _cache["last_successful_cny"]
    return None

def get_final_usdt_rub_rate():
    rate = get_usdt_rub_rate()
    if rate is None:
        return None
    return rate + deltas["delta_rub_to_usdt"]

def get_final_usdt_cny_rate():
    rate = get_usdt_cny_rate()
    if rate is None:
        return None
    return rate + deltas["delta_usdt_to_cny"]

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

def course_text():
    rub_rate = get_final_usdt_rub_rate()
    cny_rate = get_final_usdt_cny_rate()
    if rub_rate is None:
        return "❌ Не удалось получить курс. Попробуйте позже."
    text = "💰 **Текущий курс USDT**\n\n"
    text += f"🇺🇸 USDT/RUB: **{rub_rate:.2f}** ₽\n"
    if cny_rate is not None:
        text += f"🇨🇳 USDT/CNY: **{cny_rate:.2f}** ¥"
    else:
        text += "🇨🇳 USDT/CNY: ❌"
    return text

# ---------- Обработчики ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "💰 Добро пожаловать в обменник!\n\n"
        "Я предлагаю актуальный курс USDT к рублю и юаню.\n"
        "Курс обновляется в реальном времени.\n\n"
        "Для сделки (покупка или продажа) выберите соответствующую кнопку ниже.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("course"))
async def course_cmd(message: Message):
    text = course_text()
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ---------- Коллбэки ----------
@dp.callback_query(F.data == "refresh")
async def refresh_callback(callback: CallbackQuery):
    await callback.answer("Курс обновлён")
    text = course_text()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "back_to_course")
async def back_to_course_callback(callback: CallbackQuery):
    await callback.answer()
    text = course_text()
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "buy")
async def buy_callback(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📩 Вы выбрали **покупку USDT**.\n\n"
        "Условия сделки:\n"
        "• Оплата наличными (рубли или доллары США)\n"
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
        "• Получение наличных (рубли или доллары США)\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=action_keyboard())

@dp.callback_query(F.data == "services")
async def services_callback(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📋 **Дополнительные услуги:**\n\n"
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
        BotCommand(command="course", description="💰 Текущий курс USDT")
    ])
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())