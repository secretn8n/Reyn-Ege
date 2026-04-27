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

app = Flask('')

@app.route('/')
def home():
    return "OK"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
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

    def add_item(task, variant, text_key=None):
        ALL_TASKS.append({
            "id": f"v{variant}_t{task['number']}",
            "variant": variant,
            "number": task["number"],
            "question": task.get("question", "Текст вопроса отсутствует"),
            "answer": task.get("answer", "Ответ не указан"),
            "explanation": task.get("explanation", ""),
            "text_key": text_key
        })

    if "group_1_3" in v:
        for t in v["group_1_3"].get("tasks", []):
            add_item(t, num, "text_1_3")
    
    for t in v.get("group_4_22", []):
        add_item(t, num, None)
        
    if "group_23_26" in v:
        for t in v["group_23_26"].get("tasks", []):
            add_item(t, num, "text_23_26")

TASK_BY_ID = {t["id"]: t for t in ALL_TASKS}
USER_STATE = {}

def get_state(uid: int):
    if uid not in USER_STATE:
        USER_STATE[uid] = {"current_id": None, "queue": []}
    return USER_STATE[uid]

def esc(text: str):
    if not text: return ""
    res = str(text)
    for ch in r"\_*[]()~`>#+-=|{}.!":
        res = res.replace(ch, f"\\{ch}")
    return res

def get_task_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 Показать ответ", callback_data="show_ans")],
        [InlineKeyboardButton("🏠 Меню", callback_data="menu")]
    ])

def get_ans_markup(has_exp: bool):
    btns = []
    if has_exp:
        btns.append(InlineKeyboardButton("📝 Пояснение", callback_data="show_exp"))
    btns.append(InlineKeyboardButton("⏭ Следующее", callback_data="next"))
    return InlineKeyboardMarkup([btns, [InlineKeyboardButton("🏠 Меню", callback_data="menu")]])

def get_exp_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Следующее", callback_data="next")],
        [InlineKeyboardButton("🏠 Меню", callback_data="menu")]
    ])

async def send_task_msg(update: Update, task: dict):
    v, n = task["variant"], task["number"]
    txt = f"📋 *Задание {n}* (Вариант {v})\n\n"
    
    if task["text_key"]:
        base_text = VARIANTS_META[v].get(task["text_key"], "")
        if base_text:
            display_text = base_text[:600] + "..." if len(base_text) > 600 else base_text
            txt += f"📖 *Текст:*\n_{esc(display_text)}_\n\n"
    
    txt += f"❓ *Вопрос:*\n{esc(task['question'])}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_task_markup())
    else:
        await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_task_markup())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Начать решать", callback_data="next")]])
    await update.message.reply_text(f"Готов к работе. В базе {len(ALL_TASKS)} заданий.", reply_markup=kb)

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    s = get_state(uid)
    
    if q.data == "menu":
        await start(update, context)
        
    elif q.data == "next":
        task = random.choice(ALL_TASKS)
        s["current_id"] = task["id"]
        await send_task_msg(update, task)
        
    elif q.data == "show_ans":
        task = TASK_BY_ID.get(s["current_id"])
        if task:
            txt = f"✅ *Ответ:* `{esc(task['answer'])}`"
            await q.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(uid, txt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_ans_markup(bool(task["explanation"])))

    elif q.data == "show_exp":
        task = TASK_BY_ID.get(s["current_id"])
        if task and task["explanation"]:
            txt = f"📝 *Пояснение:*\n{esc(task['explanation'])}"
            await context.bot.send_message(uid, txt, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=get_exp_markup())

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token: return
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_buttons))
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    keep_alive()
    main()
        
