import json
import random
import os
from pathlib import Path
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode

# ── Flask Сервер для Render ────────────────────────────────────────────────
app = Flask('')

@app.route('/')
def home():
    return "Бот работает"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ── Загрузка данных ────────────────────────────────────────────────────────
DATA_FILE = Path(__file__).parent / "all_variants.json"

try:
    with open(DATA_FILE, encoding="utf-8") as f:
        RAW = json.load(f)
except FileNotFoundError:
    print(f"Ошибка: Файл {DATA_FILE} не найден!")
    RAW = []

ALL_TASKS = []
VARIANTS_META = {}

for v in RAW:
    num = v["variant"]
    VARIANTS_META[num] = {
        "url": v.get("variant_url", ""),
        "text_1_3": v.get("group_1_3", {}).get("text", ""),
        "text_23_26": v.get("group_23_26", {}).get("text", ""),
    }

    def add_t(task, variant, text_key=None):
        ALL_TASKS.append({
            "id": f"v{variant}_t{task['number']}",
            "variant": variant,
            "number": task["number"],
            "question": task.get("question", ""),
            "answer": task.get("answer", ""),
            "explanation": task.get("explanation", ""),
            "text_key": text_key,
        })

    for t in v.get("group_1_3", {}).get("tasks", []):
        add_t(t, num, "text_1_3")
    for t in v.get("group_4_22", []):
        add_t(t, num, None)
    for t in v.get("group_23_26", {}).get("tasks", []):
        add_t(t, num, "text_23_26")

TASK_BY_ID = {t["id"]: t for t in ALL_TASKS}
USER_STATE = {}

# ── Логика бота ────────────────────────────────────────────────────────────

def get_state(uid: int):
    if uid not in USER_STATE:
        USER_STATE[uid] = {
            "queue": [], "current_id": None, "stats": {}, 
            "wrong_ids": set(), "filter_num": None, "filter_var": None, "answered": False
        }
    return USER_STATE[uid]

def escape(text: str):
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def build_task_msg(task: dict):
    v, n = task["variant"], task["number"]
    url = VARIANTS_META[v]["url"]
    lines = [f"📋 *Задание {n}* — Вариант {v}"]
    if task["text_key"]:
        ctx = VARIANTS_META[v].get(task["text_key"], "")
        if ctx:
            short = ctx[:800].rsplit(" ", 1)[0] + "…" if len(ctx) > 800 else ctx
            lines.append(f"\n📖 *Текст:*\n_{escape(short)}_")
    lines.append(f"\n❓ *Вопрос:*\n{escape(task['question'])}")
    if url: lines.append(f"\n🔗 [Открыть вариант]({url})")
    return "\n".join(lines), ParseMode.MARKDOWN_V2

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайное задание", callback_data="random")],
        [InlineKeyboardButton("📚 По номеру", callback_data="by_number"), InlineKeyboardButton("📓 По варианту", callback_data="by_variant")],
        [InlineKeyboardButton("🔁 Ошибки", callback_data="repeat_wrong"), InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("⚙️ Сброс фильтров", callback_data="reset_filters")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Выбери режим подготовки:", reply_markup=main_menu_kb())

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    s = get_state(uid)

    if q.data == "menu":
        await q.edit_message_text("🏠 *Главное меню*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())
    elif q.data == "random":
        if not ALL_TASKS: return
        task = random.choice(ALL_TASKS)
        text, pm = build_task_msg(task)
        await q.edit_message_text(text, parse_mode=pm, reply_markup=main_menu_kb()) # Упрощено для теста

# ── Запуск ─────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("КРИТИЧЕСКАЯ ОШИБКА: Переменная BOT_TOKEN не найдена в окружении!")
        return

    print("Инициализация бота...")
    application = Application.builder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    
    print("Бот запущен и начинает опрос (polling)...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    keep_alive() # Запуск Flask
    main()       # Запуск бота
    
