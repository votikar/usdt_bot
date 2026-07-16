import os
import threading
from flask import Flask
from bot import bot, dp  # Импортируем вашего бота и диспетчер
import asyncio

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK"

# Функция для запуска бота в отдельном потоке
def run_bot():
    asyncio.run(dp.start_polling(bot, skip_updates=True))

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    thread = threading.Thread(target=run_bot)
    thread.start()
    # Запускаем веб-сервер, который будет слушать порт
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)