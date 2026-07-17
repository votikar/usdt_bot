import asyncio
import logging
import os
from datetime import datetime

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Дельта
def get_delta(key, default):
    try:
        val = os.environ.get(key)
        if val is not None:
            return float(val)
    except:
        pass
    return default

delta_rub_to_usdt = get_delta("DELTA_RUB_USDT", 0.30)
delta_cny_rub = get_delta("DELTA_CNY_RUB", 0.00)

# Кеш
_cache = {"usdt_rub": None, "cny_rub": None, "timestamp": None}
CACHE_TTL = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- Получение курсов ----------
def get_usdt_rub_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["usdt_rub"]:
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
                logger.info(f"USDT/RUB: {rate}")
                return rate
        return None
    except Exception as e:
        logger.error(f"Rapira error: {e}")
        return None

def get_cny_rub_rate(force=False):
    now = datetime.now()
    if not force and _cache["timestamp"] and (now - _cache["timestamp"]).seconds < CACHE_TTL:
        if _cache["cny_rub"]:
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

def get_final_usdt_rub():
    rate = get_usdt_rub_rate()
    return rate + delta_rub_to_usdt if rate is not None else None

def get_final_cny_rub():
    rate = get_cny_rub_rate()
    return rate + delta_cny_rub if rate is not None else None

# ---------- Конвертация ----------
def rub_to_usdt(amount):
    rate = get_final_usdt_rub()
    if rate is None:
        return None
    return amount / rate

def rub_to_cny(amount):
    rate = get_final_cny_rub()
    if rate is None:
        return None
    return amount / rate

def usdt_to_rub(amount):
    rate = get_final_usdt_rub()
    if rate is None:
        return None
    return amount * rate

def cny_to_rub(amount):
    rate = get_final_cny_rub()
    if rate is None:
        return None
    return amount * rate

# ---------- Клавиатуры ----------
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Купить USDT", callback_data="buy"),
         InlineKeyboardButton(text="💳 Продать USDT", callback_data="sell")],
        [InlineKeyboardButton(text="💱 Конвертировать", callback_data="convert"),
         InlineKeyboardButton(text="🔄 Обновить курс", callback_data="refresh")],
        [InlineKeyboardButton(text="📋 Услуги", callback_data="services")]
    ])

def convert_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="RUB → USDT", callback_data="conv_RUB_USDT"),
         InlineKeyboardButton(text="RUB → CNY", callback_data="conv_RUB_CNY")],
        [InlineKeyboardButton(text="USDT → RUB", callback_data="conv_USDT_RUB"),
         InlineKeyboardButton(text="CNY → RUB", callback_data="conv_CNY_RUB")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def contact_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Связаться со мной", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_course")]
    ])

def services_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать мне", url="https://t.me/Hans77888")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_course")]
    ])

def course_text():
    usdt = get_final_usdt_rub()
    cny = get_final_cny_rub()
    if usdt is None:
        return "❌ Не удалось получить курс USDT. Попробуйте позже."
    text = "💰 **Текущие курсы**\n\n"
    text += f"🪙 USDT/RUB: **{usdt:.2f}** ₽\n"
    text += f"🇨🇳 CNY/RUB: **{cny:.2f}** ₽" if cny is not None else "🇨🇳 CNY/RUB: ❌"
    return text

# ---------- Словарь для ожидания ----------
waiting = {}

# ---------- Обработчики команд ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        f"🏦 Добро пожаловать в обменник!\n\n{course_text()}",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.message(Command("course"))
async def course_cmd(message: Message):
    text = course_text()
    await message.answer(text, parse_mode="Markdown", reply_markup=contact_button())

@dp.message(Command("convert"))
async def convert_cmd(message: Message):
    await message.answer("Выберите направление:", reply_markup=convert_menu())

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "📋 **Доступные команды:**\n"
        "/start – Главное меню\n"
        "/course – Показать курсы\n"
        "/convert – Открыть конвертацию\n"
        "/help – Эта справка\n\n"
        "Для связи со мной используйте кнопку «Связаться» под любым сообщением."
    )

# ---------- Обработка чисел ----------
@dp.message(F.text.regexp(r'^\d+([,.]\d+)?$'))
async def handle_number(message: Message):
    user_id = message.from_user.id
    if user_id not in waiting:
        await message.answer("Сначала выберите направление конвертации через меню.")
        return
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число.")
        return
    conv_type = waiting.pop(user_id)
    result = None
    if conv_type == "RUB_USDT":
        result = rub_to_usdt(amount)
        if result is not None:
            await message.answer(
                f"💱 **{amount:.2f} RUB ≈ {result:.4f} USDT**",
                parse_mode="Markdown",
                reply_markup=contact_button()
            )
        else:
            await message.answer("❌ Не удалось получить курс.")
    elif conv_type == "RUB_CNY":
        result = rub_to_cny(amount)
        if result is not None:
            await message.answer(
                f"💱 **{amount:.2f} RUB ≈ {result:.4f} CNY**",
                parse_mode="Markdown",
                reply_markup=contact_button()
            )
        else:
            await message.answer("❌ Не удалось получить курс.")
    elif conv_type == "USDT_RUB":
        result = usdt_to_rub(amount)
        if result is not None:
            await message.answer(
                f"💱 **{amount:.2f} USDT ≈ {result:.2f} RUB**",
                parse_mode="Markdown",
                reply_markup=contact_button()
            )
        else:
            await message.answer("❌ Не удалось получить курс.")
    elif conv_type == "CNY_RUB":
        result = cny_to_rub(amount)
        if result is not None:
            await message.answer(
                f"💱 **{amount:.2f} CNY ≈ {result:.2f} RUB**",
                parse_mode="Markdown",
                reply_markup=contact_button()
            )
        else:
            await message.answer("❌ Не удалось получить курс.")
    else:
        await message.answer("❌ Неизвестное направление.")

# ---------- Колбэки ----------
@dp.callback_query(F.data == "refresh")
async def refresh_cb(callback: CallbackQuery):
    await callback.answer("Обновляю...")
    get_usdt_rub_rate(force=True)
    get_cny_rub_rate(force=True)
    await callback.message.edit_text(
        course_text(),
        parse_mode="Markdown",
        reply_markup=contact_button()
    )

@dp.callback_query(F.data == "back_to_course")
async def back_cb(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        course_text(),
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "buy")
async def buy_cb(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📩 Вы выбрали **покупку USDT**.\n\n"
        "Условия сделки:\n"
        "• Оплата наличными\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=contact_button())

@dp.callback_query(F.data == "sell")
async def sell_cb(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📩 Вы выбрали **продажу USDT**.\n\n"
        "Условия сделки:\n"
        "• Получение наличных\n"
        "• Сделки проходят в моём офисе\n"
        "• Курс фиксируется на 1 час после согласования\n\n"
        "Для оформления нажмите «Продолжить»."
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=contact_button())

@dp.callback_query(F.data == "services")
async def services_cb(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📋 **Наши услуги:**\n\n"
        "• Покупка и продажа USDT (наличные)\n"
        "• Работа с юанями (CNY)\n"
        "• Оплата товаров в Китае\n"
        "• Пополнение WeChat и Alipay\n"
        "• Переводы по Китаю\n"
        "• Оплата на юр. счета\n\n"
        "Для подробностей напишите мне в личный чат."
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=services_menu())

@dp.callback_query(F.data == "convert")
async def convert_cb(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите направление:", reply_markup=convert_menu())

@dp.callback_query(F.data.startswith("conv_"))
async def conv_choice_cb(callback: CallbackQuery):
    await callback.answer()
    pair = callback.data.split("_")[1:]
    if len(pair) != 2:
        await callback.message.answer("Ошибка.")
        return
    from_cur, to_cur = pair
    key = f"{from_cur}_{to_cur}"
    waiting[callback.from_user.id] = key
    await callback.message.answer(f"Введите сумму в {from_cur}:")

# ---------- Запуск ----------
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="🏦 Главное меню"),
        BotCommand(command="course", description="💰 Текущие курсы"),
        BotCommand(command="convert", description="💱 Конвертация валют"),
        BotCommand(command="help", description="❓ Помощь")
    ])
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())