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

delta_rub_to_usdt = get_delta_from_env("DELTA_RUB_USDT", 0.30)
delta_cny_rub = get_delta_from_env("DELTA_CNY_RUB", 0.00)

# ---------- Кеш ----------
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
                logger.info(f"USDT/RUB from Rapira: {rate}")
                return rate
        return None
    except Exception as e:
        logger.error(f"Rapira USDT/RUB error: {e}")
        return None

def get_cny_rub_rate(force=False):
    """Прямой курс CNY/RUB с ЦБ РФ (с дельтой)"""
    now = datetime.now()
    if not force and _cache["timestamp"] is not None and (now - _cache["timestamp"]).seconds < CACHE_TTL:
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
        logger.error(f"CBR CNY/RUB error: {e}")
        return None

def get_final_usdt_rub_rate():
    rate = get_usdt_rub_rate()
    if rate is None:
        return None
    return rate + delta_rub_to_usdt

def get_final_cny_rub_rate():
    rate = get_cny_rub_rate()
    if rate is None:
        return None
    return rate + delta_cny_rub

# ---------- Клавиатуры ----------
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Купить USDT", callback_data="buy"),
         InlineKeyboardButton(text="💳 Продать USDT", callback_data="sell")],
        [InlineKeyboardButton(text="📋 Услуги", callback_data="services"),
         InlineKeyboardButton(text="🔄 Обновить курс", callback_data="refresh")]
    ])

def convert_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="RUB → USDT", callback_data="conv_RUB_USDT"),
         InlineKeyboardButton(text="RUB → CNY", callback_data="conv_RUB_CNY")],
        [InlineKeyboardButton(text="USDT → RUB", callback_data="conv_USDT_RUB"),
         InlineKeyboardButton(text="CNY → RUB", callback_data="conv_CNY_RUB")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
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
    cny_rub = get_final_cny_rub_rate()
    if usdt_rub is None:
        return "❌ Не удалось получить курс USDT. Попробуйте позже."
    text = "💰 **Текущие курсы**\n\n"
    text += f"🪙 USDT/RUB: **{usdt_rub:.2f}** ₽\n"
    if cny_rub is not None:
        text += f"🇨🇳 CNY/RUB: **{cny_rub:.2f}** ₽"
    else:
        text += "🇨🇳 CNY/RUB: ❌"
    return text

# ---------- Конвертация ----------
def convert_rub_to_usdt(amount_rub):
    rate = get_final_usdt_rub_rate()
    if rate is None:
        return None
    return amount_rub / rate

def convert_rub_to_cny(amount_rub):
    rate = get_final_cny_rub_rate()
    if rate is None:
        return None
    return amount_rub / rate

def convert_usdt_to_rub(amount_usdt):
    rate = get_final_usdt_rub_rate()
    if rate is None:
        return None
    return amount_usdt * rate

def convert_cny_to_rub(amount_cny):
    rate = get_final_cny_rub_rate()
    if rate is None:
        return None
    return amount_cny * rate

# ---------- Обработчики ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    text = get_course_text()
    await message.answer(
        f"🏦 Добро пожаловать в обменник!\n\n{text}\n\n"
        "Для конвертации нажмите кнопку «Конвертировать» ниже.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )

@dp.message(Command("course"))
async def course_cmd(message: Message):
    text = get_course_text()
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

@dp.message(Command("convert"))
async def convert_cmd(message: Message):
    await message.answer("Выберите направление конвертации:", reply_markup=convert_menu_keyboard())

# ---------- Обработка текстовых сообщений (ввод числа) ----------
waiting_for_convert = {}

@dp.message(F.text.regexp(r'^\d+([,.]\d+)?$'))
async def handle_number(message: Message):
    user_id = message.from_user.id
    if user_id in waiting_for_convert:
        try:
            amount = float(message.text.replace(',', '.'))
            if amount <= 0:
                raise ValueError
        except:
            await message.answer("❌ Введите положительное число.")
            return
        conv_type = waiting_for_convert.pop(user_id)
        result = None
        if conv_type == "RUB_USDT":
            result = convert_rub_to_usdt(amount)
            if result is not None:
                await message.answer(f"💱 **{amount:.2f} RUB ≈ {result:.4f} USDT**")
            else:
                await message.answer("❌ Не удалось получить курс.")
        elif conv_type == "RUB_CNY":
            result = convert_rub_to_cny(amount)
            if result is not None:
                await message.answer(f"💱 **{amount:.2f} RUB ≈ {result:.4f} CNY**")
            else:
                await message.answer("❌ Не удалось получить курс.")
        elif conv_type == "USDT_RUB":
            result = convert_usdt_to_rub(amount)
            if result is not None:
                await message.answer(f"💱 **{amount:.2f} USDT ≈ {result:.2f} RUB**")
            else:
                await message.answer("❌ Не удалось получить курс.")
        elif conv_type == "CNY_RUB":
            result = convert_cny_to_rub(amount)
            if result is not None:
                await message.answer(f"💱 **{amount:.2f} CNY ≈ {result:.2f} RUB**")
            else:
                await message.answer("❌ Не удалось получить курс.")
        else:
            await message.answer("❌ Неизвестное направление.")
        return
    # Если просто число без ожидания – предлагаем конвертацию
    await message.answer("Используйте кнопки конвертации, чтобы выбрать направление.")

# ---------- Коллбэки ----------
@dp.callback_query(F.data == "refresh")
async def refresh_callback(callback: CallbackQuery):
    await callback.answer("Обновляю курс...")
    get_usdt_rub_rate(force=True)
    get_cny_rub_rate(force=True)
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

@dp.callback_query(F.data == "convert")
async def convert_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите направление конвертации:", reply_markup=convert_menu_keyboard())

@dp.callback_query(F.data.startswith("conv_"))
async def convert_pair_callback(callback: CallbackQuery):
    await callback.answer()
    pair = callback.data.split("_")[1:]
    if len(pair) != 2:
        await callback.message.answer("Ошибка выбора пары.")
        return
    from_cur, to_cur = pair
    conv_key = f"{from_cur}_{to_cur}"
    waiting_for_convert[callback.from_user.id] = conv_key
    await callback.message.answer(f"💱 Введите сумму в {from_cur}:")

# ---------- Запуск ----------
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏦 Главное меню"),
        BotCommand(command="course", description="💰 Текущие курсы"),
        BotCommand(command="convert", description="💱 Конвертация валют")
    ])
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())