import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F

BOT_TOKEN = "8221747840:AAHWUVECN07_ldY8aLutcr9qLnsKtRt45Uc"
ADMIN_ID = 8891085561

DELTA_FILE = "deltas.json"

# Загрузка дельт
def load_deltas():
    default = {
        "delta_rub_to_usdt": 0.30,
        "delta_usdt_to_cny": 0.10,
        "delta_usdt_to_rub": 0.20
    }
    if Path(DELTA_FILE).exists():
        try:
            with open(DELTA_FILE, "r") as f:
                data = json.load(f)
                for key in default:
                    if key not in data:
                        data[key] = default[key]
                return data
        except:
            return default
    return default

def save_deltas(deltas):
    with open(DELTA_FILE, "w") as f:
        json.dump(deltas, f)

deltas = load_deltas()

# Функции получения курсов
def get_usdt_rub_rate():
    url = "https://api.rapira.net/open/market/rates"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            if item.get("symbol") == "USDT/RUB":
                return float(item.get("askPrice", 0))
        return None
    except Exception as e:
        logging.error(f"Rapira error: {e}")
        return None

def get_usdt_cny_rate():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=cny"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data["tether"]["cny"])
    except Exception as e:
        logging.error(f"CoinGecko error: {e}")
        return None

# Конвертация
def convert_rub_to_usdt_cny(amount_rub):
    usdt_rate = get_usdt_rub_rate()
    cny_rate = get_usdt_cny_rate()
    if usdt_rate is None or cny_rate is None:
        return None
    usdt_rate_with_delta = usdt_rate + deltas["delta_rub_to_usdt"]
    cny_rate_with_delta = cny_rate + deltas["delta_usdt_to_cny"]
    usdt = amount_rub / usdt_rate_with_delta
    cny = usdt * cny_rate_with_delta
    return {
        "amount_rub": amount_rub,
        "usdt": usdt,
        "cny": cny,
    }

def convert_usdt_to_rub(amount_usdt):
    usdt_rate = get_usdt_rub_rate()
    if usdt_rate is None:
        return None
    rate_with_delta = usdt_rate - deltas["delta_usdt_to_rub"]
    if rate_with_delta < 0:
        rate_with_delta = 0
    rub = amount_usdt * rate_with_delta
    return {
        "amount_usdt": amount_usdt,
        "rub": rub,
    }

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище для ожидания ввода
waiting_for_rub = {}
waiting_for_usdt = {}

# Установка команд меню
async def set_default_commands():
    await bot.set_my_commands([
        BotCommand(command="course", description="📈 Текущий курс USDT/RUB"),
        BotCommand(command="convert_rub", description="💱 Конвертировать рубли → USDT/CNY"),
        BotCommand(command="convert_usdt", description="💰 Конвертировать USDT → рубли"),
        BotCommand(command="help", description="❓ Справка")
    ])

# Обработчики
@dp.message(Command("start"))
async def start_cmd(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Курс", callback_data="course")],
        [InlineKeyboardButton(text="💱 Рубли → USDT/CNY", callback_data="convert_rub")],
        [InlineKeyboardButton(text="💰 USDT → рубли", callback_data="convert_usdt")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])
    await message.answer(
        "👋 Привет! Я бот для конвертации криптовалют.\n\n"
        "Используй кнопки ниже или команды из меню.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "course")
async def course_callback(callback: CallbackQuery):
    await callback.answer()
    await course_cmd(callback.message)

@dp.callback_query(F.data == "convert_rub")
async def convert_rub_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("Введите сумму в рублях (например, 10000):")
    waiting_for_rub[callback.from_user.id] = True

@dp.callback_query(F.data == "convert_usdt")
async def convert_usdt_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("Введите сумму в USDT (например, 500):")
    waiting_for_usdt[callback.from_user.id] = True

@dp.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):
    await callback.answer()
    await help_cmd(callback.message)

@dp.message(Command("course"))
async def course_cmd(message: Message):
    rate = get_usdt_rub_rate()
    if rate is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.")
        return
    now = datetime.now().strftime("%d.%m.%Y, %H:%M")
    await message.answer(f"📈 **Курс USDT/RUB**\n🕐 {now}\n\n💰 **{rate:.2f}** ₽", parse_mode="Markdown")

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
            await message.answer("❌ Введите корректное положительное число.")
    else:
        await message.answer("Введите сумму в рублях (например, 10000):")
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
            await message.answer("❌ Введите корректное положительное число.")
    else:
        await message.answer("Введите сумму в USDT (например, 500):")
        waiting_for_usdt[message.from_user.id] = True

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "📋 **Доступные команды:**\n\n"
        "/course – текущий курс USDT/RUB\n"
        "/convert_rub [сумма] – конвертировать рубли в USDT и CNY\n"
        "/convert_usdt [сумма] – конвертировать USDT в рубли\n"
        "/help – эта справка\n\n"
        "💡 Примеры:\n"
        "/convert_rub 10000\n"
        "/convert_usdt 500"
    )

# Админ-команды для установки дельт
@dp.message(Command("set_delta_rub_usdt"))
async def set_delta_rub_usdt(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Только для администратора.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Пример: `/set_delta_rub_usdt 0.30`")
        return
    try:
        val = float(args[1].replace(',', '.'))
        deltas["delta_rub_to_usdt"] = val
        save_deltas(deltas)
        await message.answer(f"✅ Дельта RUB→USDT установлена: {val:.2f} ₽")
    except:
        await message.answer("❌ Введите корректное число.")

@dp.message(Command("set_delta_usdt_cny"))
async def set_delta_usdt_cny(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Только для администратора.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Пример: `/set_delta_usdt_cny 0.10`")
        return
    try:
        val = float(args[1].replace(',', '.'))
        deltas["delta_usdt_to_cny"] = val
        save_deltas(deltas)
        await message.answer(f"✅ Дельта USDT→CNY установлена: {val:.2f} ¥")
    except:
        await message.answer("❌ Введите корректное число.")

@dp.message(Command("set_delta_usdt_rub"))
async def set_delta_usdt_rub(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Только для администратора.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Пример: `/set_delta_usdt_rub 0.20`")
        return
    try:
        val = float(args[1].replace(',', '.'))
        deltas["delta_usdt_to_rub"] = val
        save_deltas(deltas)
        await message.answer(f"✅ Дельта USDT→RUB установлена: {val:.2f} ₽")
    except:
        await message.answer("❌ Введите корректное число.")

# Обработка обычных текстовых сообщений (для ввода суммы)
@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if waiting_for_rub.get(user_id, False):
        try:
            amount = float(text.replace(',', '.'))
            if amount <= 0:
                raise ValueError
            del waiting_for_rub[user_id]
            await process_rub_conversion(message, amount)
        except:
            await message.answer("❌ Введите корректное положительное число.")
        return

    if waiting_for_usdt.get(user_id, False):
        try:
            amount = float(text.replace(',', '.'))
            if amount <= 0:
                raise ValueError
            del waiting_for_usdt[user_id]
            await process_usdt_conversion(message, amount)
        except:
            await message.answer("❌ Введите корректное положительное число.")
        return

    await message.answer("Используйте команды из меню или отправьте /help")

# Вспомогательные функции с анимацией
async def process_rub_conversion(message: Message, amount_rub):
    loading = await message.answer("⏳ Конвертирую...")
    result = convert_rub_to_usdt_cny(amount_rub)
    if result is None:
        await loading.edit_text("❌ Не удалось получить курс. Попробуйте позже.")
        return
    now = datetime.now().strftime("%d.%m.%Y, %H:%M")
    await loading.edit_text(
        f"💱 **Конвертация {result['amount_rub']:,.0f} ₽**\n"
        f"🕐 {now}\n\n"
        f"🪙 Получите: **{result['usdt']:,.2f} USDT**\n"
        f"🇨🇳 В юанях: **{result['cny']:,.2f} CNY**",
        parse_mode="Markdown"
    )

async def process_usdt_conversion(message: Message, amount_usdt):
    loading = await message.answer("⏳ Конвертирую...")
    result = convert_usdt_to_rub(amount_usdt)
    if result is None:
        await loading.edit_text("❌ Не удалось получить курс. Попробуйте позже.")
        return
    now = datetime.now().strftime("%d.%m.%Y, %H:%M")
    await loading.edit_text(
        f"💰 **Конвертация {result['amount_usdt']:,.2f} USDT**\n"
        f"🕐 {now}\n\n"
        f"🇷🇺 Получите: **{result['rub']:,.2f} ₽**",
        parse_mode="Markdown"
    )

# Запуск
async def main():
    await set_default_commands()
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())