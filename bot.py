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

    def add(task, variant, text_key=None):
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
        add(t, num, "text_1_3")
    for t in v.get("group_4_22", []):
        add(t, num, None)
    for t in v.get("group_23_26", {}).get("tasks", []):
        add(t, num, "text_23_26")

TASK_BY_ID = {t["id"]: t for t in ALL_TASKS}
USER_STATE = {}

def get_state(uid: int):
    if uid not in USER_STATE:
        USER_STATE[uid] = {
            "mode": "menu",
            "queue": [],
            "current_id": None,
            "stats": {},
            "wrong_ids": set(),
            "filter_num": None,
            "filter_var": None,
            "answered": False,
        }
    return USER_STATE[uid]

def escape(text: str):
    if not text: return ""
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
    if url:
        lines.append(f"\n🔗 [Открыть вариант]({url})")
    return "\n".join(lines), ParseMode.MARKDOWN_V2

def build_answer_msg(task: dict):
    ans = escape(task["answer"])
    exp = escape(task["explanation"]) if task["explanation"] else "_пояснение отсутствует_"
    return f"✅ *Ответ:* `{ans}`\n\n📝 *Пояснение:*\n{exp}"

def filter_tasks(uid: int):
    s = get_state(uid)
    tasks = ALL_TASKS
    if s["filter_num"]:
        tasks = [t for t in tasks if t["number"] == s["filter_num"]]
    if s["filter_var"]:
        tasks = [t for t in tasks if t["variant"] == s["filter_var"]]
    return tasks

def stats_summary(uid: int):
    s = get_state(uid)
    st = s["stats"]
    if not st:
        return "Статистики пока нет\\. Порешай задания\\!"
    total = len(st)
    correct = sum(1 for v in st.values() if v["correct"] > 0)
    pct = int(correct / total * 100)
    lines = [f"📊 *Твоя статистика*\n"]
    lines.append(f"Всего решено: *{total}*")
    lines.append(f"С правильным ответом: *{correct}* ({pct}%)")
    lines.append(f"Требуют повторения: *{len(s['wrong_ids'])}*")
    return "\n".join(lines)

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайное задание", callback_data="random")],
        [InlineKeyboardButton("📚 По номеру", callback_data="by_number"),
         InlineKeyboardButton("📓 По варианту", callback_data="by_variant")],
        [InlineKeyboardButton("🔁 Ошибки", callback_data="repeat_wrong"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("⚙️ Сброс фильтров", callback_data="reset_filters")],
    ])

def task_kb(answered: bool):
    kb = [
        [InlineKeyboardButton("✅ Знал", callback_data="mark_correct"),
         InlineKeyboardButton("❌ Не знал", callback_data="mark_wrong")],
        [InlineKeyboardButton("⏭ Следующее", callback_data="next_task"),
         InlineKeyboardButton("🏠 Меню", callback_data="menu")]
    ]
    if not answered:
        kb.insert(0, [InlineKeyboardButton("👁 Показать ответ", callback_data="show_answer")])
    return InlineKeyboardMarkup(kb)

def number_select_kb():
    nums = sorted(set(t["number"] for t in ALL_TASKS))
    rows, row = [], []
    for n in nums:
        row.append(InlineKeyboardButton(str(n), callback_data=f"num_{n}"))
        if len(row) == 6:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def variant_select_kb():
    vars_ = sorted(VARIANTS_META.keys())
    rows, row = [], []
    for v in vars_:
        row.append(InlineKeyboardButton(f"В{v}", callback_data=f"var_{v}"))
        if len(row) == 5:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

async def send_task(update: Update, context: ContextTypes.DEFAULT_TYPE, task: dict):
    uid = update.effective_user.id
    s = get_state(uid)
    s["current_id"] = task["id"]
    s["answered"] = False
    text, pm = build_task_msg(task)
    kb = task_kb(False)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=pm, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=pm, reply_markup=kb)

async def send_next_from_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = get_state(uid)
    if s["queue"]:
        task_id = s["queue"].pop(0)
        task = TASK_BY_ID.get(task_id)
        if task:
            await send_task(update, context, task)
            return
    text = "🎉 Задания закончились\\! Выбери режим снова\\."
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = escape(f"👋 Привет! В базе: {len(ALL_TASKS)} заданий. Выбери режим:")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id
    s = get_state(uid)

    if data == "menu":
        await q.edit_message_text(escape("🏠 Главное меню:"), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())
    elif data == "reset_filters":
        s["filter_num"], s["filter_var"] = None, None
        await q.edit_message_text(escape("✅ Фильтры сброшены!"), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())
    elif data == "random":
        tasks = filter_tasks(uid)
        if not tasks:
            await q.edit_message_text(escape("Нет заданий!"), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())
            return
        await send_task(update, context, random.choice(tasks))
    elif data == "by_number":
        await q.edit_message_text("Выбери номер:", reply_markup=number_select_kb())
    elif data.startswith("num_"):
        n = int(data[4:])
        s["filter_num"], s["filter_var"] = n, None
        tasks = [t for t in ALL_TASKS if t["number"] == n]
        s["queue"] = [t["id"] for t in tasks]
        random.shuffle(s["queue"])
        await send_next_from_queue(update, context)
    elif data == "by_variant":
        await q.edit_message_text("Выбери вариант:", reply_markup=variant_select_kb())
    elif data.startswith("var_"):
        v = int(data[4:])
        s["filter_var"], s["filter_num"] = v, None
        s["queue"] = [t["id"] for t in ALL_TASKS if t["variant"] == v]
        await send_next_from_queue(update, context)
    elif data == "repeat_wrong":
        wrong = list(s["wrong_ids"])
        if not wrong:
            await q.edit_message_text(escape("Ошибок нет!"), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())
            return
        s["queue"] = wrong[:]
        random.shuffle(s["queue"])
        await send_next_from_queue(update, context)
    elif data == "show_answer":
        tid = s.get("current_id")
        task = TASK_BY_ID.get(tid)
        if task:
            s["answered"] = True
            await context.bot.send_message(uid, build_answer_msg(task), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=task_kb(True))
            await q.edit_message_reply_markup(reply_markup=None)
    elif data in ("mark_correct", "mark_wrong"):
        tid = s.get("current_id")
        if not tid: return
        if tid not in s["stats"]: s["stats"][tid] = {"attempts": 0, "correct": 0}
        s["stats"][tid]["attempts"] += 1
        if data == "mark_correct":
            s["stats"][tid]["correct"] += 1
            s["wrong_ids"].discard(tid)
            msg = "✅ Сохранено"
        else:
            s["wrong_ids"].add(tid)
            msg = "❌ В список ошибок"
        await context.bot.send_message(uid, escape(msg), parse_mode=ParseMode.MARKDOWN_V2)
    elif data == "next_task":
        await send_next_from_queue(update, context)
    elif data == "stats":
        await q.edit_message_text(stats_summary(uid), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu_kb())

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token: raise RuntimeError("BOT_TOKEN MISSING")
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    keep_alive()
    main()
    
