import os
import json
import base64
import logging
import sqlite3
from datetime import datetime
from anthropic import Anthropic
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

client = Anthropic(api_key=ANTHROPIC_API_KEY)

INITIAL_HISTORY = [
  {"date":"2026-01-14T10:00:00","exercises":[{"name":"Разгибание ног сидя статика","sets":[{"weight":"54","reps":"30"},{"weight":"54","reps":"30"},{"weight":"54","reps":"30"}]},{"name":"Разгибание ног сидя","sets":[{"weight":"54","reps":"12"},{"weight":"54","reps":"12"},{"weight":"54","reps":"12"}]},{"name":"Сгибание ног лёжа","sets":[{"weight":"","reps":"12"},{"weight":"","reps":"12"},{"weight":"","reps":"12"}]},{"name":"Приседания со штангой","sets":[{"weight":"25","reps":"15"},{"weight":"25","reps":"12"},{"weight":"25","reps":"10"},{"weight":"25","reps":"8"}]},{"name":"Бабочка тренажёр сведение рук","sets":[{"weight":"27","reps":"10"},{"weight":"27","reps":"10"},{"weight":"27","reps":"10"},{"weight":"27","reps":"10"}]},{"name":"Жим штанги узкий хват","sets":[{"weight":"15","reps":"12"},{"weight":"15","reps":"10"},{"weight":"15","reps":"8"},{"weight":"15","reps":"8"}]},{"name":"Трицепс верёвочная рукоять","sets":[{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"}]}]},
  {"date":"2026-01-18T10:00:00","exercises":[{"name":"Тяга штанги в наклоне обратный хват","sets":[{"weight":"20","reps":"10"},{"weight":"20","reps":"10"},{"weight":"20","reps":"10"},{"weight":"20","reps":"10"}]},{"name":"Тяга блок к груди поперечный хват","sets":[{"weight":"57","reps":"10"},{"weight":"57","reps":"10"},{"weight":"57","reps":"10"},{"weight":"57","reps":"10"}]},{"name":"Тяга гантели в наклоне к поясу","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},{"name":"Тяга z гриф к поясу двумя руками сверху","sets":[{"weight":"36","reps":"10"},{"weight":"36","reps":"10"},{"weight":"36","reps":"10"}]},{"name":"Бицепс штанга в смите стоя","sets":[{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"}]},{"name":"Стоя мягкий блок молоток","sets":[{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"}]}]},
  {"date":"2026-01-20T10:00:00","exercises":[{"name":"Жим штанги лёжа широкий хват","sets":[{"weight":"20","reps":"12"},{"weight":"25","reps":"10"},{"weight":"30","reps":"7"},{"weight":"35","reps":"3"},{"weight":"35","reps":"3"}]},{"name":"Бабочка тренажёр сведение рук","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"8"},{"weight":"31","reps":"7"}]},{"name":"Скоростной жим лёжа средний хват","sets":[{"weight":"15","reps":"12"},{"weight":"20","reps":"9"},{"weight":"20","reps":"7"}]},{"name":"Трицепс с/сет мягкий блок стоя","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]},{"name":"Бицепс штанга стоя прямой хват","sets":[{"weight":"25","reps":"6"},{"weight":"25","reps":"6"},{"weight":"25","reps":"6"}]}]},
  {"date":"2026-01-21T12:00:00","exercises":[{"name":"Подтягивания имитация тяга сверху","sets":[{"weight":"54","reps":"10"},{"weight":"54","reps":"10"},{"weight":"54","reps":"6"},{"weight":"54","reps":"5"}]},{"name":"Тяга в наклоне z хват треугольник","sets":[{"weight":"37.5","reps":"10"},{"weight":"37.5","reps":"8"},{"weight":"37.5","reps":"6"},{"weight":"37.5","reps":"4"}]},{"name":"Тяга одной рукой сидя к поясу","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},{"name":"Гантели в наклоне на широчайшую","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},{"name":"Опускание блока z гриф сверху к поясу","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"}]},{"name":"Бицепс молот гантели","sets":[{"weight":"5","reps":"10"},{"weight":"5","reps":"10"},{"weight":"5","reps":"10"}]}]},
  {"date":"2026-01-23T11:00:00","exercises":[{"name":"Жим лёжа широкий хват пауза","sets":[{"weight":"65","reps":"4"},{"weight":"65","reps":"4"},{"weight":"65","reps":"4"},{"weight":"65","reps":"4"},{"weight":"65","reps":"4"}]},{"name":"Жим лёжа средний хват ноги на лавке","sets":[{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"}]},{"name":"Бабочка тренажёр сведение рук","sets":[{"weight":"36","reps":"10"},{"weight":"36","reps":"10"},{"weight":"36","reps":"10"},{"weight":"36","reps":"10"}]},{"name":"Трицепс жим штанги узким хватом","sets":[{"weight":"30","reps":"15"},{"weight":"30","reps":"12"},{"weight":"30","reps":"10"},{"weight":"30","reps":"8"}]},{"name":"Трицепс верёвочная рукоять оба варианта","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]}]},
  {"date":"2026-01-27T11:00:00","exercises":[{"name":"Разгибание ног сидя статика","sets":[{"weight":"58","reps":"30"},{"weight":"58","reps":"30"},{"weight":"58","reps":"30"}]},{"name":"Разгибание ног сидя","sets":[{"weight":"45","reps":"20"},{"weight":"45","reps":"20"},{"weight":"45","reps":"20"}]},{"name":"Сгибание ног лёжа","sets":[{"weight":"31","reps":"15"},{"weight":"31","reps":"15"},{"weight":"31","reps":"15"}]},{"name":"Приседания со штангой узкая постановка","sets":[{"weight":"50","reps":"8"},{"weight":"50","reps":"8"},{"weight":"50","reps":"8"},{"weight":"50","reps":"8"}]},{"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"15","reps":"10"},{"weight":"15","reps":"10"},{"weight":"15","reps":"10"},{"weight":"15","reps":"10"}]},{"name":"Разводка гантелей стоя плечи","sets":[{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"}]},{"name":"Трицепс косичка с разведением в стороны стоя","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"}]}]},
  {"date":"2026-01-28T13:00:00","exercises":[{"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"}]},{"name":"Задние дельты лёжа скамья 30°","sets":[{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"}]},{"name":"Разводка гантелей сидя в стороны","sets":[{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"}]},{"name":"Подъём гантелей перед собой стоя","sets":[{"weight":"6","reps":"10"},{"weight":"6","reps":"10"},{"weight":"6","reps":"10"}]}]},
  {"date":"2026-01-29T13:49:00","exercises":[{"name":"Подтягивания имитация тяга сверху","sets":[{"weight":"68","reps":"6"},{"weight":"68","reps":"6"},{"weight":"68","reps":"6"},{"weight":"68","reps":"6"}]},{"name":"Тяга блока сидя поперечный хват","sets":[{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"}]},{"name":"Тяга блока одной рукой сидя грудью в спинку","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"}]},{"name":"Тяга одной рукой в наклоне с упором на скамью","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},{"name":"Тяга блок треугольная рукоять к груди","sets":[{"weight":"45","reps":"10"},{"weight":"45","reps":"10"},{"weight":"45","reps":"10"}]},{"name":"Бицепс скотт молот с/сет","sets":[{"weight":"13","reps":"10"},{"weight":"13","reps":"10"},{"weight":"13","reps":"10"}]},{"name":"Бицепс мягкий блок стоя","sets":[{"weight":"13","reps":"15"},{"weight":"13","reps":"15"},{"weight":"13","reps":"15"},{"weight":"13","reps":"15"}]}]},
  {"date":"2026-02-02T13:00:00","exercises":[{"name":"Жим лёжа лавка 30° средний хват","sets":[{"weight":"50","reps":"12"},{"weight":"50","reps":"10"},{"weight":"50","reps":"5"},{"weight":"50","reps":"5"},{"weight":"50","reps":"5"}]},{"name":"Скоростной жим лёжа горизонтальная лавка","sets":[{"weight":"40","reps":"12"},{"weight":"40","reps":"12"},{"weight":"40","reps":"12"}]},{"name":"Жим гантелей лёжа горизонтальный сжатые","sets":[{"weight":"18","reps":"9"},{"weight":"18","reps":"9"},{"weight":"18","reps":"9"}]},{"name":"Трицепс сидя лавка 60° гантели из-за головы","sets":[{"weight":"8","reps":"12"},{"weight":"8","reps":"12"},{"weight":"8","reps":"12"},{"weight":"8","reps":"12"}]},{"name":"Трицепс с/сет мягкий блок стоя","sets":[{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"}]},{"name":"Бицепс стоя штанга z гриф","sets":[{"weight":"27.5","reps":"10"},{"weight":"27.5","reps":"10"},{"weight":"27.5","reps":"10"},{"weight":"27.5","reps":"10"}]}]},
  {"date":"2026-02-07T13:52:00","exercises":[{"name":"Подтягивания имитация тяга сверху","sets":[{"weight":"68","reps":"7"},{"weight":"68","reps":"7"},{"weight":"68","reps":"7"},{"weight":"68","reps":"7"}]},{"name":"Тяга блока к груди сидя узкий хват","sets":[{"weight":"58","reps":"10"},{"weight":"58","reps":"10"},{"weight":"58","reps":"10"},{"weight":"58","reps":"10"}]},{"name":"Тяга блока одной рукой сидя с доворотом","sets":[{"weight":"28","reps":"7"},{"weight":"28","reps":"7"},{"weight":"28","reps":"7"},{"weight":"28","reps":"7"}]},{"name":"Тяга гантели одной рукой в наклоне с упором","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]},{"name":"Бицепс штанга стоя молот с/сет","sets":[{"weight":"25","reps":"6"},{"weight":"25","reps":"6"},{"weight":"25","reps":"6"}]},{"name":"Бицепс z гриф мягкий блок стоя","sets":[{"weight":"27","reps":"5"},{"weight":"27","reps":"5"},{"weight":"27","reps":"5"},{"weight":"27","reps":"5"},{"weight":"27","reps":"5"}]}]},
  {"date":"2026-02-11T11:32:00","exercises":[{"name":"Разгибание ног сидя статика","sets":[{"weight":"63","reps":"30"},{"weight":"63","reps":"30"}]},{"name":"Разгибание ног сидя","sets":[{"weight":"54","reps":"12"},{"weight":"54","reps":"12"},{"weight":"54","reps":"12"}]},{"name":"Сгибание ног лёжа","sets":[{"weight":"36","reps":"12"},{"weight":"36","reps":"12"},{"weight":"36","reps":"12"}]},{"name":"Приседания со штангой широкая постановка","sets":[{"weight":"60","reps":"6"},{"weight":"60","reps":"6"},{"weight":"60","reps":"6"},{"weight":"60","reps":"6"},{"weight":"60","reps":"6"}]},{"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"}]},{"name":"Трицепс мягкий блок косичка разведение","sets":[{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"}]}]},
  {"date":"2026-02-13T14:22:00","exercises":[{"name":"Румынская тяга со штангой","sets":[{"weight":"60","reps":"10"},{"weight":"60","reps":"10"},{"weight":"60","reps":"10"},{"weight":"60","reps":"10"},{"weight":"60","reps":"10"}]},{"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]},{"name":"Задние дельты стоя в наклоне","sets":[{"weight":"10","reps":"9"},{"weight":"10","reps":"9"},{"weight":"10","reps":"9"}]},{"name":"Обратное разведение в кроссовере наклон","sets":[{"weight":"9","reps":"9"},{"weight":"9","reps":"9"},{"weight":"9","reps":"9"}]},{"name":"Подъём гантелей перед собой стоя","sets":[{"weight":"6","reps":"9"},{"weight":"6","reps":"9"},{"weight":"6","reps":"9"}]},{"name":"Трицепс прямой блок","sets":[{"weight":"45","reps":"10"},{"weight":"45","reps":"10"},{"weight":"45","reps":"10"}]}]}
]

SKIP_KEYWORDS = ['пресс','кор','планка','растяжка','разминка','стретчинг','экстензи','супинация','пронация','предплечь']

def should_skip(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in SKIP_KEYWORDS)

# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS workouts (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, data TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT NOT NULL, created_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    c.execute("SELECT value FROM meta WHERE key='history_loaded'")
    if not c.fetchone():
        for w in INITIAL_HISTORY:
            c.execute("INSERT INTO workouts (date, data) VALUES (?, ?)", (w["date"], json.dumps(w["exercises"], ensure_ascii=False)))
        c.execute("INSERT INTO meta (key, value) VALUES ('history_loaded', '1')")
        logger.info(f"Loaded {len(INITIAL_HISTORY)} historical workouts")
    c.execute("SELECT COUNT(*) FROM rules")
    if c.fetchone()[0] == 0:
        for rule in ["Не вносить упражнения на пресс и кор", "Не вносить растяжки и разминку", "Не вносить упражнения на предплечья"]:
            c.execute("INSERT INTO rules (rule, created_at) VALUES (?, ?)", (rule, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def save_workout(date: str, exercises: list):
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("INSERT INTO workouts (date, data) VALUES (?, ?)", (date, json.dumps(exercises, ensure_ascii=False)))
    conn.commit()
    conn.close()

def get_all_workouts() -> list:
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("SELECT date, data FROM workouts ORDER BY date ASC")
    rows = c.fetchall()
    conn.close()
    return [{"date": r[0], "exercises": json.loads(r[1])} for r in rows]

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
    c.execute("INSERT INTO rules (rule, created_at) VALUES (?, ?)", (rule, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def delete_rule(rule_id: int):
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()

# ─── History lookup ───────────────────────────────────────────────────────────

MONTHS_RU = {1:"янв",2:"фев",3:"мар",4:"апр",5:"май",6:"июн",7:"июл",8:"авг",9:"сен",10:"окт",11:"ноя",12:"дек"}

def fmt_date(dt_str: str) -> str:
    d = datetime.fromisoformat(dt_str)
    return f"{d.day} {MONTHS_RU[d.month]}"

def get_exact_result(exercise_name: str):
    """Exact match lookup. Returns (date_str, short_summary)."""
    workouts = get_all_workouts()
    norm = exercise_name.lower().strip()
    for w in reversed(workouts):
        for ex in w["exercises"]:
            if ex["name"].lower().strip() == norm:
                sets = [s for s in ex["sets"] if s.get("weight") or s.get("reps")]
                if sets:
                    first = sets[0]
                    weight = first.get("weight","?")
                    reps = first.get("reps","?")
                    return fmt_date(w["date"]), f"{weight}кг × {reps} повт"
    return None, None

def find_similar_exercise(exercise_name: str):
    """Use AI to find the most similar exercise from history."""
    workouts = get_all_workouts()
    all_names = list({ex["name"] for w in workouts for ex in w["exercises"]})
    if not all_names:
        return None, None, None

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"""Упражнение: "{exercise_name}"

Список упражнений из истории:
{json.dumps(all_names, ensure_ascii=False)}

Найди самое похожее упражнение из списка по этим критериям (по приоритету):
1. Снаряд должен совпадать: гантели ≠ блок/трос ≠ штанга ≠ гиря. Это главное.
2. Группа мышц и тип движения должны совпадать.
3. Хват или техника похожи.

Верни ТОЛЬКО JSON без markdown: {{"similar": "название из списка"}}
Если подходящего нет (другой снаряд или другая мышца) — верни {{"similar": null}}"""
        }]
    )
    text = response.content[0].text.strip().replace("```json","").replace("```","").strip()
    result = json.loads(text)
    similar_name = result.get("similar")
    if not similar_name:
        return None, None, None
    date_str, sets_str = get_exact_result(similar_name)
    return similar_name, date_str, sets_str

def get_history_info(exercise_name: str) -> str:
    """Get history string for an exercise, with fallback to similar."""
    date_str, sets_str = get_exact_result(exercise_name)
    if date_str:
        return f"📅 {date_str}: {sets_str}"
    # Try similar
    similar_name, sim_date, sim_sets = find_similar_exercise(exercise_name)
    if similar_name and sim_date:
        return f"🔍 Похожее «{similar_name}»\n   {sim_date}: {sim_sets}"
    return "🆕 Первый раз"

# ─── Session state ────────────────────────────────────────────────────────────

user_sessions = {}

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "today_exercises": [],
            "results": [],
            "current_idx": -1,
            "date": None,
            "mode": None  # "interactive" or None
        }
    return user_sessions[user_id]

def reset_session(user_id: int):
    user_sessions[user_id] = {
        "today_exercises": [],
        "results": [],
        "current_idx": -1,
        "date": None,
        "mode": None
    }

# ─── Interactive mode ─────────────────────────────────────────────────────────

def format_exercise_prompt(ex: dict, idx: int, total: int) -> str:
    hist = get_history_info(ex["name"])
    return (
        f"*{idx+1}/{total}. {ex['name']}*\n"
        f"📋 {ex['sets']}×{ex['reps']} повт\n"
        f"{hist}\n\n"
        f"Введи вес (кг) или напиши «—» если без веса:"
    )

async def send_next_exercise(update: Update, session: dict):
    exercises = session["today_exercises"]
    idx = session["current_idx"]

    if idx >= len(exercises):
        # All done — save
        valid = [r for r in session["results"] if r]
        if valid:
            save_workout(session["date"], valid)
        text = "✅ *Тренировка сохранена!*\n\n"
        for r in valid:
            w = r["sets"][0].get("weight","?") if r["sets"] else "?"
            reps = r["sets"][0].get("reps","?") if r["sets"] else "?"
            text += f"• {r['name']}: {w}кг × {reps} повт\n"
        text += "\nОтличная работа! 💪"
        session["mode"] = None
        session["current_idx"] = -1
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        return

    ex = exercises[idx]
    msg = format_exercise_prompt(ex, idx, len(exercises))

    # Quick reply buttons with suggested weight
    _, sets_str = get_exact_result(ex["name"])
    buttons = []
    if sets_str:
        # Extract weight from last result
        try:
            last_w = sets_str.split(",")[0].split("кг")[0].strip()
            buttons.append([f"{last_w}"])
        except:
            pass
    buttons.append(["—"])

    markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True) if buttons else ReplyKeyboardRemove()
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=markup)

# ─── AI helpers ──────────────────────────────────────────────────────────────

def get_rules_text() -> str:
    rules = get_rules()
    return "\n".join(f"- {r[1]}" for r in rules)

def parse_program_from_image(image_base64: str, media_type: str) -> list:
    rules_text = get_rules_text()
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_base64}},
                {"type": "text", "text": f"""Это программа тренировки. Извлеки список упражнений.

НЕ включать:
{rules_text}

Верни ТОЛЬКО JSON без markdown:
{{"exercises":[{{"number":1,"name":"Название","sets":3,"reps":"10"}}]}}"""}
            ]
        }]
    )
    text = response.content[0].text.strip().replace("```json","").replace("```","").strip()
    exercises = json.loads(text)["exercises"]
    return [ex for ex in exercises if not should_skip(ex["name"])]

def answer_question(user_text: str) -> str:
    history = get_all_workouts()
    history_text = ""
    for w in history[-10:]:
        date_str = fmt_date(w["date"])
        exes = []
        for ex in w["exercises"]:
            sets_str = ", ".join(f"{s.get('weight','?')}кг×{s.get('reps','?')}" for s in ex["sets"] if s.get("weight") or s.get("reps"))
            if sets_str:
                exes.append(f"  {ex['name']}: {sets_str}")
        if exes:
            history_text += f"\n{date_str}:\n" + "\n".join(exes)

    rules_text = get_rules_text()
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        system=f"Ты трекер тренировок. Правила: {rules_text}. Отвечай кратко по-русски.",
        messages=[{"role": "user", "content": f"История:\n{history_text or 'нет'}\n\nВопрос: {user_text}"}]
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
    await update.message.reply_text(
        "👋 Привет! Я твой трекер тренировок.\n\n"
        "📸 Пришли скриншот программы от тренера — начнём тренировку\n"
        "📊 /history — история\n"
        "📋 /rules — правила\n"
        "❓ /help — помощь"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "📖 *Как пользоваться:*\n\n"
        "1. Пришли скриншот программы от тренера\n"
        "2. Бот покажет упражнения по одному с историей\n"
        "3. Вводи вес — бот сохранит автоматически\n\n"
        "/history — последние тренировки\n"
        "/last [упражнение] — последний результат\n"
        "/cancel — отменить текущую тренировку\n"
        "/rules — правила\n"
        "/addrule [текст] — добавить правило\n"
        "/delrule [номер] — удалить правило",
        parse_mode="Markdown"
    )

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    reset_session(update.effective_user.id)
    await update.message.reply_text("❌ Тренировка отменена.", reply_markup=ReplyKeyboardRemove())

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    workouts = get_all_workouts()
    if not workouts:
        await update.message.reply_text("Пока нет записей.")
        return
    text = "📊 *Последние тренировки:*\n"
    for w in reversed(workouts[-5:]):
        date_str = fmt_date(w["date"])
        names = [ex["name"] for ex in w["exercises"]]
        text += f"\n*{date_str}*\n" + "\n".join(f"  • {n}" for n in names[:4])
        if len(names) > 4:
            text += f"\n  +ещё {len(names)-4}"
        text += "\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Напиши: /last тяга")
        return
    query = " ".join(context.args)
    date_str, sets_str = get_exact_result(query)
    if date_str:
        await update.message.reply_text(f"*{query}*\n{date_str}: {sets_str}", parse_mode="Markdown")
    else:
        similar, sim_date, sim_sets = find_similar_exercise(query)
        if similar:
            await update.message.reply_text(f"Точного совпадения нет.\nПохожее: *{similar}*\n{sim_date}: {sim_sets}", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"Нет истории по «{query}»")

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    rules = get_rules()
    text = "📋 *Правила:*\n\n" + "\n".join(f"{r[0]}. {r[1]}" for r in rules)
    text += "\n\n/addrule [текст] — добавить\n/delrule [номер] — удалить"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_addrule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Напиши: /addrule текст правила")
        return
    add_rule(" ".join(context.args))
    await update.message.reply_text("✅ Правило добавлено")

async def cmd_delrule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Напиши: /delrule 3")
        return
    delete_rule(int(context.args[0]))
    await update.message.reply_text("✅ Правило удалено")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("📸 Читаю программу...")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    import aiohttp
    async with aiohttp.ClientSession() as session_http:
        async with session_http.get(file.file_path) as resp:
            image_bytes = await resp.read()
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    try:
        exercises = parse_program_from_image(image_base64, "image/jpeg")
    except Exception as e:
        logger.error(f"Image parse error: {e}")
        await update.message.reply_text("❌ Не удалось прочитать. Попробуй ещё раз.")
        return

    uid = update.effective_user.id
    reset_session(uid)
    session = get_session(uid)
    session["today_exercises"] = exercises
    session["results"] = [None] * len(exercises)
    session["date"] = datetime.now().isoformat()
    session["current_idx"] = 0
    session["mode"] = "interactive"

    await update.message.reply_text(
        f"✅ Загружено {len(exercises)} упражнений. Поехали!\n\n"
        f"_(напиши /cancel чтобы отменить)_",
        parse_mode="Markdown"
    )
    await send_next_exercise(update, session)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    uid = update.effective_user.id
    session = get_session(uid)
    text = update.message.text.strip()

    # Interactive mode — collecting weights
    if session.get("mode") == "interactive" and session["current_idx"] >= 0:
        idx = session["current_idx"]
        exercises = session["today_exercises"]
        ex = exercises[idx]

        # Parse weight
        if text == "—" or text.lower() == "-":
            weight = ""
        else:
            try:
                weight = str(float(text.replace(",", ".")))
                if weight.endswith(".0"):
                    weight = weight[:-2]
            except:
                await update.message.reply_text("Введи число (например 42) или «—» если без веса:")
                return

        session["results"][idx] = {
            "name": ex["name"],
            "sets": [{"weight": weight, "reps": ex.get("reps", "10")}]
        }

        session["current_idx"] += 1
        await send_next_exercise(update, session)
        return

    # Not in interactive mode — answer questions
    answer = answer_question(text)
    await update.message.reply_text(answer)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
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
