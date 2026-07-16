import os
import threading
from flask import Flask
import asyncio
import logging
from bot import bot, dp

# Настройка логирования
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK"

def run_flask():
    """Запускает Flask-сервер в отдельном потоке"""
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

async def run_bot():
    """Запускает бота (polling)"""
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logging.error(f"Ошибка при запуске бота: {e}")
        raise

if __name__ == "__main__":
    # Запускаем Flask в фоновом потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем бота в основном потоке (asyncio)
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logging.info("Бот остановлен")