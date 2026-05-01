import os
import json
import base64
import logging
import sqlite3
from datetime import datetime
from anthropic import Anthropic
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            data TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    # Default rules
    c.execute("SELECT COUNT(*) FROM rules")
    if c.fetchone()[0] == 0:
        default_rules = [
            "Не вносить в трекер упражнения на пресс и кор",
            "Не вносить растяжки и разминку",
            "Не вносить упражнения на предплечья (супинация, пронация)",
        ]
        for rule in default_rules:
            c.execute("INSERT INTO rules (rule, created_at) VALUES (?, ?)",
                      (rule, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def save_workout(date: str, exercises: list):
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("INSERT INTO workouts (date, data) VALUES (?, ?)",
              (date, json.dumps(exercises, ensure_ascii=False)))
    conn.commit()
    conn.close()

def get_all_workouts() -> list:
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("SELECT date, data FROM workouts ORDER BY date ASC")
    rows = c.fetchall()
    conn.close()
    return [{"date": r[0], "exercises": json.loads(r[1])} for r in rows]

def get_last_result(exercise_name: str) -> str | None:
    workouts = get_all_workouts()
    norm = exercise_name.lower().strip()
    for w in reversed(workouts):
        for ex in w["exercises"]:
            if ex["name"].lower().strip() == norm:
                sets = [s for s in ex["sets"] if s.get("weight") or s.get("reps")]
                if sets:
                    date_str = datetime.fromisoformat(w["date"]).strftime("%-d %b")
                    sets_str = ", ".join(
                        f"{s['weight']}кг×{s['reps']}" if s.get("weight") and s.get("reps")
                        else f"{s['weight']}кг" if s.get("weight")
                        else f"{s['reps']} повт"
                        for s in sets
                    )
                    return f"{date_str}: {sets_str}"
    return None

def get_rules() -> list:
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("SELECT id, rule FROM rules ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows

def add_rule(rule: str):
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("INSERT INTO rules (rule, created_at) VALUES (?, ?)",
              (rule, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def delete_rule(rule_id: int):
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()

# ─── Session state ────────────────────────────────────────────────────────────

user_sessions = {}  # user_id -> {"today_exercises": [...], "pending_results": [...]}

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {"today_exercises": [], "pending_results": []}
    return user_sessions[user_id]

# ─── AI helpers ──────────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    rules = get_rules()
    rules_text = "\n".join(f"- {r[1]}" for r in rules)
    return f"""Ты — персональный трекер тренировок. Помогаешь вести журнал тренировок.

ПРАВИЛА (всегда соблюдай):
{rules_text}

Ты умеешь:
1. Читать программы тренировок со скриншотов
2. Парсить результаты тренировок из свободного текста пользователя
3. Отвечать на вопросы об истории тренировок

Отвечай кратко и по делу. Используй русский язык."""

def parse_program_from_image(image_base64: str, media_type: str) -> list:
    rules = get_rules()
    rules_text = "\n".join(f"- {r[1]}" for r in rules)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_base64}
                },
                {
                    "type": "text",
                    "text": f"""Это программа тренировки. Извлеки список упражнений.

ПРАВИЛА — эти категории НЕ включать:
{rules_text}

Верни ТОЛЬКО JSON без markdown:
{{"exercises":[{{"number":1,"name":"Название упражнения","sets":3,"reps":"8-10"}}]}}

Если количество подходов или повторений не указано, ставь sets:3, reps:"10"."""
                }
            ]
        }]
    )
    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(text)
    return parsed["exercises"]

def parse_results_from_text(user_text: str, today_exercises: list) -> list:
    exercises_list = "\n".join(
        f"{ex['number']}. {ex['name']}" for ex in today_exercises
    )
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"""Пользователь написал результаты тренировки в свободной форме.

Программа тренировки сегодня:
{exercises_list}

Что написал пользователь:
{user_text}

Сопоставь результаты с упражнениями из программы. Название в результате может не совпадать точно — используй смысловое совпадение.

Верни ТОЛЬКО JSON без markdown:
{{"results":[{{"name":"точное название из программы","sets":[{{"weight":"40","reps":"10"}}]}}]}}

Если вес не указан — weight:"", если повторения не указаны — reps:"".
Если результат не относится ни к одному упражнению — пропусти."""
        }]
    )
    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(text)
    return parsed["results"]

def answer_question(user_text: str, history: list) -> str:
    history_text = ""
    for w in history[-10:]:
        date_str = datetime.fromisoformat(w["date"]).strftime("%-d %b %Y")
        exes = []
        for ex in w["exercises"]:
            sets_str = ", ".join(
                f"{s.get('weight','?')}кг×{s.get('reps','?')}" for s in ex["sets"] if s.get("weight") or s.get("reps")
            )
            if sets_str:
                exes.append(f"  {ex['name']}: {sets_str}")
        if exes:
            history_text += f"\n{date_str}:\n" + "\n".join(exes)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        system=build_system_prompt(),
        messages=[{
            "role": "user",
            "content": f"""История тренировок:
{history_text or 'Пока нет записей'}

Вопрос пользователя: {user_text}

Ответь кратко и полезно."""
        }]
    )
    return response.content[0].text.strip()

# ─── Telegram handlers ───────────────────────────────────────────────────────

def is_allowed(update: Update) -> bool:
    if ALLOWED_USER_ID == 0:
        return True
    return update.effective_user.id == ALLOWED_USER_ID

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    text = (
        "👋 Привет! Я твой трекер тренировок.\n\n"
        "Что умею:\n"
        "📸 Получи скриншот программы от тренера → перешли мне\n"
        "💬 После тренировки напиши результаты в свободной форме\n"
        "📊 /history — история тренировок\n"
        "📋 /rules — правила (что не записывать)\n"
        "❓ /help — подробная помощь\n\n"
        "Начнём? Пришли скриншот программы от тренера!"
    )
    await update.message.reply_text(text)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    text = (
        "📖 *Как пользоваться:*\n\n"
        "*1. Загрузка программы*\n"
        "Пришли фото/скриншот программы от тренера → я прочитаю и покажу историю по каждому упражнению\n\n"
        "*2. Запись результатов*\n"
        "После тренировки напиши в любом формате:\n"
        "• _тяга 42кг 4х7_\n"
        "• _блок к груди 60, подъём гантели 14кг_\n"
        "• _1 - 42кг, 2 - 60кг, 3 - 55кг_\n\n"
        "*3. Команды:*\n"
        "/history — последние тренировки\n"
        "/last [упражнение] — последний результат\n"
        "/rules — текущие правила\n"
        "/addrule [текст] — добавить правило\n"
        "/delrule [номер] — удалить правило\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    workouts = get_all_workouts()
    if not workouts:
        await update.message.reply_text("Пока нет записей. Пришли скриншот программы!")
        return

    text = "📊 *Последние тренировки:*\n"
    for w in reversed(workouts[-5:]):
        date_str = datetime.fromisoformat(w["date"]).strftime("%-d %b %Y")
        names = [ex["name"] for ex in w["exercises"]]
        text += f"\n*{date_str}*\n" + "\n".join(f"  • {n}" for n in names[:4])
        if len(names) > 4:
            text += f"\n  ...ещё {len(names)-4}"
        text += "\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Напиши: /last тяга блок")
        return
    query = " ".join(context.args)
    result = get_last_result(query)
    if result:
        await update.message.reply_text(f"*{query}*\n{result}", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Нет истории по «{query}»")

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    rules = get_rules()
    text = "📋 *Текущие правила:*\n\n"
    for r in rules:
        text += f"{r[0]}. {r[1]}\n"
    text += "\n/addrule [текст] — добавить\n/delrule [номер] — удалить"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_addrule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Напиши: /addrule Не записывать разминку на велосипеде")
        return
    rule = " ".join(context.args)
    add_rule(rule)
    await update.message.reply_text(f"✅ Правило добавлено:\n_{rule}_", parse_mode="Markdown")

async def cmd_delrule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Напиши: /delrule 3")
        return
    rule_id = int(context.args[0])
    delete_rule(rule_id)
    await update.message.reply_text(f"✅ Правило #{rule_id} удалено")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    await update.message.reply_text("📸 Читаю программу тренировки...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(file.file_path) as resp:
            image_bytes = await resp.read()

    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    try:
        exercises = parse_program_from_image(image_base64, "image/jpeg")
    except Exception as e:
        logger.error(f"Image parse error: {e}")
        await update.message.reply_text("❌ Не удалось прочитать программу. Попробуй ещё раз.")
        return

    session = get_session(update.effective_user.id)
    session["today_exercises"] = exercises
    session["date"] = datetime.now().isoformat()

    text = f"✅ Программа загружена — {len(exercises)} упражнений\n\n"
    for ex in exercises:
        history = get_last_result(ex["name"])
        hist_str = f"\n   ↳ Прошлый раз: {history}" if history else "\n   ↳ Первый раз"
        text += f"*{ex['number']}. {ex['name']}*  {ex['sets']}×{ex['reps']}{hist_str}\n\n"

    text += "💪 Удачи на тренировке!\nПосле — напиши результаты в любом формате."
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    user_text = update.message.text.strip()
    session = get_session(update.effective_user.id)

    # If we have a loaded program — try to parse results
    if session.get("today_exercises"):
        await update.message.reply_text("⏳ Разбираю результаты...")
        try:
            results = parse_results_from_text(user_text, session["today_exercises"])
        except Exception as e:
            logger.error(f"Results parse error: {e}")
            await update.message.reply_text("❌ Не понял формат. Напиши например: _тяга 42кг, блок 60кг_", parse_mode="Markdown")
            return

        if not results:
            # Maybe it's a question
            history = get_all_workouts()
            answer = answer_question(user_text, history)
            await update.message.reply_text(answer)
            return

        # Save workout
        date = session.get("date", datetime.now().isoformat())
        save_workout(date, results)
        session["today_exercises"] = []

        text = "✅ *Тренировка сохранена!*\n\n"
        for ex in results:
            sets_str = " | ".join(
                f"{s.get('weight','?')}кг×{s.get('reps','?')}" for s in ex["sets"]
                if s.get("weight") or s.get("reps")
            )
            text += f"• {ex['name']}\n  {sets_str}\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    else:
        # No program loaded — answer questions or give instructions
        history = get_all_workouts()
        answer = answer_question(user_text, history)
        await update.message.reply_text(answer)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("last", cmd_last))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("addrule", cmd_addrule))
    app.add_handler(CommandHandler("delrule", cmd_delrule))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
