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

flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "✅ Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

DATA_FILE = Path(__file__).parent / "all_variants.json"

with open(DATA_FILE, encoding="utf-8") as f:
    RAW = json.load(f)

ALL_TASKS = []
VARIANTS_META = {}

for v in RAW:
    num = v["variant"]
    VARIANTS_META[num] = {
        "url": v.get("variant_url", ""),
        "text_1_3": v.get("group_1_3", {}).get("text", ""),
        "text_23_26": v.get("group_23_26", {}).get("text", ""),
    }

    def add_i(task, variant, text_key=None):
        ALL_TASKS.append({
            "id": f"v{variant}_t{task['number']}",
            "variant": variant,
            "number": task["number"],
            "question": task.get("question", ""),
            "answer": task.get("answer", ""),
            "explanation": task.get("explanation", ""),
            "text_key": text_key,
        })

    if "group_1_3" in v:
        for t in v["group_1_3"].get("tasks", []): add_i(t, num, "text_1_3")
    for t in v.get("group_4_22", []): add_i(t, num, None)
    if "group_23_26" in v:
        for t in v["group_23_26"].get("tasks", []): add_i(t, num, "text_23_26")

TASK_BY_ID = {t["id"]: t for t in ALL_TASKS}
USER_STATE = {}

def get_s(uid):
    if uid not in USER_STATE:
        USER_STATE[uid] = {"current_id": None, "wrong_ids": set()}
    return USER_STATE[uid]

def esc(text):
    if not text: return ""
    for ch in r"\_*[]()~`>#+-=|{}.!/":
        text = text.replace(ch, f"\\{ch}")
    return text

def kb_task():
    return InlineKeyboardMarkup([[InlineKeyboardButton("👁 Показать ответ", callback_data="ans")]])

def kb_ans(has_exp):
    row = [InlineKeyboardButton("⏭ Следующее", callback_data="next")]
    if has_exp: row.insert(0, InlineKeyboardButton("📝 Пояснение", callback_data="exp"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("🏠 Меню", callback_data="menu")]])

async def send_q(update, context, task):
    v, n = task["variant"], task["number"]
    msg = f"📋 *Задание {n}* \\(Вариант {v}\\)\n\n"
    if task["text_key"]:
        t_raw = VARIANTS_META[v].get(task["text_key"], "")
        if t_raw: msg += f"📖 *Текст:*\n_{esc(t_raw[:500])}..._\n\n"
    msg += f"❓ *Вопрос:*\n{esc(task['question'])}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_task())
    else:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_task())

async def start(update, context):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Начать", callback_data="next")]])
    await update.message.reply_text("Бот готов к работе.", reply_markup=kb)

async def handle(update, context):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    s = get_s(uid)

    if q.data == "menu":
        await start(update, context)
    elif q.data == "next":
        task = random.choice(ALL_TASKS)
        s["current_id"] = task["id"]
        await send_q(update, context, task)
    elif q.data == "ans":
        task = TASK_BY_ID.get(s["current_id"])
        if task:
            txt = f"✅ *Ответ:* `{esc(task['answer'])}`"
            await context.bot.send_message(uid, txt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_ans(bool(task["explanation"])))
    elif q.data == "exp":
        task = TASK_BY_ID.get(s["current_id"])
        if task and task["explanation"]:
            await context.bot.send_message(uid, f"📝 *Пояснение:*\n{esc(task['explanation'])}", parse_mode=ParseMode.MARKDOWN_V2)

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token: return
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    keep_alive()
    main()
    
