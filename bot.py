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
    "delta_cny_rub": get_delta_from_env("DELTA_CNY_RUB", 0.10),      # наценка на CNY при продаже
    "delta_cny_rub_buy": get_delta_from_env("DELTA_CNY_RUB_BUY", 0.50),  # скидка при покупке CNY
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

# ---------- Форматирование (добавлен USDT/CNY) ----------
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

# ---------- Остальной код без изменений ----------
# (все обработчики, колбэки, конвертеры, клавиатуры и т.д. остаются теми же)
# Я не буду повторять их для экономии места, но они должны быть в вашем файле.
# Если вы используете мой предыдущий полный код, просто замените функции форматирования.