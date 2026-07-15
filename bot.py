import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

BOT_TOKEN = "8221747840:AAHWUVECN07_ldY8aLutcr9qLnsKtRt45Uc"
ADMIN_ID = 8891085561

DELTA_FILE = "delta.json"

def load_delta() -> float:
    if Path(DELTA_FILE).exists():
        try:
            with open(DELTA_FILE, "r") as f:
                data = json.load(f)
                return data.get("delta", 0.30)
        except:
            return 0.30
    return 0.30

def save_delta(value: float):
    with open(DELTA_FILE, "w") as f:
        json.dump({"delta": value}, f)

DELTA = load_delta()

def get_usdt_rub_from_rapira() -> float | None:
    url = "https://api.rapira.net/open/market/rates"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        for item in data.get("data", []):
            if item.get("symbol") == "USDT/RUB":
                return float(item.get("askPrice", 0))
        return None
    except Exception as e:
        logging.error(f"Ошибка получения курса с Rapira: {e}")
        return None

def get_usdt_cny() -> float | None:
    url = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=cny"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return float(data["tether"]["cny"])
    except Exception as e:
        logging.error(f"Ошибка получения курса USDT/CNY: {e}")
        return None

def get_rate_with_delta() -> float | None:
    rate = get_usdt_rub_from_rapira()
    if rate is None:
        return None
    return rate + DELTA

def convert_rub_to_usdt_and_cny(amount_rub: float) -> dict | None:
    rub_rate = get_usdt_rub_from_rapira()
    if rub_rate is None:
        return None
    rub_rate_with_delta = rub_rate + DELTA
    cny_rate = get_usdt_cny()
    if cny_rate is None:
        return None
    usdt_amount = amount_rub / rub_rate_with_delta
    cny_amount = usdt_amount * cny_rate
    return {
        "amount_rub": amount_rub,
        "usdt_amount": usdt_amount,
        "cny_amount": cny_amount,
    }

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "👋 Привет! Я бот для конвертации USDT.\n\n"
        "📊 Доступные команды:\n"
        "/course — показать текущий курс\n"
        "/convert <сумма> — конвертировать рубли в USDT и CNY\n"
        "/help — справка"
    )

@dp.message(Command("course"))
async def course_command(message: Message):
    final_rate = get_rate_with_delta()
    if final_rate is None:
        await message.answer("❌ Не удалось получить курс. Попробуйте позже.")
        return
    now = datetime.now().strftime("%d.%m.%Y, %H:%M")
    response = f"📈 **Курс USDT/RUB**\n🕐 {now}\n\n💰 **{final_rate:.2f}** ₽"
    await message.answer(response, parse_mode="Markdown")

@dp.message(Command("convert"))
async def convert_command(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Укажите сумму в рублях.\nПример: `/convert 1000000`",
            parse_mode="Markdown"
        )
        return
    try:
        amount_rub = float(args[1].replace(",", "."))
        if amount_rub <= 0:
            raise ValueError("Сумма должна быть больше 0")
    except ValueError:
        await message.answer("❌ Введите корректное число (например, 1000000)")
        return
    result = convert_rub_to_usdt_and_cny(amount_rub)
    if result is None:
        await message.answer("❌ Не удалось получить курсы. Попробуйте позже.")
        return
    now = datetime.now().strftime("%d.%m.%Y, %H:%M")
    response = (
        f"💱 **Конвертация {result['amount_rub']:,.0f} ₽**\n"
        f"🕐 {now}\n\n"
        f"🪙 Получите: **{result['usdt_amount']:,.2f} USDT**\n"
        f"🇨🇳 В юанях: **{result['cny_amount']:,.2f} CNY**"
    )
    await message.answer(response, parse_mode="Markdown")

@dp.message(Command("set_delta"))
async def set_delta_command(message: Message):
    global DELTA
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет прав.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажите новую дельту.\nПример: `/set_delta 0.50`", parse_mode="Markdown")
        return
    try:
        new_delta = float(args[1].replace(",", "."))
        DELTA = new_delta
        save_delta(new_delta)
        await message.answer(f"✅ Дельта установлена на **{DELTA:.2f}** ₽")
    except ValueError:
        await message.answer("❌ Введите корректное число (например, 0.50)")

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "📋 **Доступные команды:**\n\n"
        "/course — показать курс USDT/RUB\n"
        "/convert <сумма> — конвертировать рубли в USDT и CNY\n"
        "/help — эта справка\n\n"
        "💡 Пример: `/convert 1000000`"
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())