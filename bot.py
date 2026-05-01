import os
import json
import base64
import logging
import sqlite3
from datetime import datetime
from anthropic import Anthropic
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
import gspread
from google.oauth2.service_account import Credentials
import asyncio
from datetime import time as dtime
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

SPREADSHEET_ID = "1PfZefjJFlIwKUFpbhq63jUsLDZpPc6sXO3And6WMeEY"
WHOOP_EMAIL = os.environ.get("WHOOP_EMAIL", "")
WHOOP_PASSWORD = os.environ.get("WHOOP_PASSWORD", "")

async def get_whoop_data() -> dict | None:
    """Fetch today's Whoop recovery, sleep and strain data."""
    if not WHOOP_EMAIL or not WHOOP_PASSWORD:
        return None
    try:
        import aiohttp as _aiohttp
        # Step 1: authenticate
        async with _aiohttp.ClientSession() as session:
            auth_resp = await session.post(
                "https://api-7.whoop.com/oauth/token",
                json={
                    "grant_type": "password",
                    "issueRefresh": False,
                    "password": WHOOP_PASSWORD,
                    "username": WHOOP_EMAIL
                }
            )
            if auth_resp.status != 200:
                logger.error(f"Whoop auth failed: {auth_resp.status}")
                return None
            auth_data = await auth_resp.json()
            token = auth_data.get("access_token")
            user_id = auth_data.get("user", {}).get("id")
            if not token or not user_id:
                return None

            headers = {"Authorization": f"bearer {token}"}

            # Step 2: get recovery
            # Get last 2 cycles: [0] = today (current), [1] = yesterday (completed)
            rec_resp = await session.get(
                f"https://api-7.whoop.com/users/{user_id}/cycles",
                headers=headers,
                params={"limit": 2}
            )
            if rec_resp.status != 200:
                return None
            rec_data = await rec_resp.json()
            cycles = rec_data.get("records", [])
            if not cycles:
                return None

            # Today's cycle — for recovery, HRV, RHR, sleep
            today_cycle = cycles[0]
            # Yesterday's completed cycle — for Strain
            yesterday_cycle = cycles[1] if len(cycles) > 1 else None

            recovery = today_cycle.get("recovery", {})
            sleep = today_cycle.get("sleep", {})

            recovery_score = recovery.get("score")
            hrv = recovery.get("hrvRmssd")
            rhr = recovery.get("restingHeartRate")
            sleep_duration = sleep.get("qualityDuration", 0)
            sleep_hours = round(sleep_duration / 3600000, 1) if sleep_duration else None

            # Strain from yesterday's completed cycle
            strain_score = None
            if yesterday_cycle:
                strain_score = yesterday_cycle.get("strain", {}).get("score")

            return {
                "recovery": round(recovery_score) if recovery_score else None,
                "hrv": round(hrv) if hrv else None,
                "rhr": round(rhr) if rhr else None,
                "sleep_hours": sleep_hours,
                "strain": round(strain_score, 1) if strain_score else None
            }
    except Exception as e:
        logger.error(f"Whoop error: {e}")
        return None

def get_whoop_sheet():
    """Get or create Whoop sheet in spreadsheet."""
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
        if not creds_json:
            return None
        import json as _json
        creds_data = _json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        try:
            return sh.worksheet("Whoop")
        except:
            ws = sh.add_worksheet(title="Whoop", rows=1000, cols=10)
            ws.append_row(["Дата", "Recovery %", "HRV (мс)", "ЧСС покоя", "Сон (ч)", "Strain"])
            return ws
    except Exception as e:
        logger.error(f"Whoop sheet error: {e}")
        return None

async def save_whoop_to_sheet(data: dict):
    """Save Whoop data to Google Sheets."""
    try:
        sheet = get_whoop_sheet()
        if not sheet:
            return
        today = datetime.now().strftime("%-d %b %Y")
        # Check if today already exists
        all_dates = sheet.col_values(1)
        if today in all_dates:
            return  # Already saved today
        sheet.append_row([
            today,
            data.get("recovery", ""),
            data.get("hrv", ""),
            data.get("rhr", ""),
            data.get("sleep_hours", ""),
            data.get("strain", "")
        ])
        logger.info(f"Whoop data saved: {data}")
    except Exception as e:
        logger.error(f"Whoop sheet save error: {e}")

def format_whoop_message(data: dict) -> str:
    recovery = data.get("recovery")
    if recovery is None:
        return ""
    if recovery >= 67:
        emoji = "🟢"
    elif recovery >= 34:
        emoji = "🟡"
    else:
        emoji = "🔴"
    
    lines = [f"\n📊 *Whoop сегодня:*"]
    lines.append(f"{emoji} Recovery: *{recovery}%*")
    if data.get("hrv"):
        lines.append(f"💓 HRV: {data['hrv']} мс")
    if data.get("rhr"):
        lines.append(f"❤️ ЧСС покоя: {data['rhr']} уд/мин")
    if data.get("sleep_hours"):
        lines.append(f"😴 Сон: {data['sleep_hours']} ч")
    if data.get("strain"):
        lines.append(f"⚡ Strain вчера: {data['strain']}")
    return "\n".join(lines)

def get_sheet():
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
        if not creds_json:
            return None
        import json as _json
        creds_data = _json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        return sh.sheet1
    except Exception as e:
        logger.error(f"Google Sheets error: {e}")
        return None

def ensure_sheet_headers(sheet):
    try:
        row1 = sheet.row_values(1)
        if not row1:
            sheet.append_row(["Дата", "Упражнение", "Подходы", "Повторения", "Вес (кг)"])
    except Exception as e:
        logger.error(f"Header error: {e}")

def write_workout_to_sheet(date: str, exercises: list):
    try:
        sheet = get_sheet()
        if not sheet:
            return
        ensure_sheet_headers(sheet)
        date_str = fmt_date(date)
        rows = []
        for ex in exercises:
            sets = [s for s in ex["sets"] if s.get("weight") or s.get("reps")]
            if sets:
                weight = sets[0].get("weight", "")
                reps = sets[0].get("reps", "")
                rows.append([date_str, ex["name"], len(sets), reps, weight])
        if rows:
            sheet.append_rows(rows)
            logger.info(f"Written {len(rows)} rows to Google Sheets")
    except Exception as e:
        logger.error(f"Sheet write error: {e}")

def import_from_sheet():
    """Read all data from Google Sheets and save to local DB."""
    try:
        sheet = get_sheet()
        if not sheet:
            return 0
        rows = sheet.get_all_values()
        if len(rows) < 2:
            return 0
        
        conn = sqlite3.connect("workouts.db")
        c = conn.cursor()
        c.execute("DELETE FROM workouts")
        
        # Group rows by date
        from collections import defaultdict
        by_date = defaultdict(list)
        for row in rows[1:]:  # skip header
            if len(row) >= 5:
                date_raw, name, sets_count, reps, weight = row[0], row[1], row[2], row[3], row[4]
                by_date[date_raw].append({"name": name, "sets_count": sets_count, "reps": reps, "weight": weight})
        
        # Convert to workout format
        imported = 0
        for date_str, exercises in by_date.items():
            ex_list = []
            for ex in exercises:
                try:
                    n = int(ex["sets_count"])
                except:
                    n = 1
                sets = [{"weight": ex["weight"], "reps": ex["reps"]}] * n
                ex_list.append({"name": ex["name"], "sets": sets})
            # Use date_str as-is (it's already formatted like "14 янв")
            # We need ISO format for storage — approximate it
            c.execute("INSERT INTO workouts (date, data) VALUES (?, ?)",
                      (date_str, json.dumps(ex_list, ensure_ascii=False)))
            imported += 1
        
        conn.commit()
        conn.close()
        return imported
    except Exception as e:
        logger.error(f"Import from sheet error: {e}")
        return 0

def export_history_to_sheet():
    try:
        sheet = get_sheet()
        if not sheet:
            return 0
        sheet.clear()
        ensure_sheet_headers(sheet)
        workouts = get_all_workouts()
        rows = []
        for w in workouts:
            date_str = fmt_date(w["date"])
            for ex in w["exercises"]:
                sets = [s for s in ex["sets"] if s.get("weight") or s.get("reps")]
                if sets:
                    weight = sets[0].get("weight", "")
                    reps = sets[0].get("reps", "")
                    rows.append([date_str, ex["name"], len(sets), reps, weight])
        if rows:
            sheet.append_rows(rows)
        return len(rows)
    except Exception as e:
        logger.error(f"Export error: {e}")
        return 0

INITIAL_HISTORY = [
  {"date":"2026-01-14T10:00:00","exercises":[
    {"name":"Разгибание ног сидя статика","sets":[{"weight":"54","reps":"30"},{"weight":"54","reps":"30"},{"weight":"54","reps":"30"}]},
    {"name":"Разгибание ног сидя","sets":[{"weight":"54","reps":"12"},{"weight":"54","reps":"12"},{"weight":"54","reps":"12"}]},
    {"name":"Сгибание ног лёжа","sets":[{"weight":"","reps":"12"},{"weight":"","reps":"12"},{"weight":"","reps":"12"}]},
    {"name":"Приседания со штангой","sets":[{"weight":"25","reps":"15"},{"weight":"25","reps":"12"},{"weight":"25","reps":"10"},{"weight":"25","reps":"8"}]},
    {"name":"Жим гантелей лёжа 60°","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},
    {"name":"Бабочка на грудные","sets":[{"weight":"27","reps":"10"},{"weight":"27","reps":"10"},{"weight":"27","reps":"10"},{"weight":"27","reps":"10"}]},
    {"name":"Жим штанги узкий хват","sets":[{"weight":"15","reps":"12"},{"weight":"15","reps":"10"},{"weight":"15","reps":"8"},{"weight":"15","reps":"8"}]},
    {"name":"Трицепс верёвочная рукоять","sets":[{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"}]}
  ]},
  {"date":"2026-01-18T10:00:00","exercises":[
    {"name":"Тяга в наклоне обратный хват","sets":[{"weight":"20","reps":"10"},{"weight":"20","reps":"10"},{"weight":"20","reps":"10"},{"weight":"20","reps":"10"}]},
    {"name":"Тяга блок к груди поперечный хват","sets":[{"weight":"57","reps":"10"},{"weight":"57","reps":"10"},{"weight":"57","reps":"10"},{"weight":"57","reps":"10"}]},
    {"name":"Тяга гантели в наклоне к поясу","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},
    {"name":"Тяга з гриф к поясу двумя руками","sets":[{"weight":"36","reps":"10"},{"weight":"36","reps":"10"},{"weight":"36","reps":"10"}]},
    {"name":"Бицепс штанга в смите стоя","sets":[{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"},{"weight":"2.5","reps":"10"}]},
    {"name":"Молот с гантелями","sets":[{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"}]}
  ]},
  {"date":"2026-01-20T10:00:00","exercises":[
    {"name":"Жим штанги лёжа широкий хват","sets":[{"weight":"20","reps":"12"},{"weight":"25","reps":"10"},{"weight":"30","reps":"7"},{"weight":"35","reps":"3"},{"weight":"35","reps":"3"}]},
    {"name":"Бабочка на грудные","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"8"},{"weight":"31","reps":"7"}]},
    {"name":"Скоростной жим лёжа средний хват","sets":[{"weight":"15","reps":"12"},{"weight":"20","reps":"9"},{"weight":"20","reps":"7"}]},
    {"name":"Жим гантелей из-за головы трицепс","sets":[{"weight":"10","reps":"10"},{"weight":"10","reps":"9"},{"weight":"10","reps":"6"},{"weight":"10","reps":"5"}]},
    {"name":"Трицепс с/сет мягкая рукоять","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]},
    {"name":"Бицепс сидя з гриф с колен","sets":[{"weight":"","reps":"5"},{"weight":"","reps":"5"},{"weight":"","reps":"5"},{"weight":"","reps":"5"},{"weight":"","reps":"5"}]},
    {"name":"Бицепс штанга стоя прямой хват","sets":[{"weight":"25","reps":"6"},{"weight":"25","reps":"6"},{"weight":"25","reps":"6"}]}
  ]},
  {"date":"2026-01-21T12:00:00","exercises":[
    {"name":"Тяга сверху имитация подтягиваний","sets":[{"weight":"54","reps":"10"},{"weight":"54","reps":"10"},{"weight":"54","reps":"6"},{"weight":"54","reps":"5"}]},
    {"name":"Тяга в наклоне з хват треугольник","sets":[{"weight":"37.5","reps":"10"},{"weight":"37.5","reps":"8"},{"weight":"37.5","reps":"6"},{"weight":"37.5","reps":"4"}]},
    {"name":"Тяга одной рукой сидя к поясу","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},
    {"name":"Тяга гантели в наклоне на широчайшую","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},
    {"name":"Опускание блока з гриф к поясу","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"}]},
    {"name":"Бицепс в смите стоя","sets":[{"weight":"5","reps":"10"},{"weight":"5","reps":"10"},{"weight":"5","reps":"10"}]},
    {"name":"Молот с гантелями","sets":[{"weight":"5","reps":"10"},{"weight":"5","reps":"10"},{"weight":"5","reps":"10"}]}
  ]},
  {"date":"2026-01-23T11:00:00","exercises":[
    {"name":"Жим штанги лёжа широкий хват пауза","sets":[{"weight":"65","reps":"4"},{"weight":"65","reps":"4"},{"weight":"65","reps":"4"},{"weight":"65","reps":"4"},{"weight":"65","reps":"4"}]},
    {"name":"Жим лёжа ноги на лавке средний хват","sets":[{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"}]},
    {"name":"Бабочка на грудные","sets":[{"weight":"36","reps":"10"},{"weight":"36","reps":"10"},{"weight":"36","reps":"10"},{"weight":"36","reps":"10"}]},
    {"name":"Трицепс жим штанги узким хватом","sets":[{"weight":"30","reps":"15"},{"weight":"30","reps":"12"},{"weight":"30","reps":"10"},{"weight":"30","reps":"8"}]},
    {"name":"Трицепс жим гантелей лёжа","sets":[{"weight":"9","reps":"12"},{"weight":"9","reps":"12"},{"weight":"9","reps":"12"},{"weight":"9","reps":"12"}]},
    {"name":"Трицепс верёвочная рукоять","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]}
  ]},
  {"date":"2026-01-27T11:00:00","exercises":[
    {"name":"Разгибание ног сидя статика","sets":[{"weight":"58","reps":"30"},{"weight":"58","reps":"30"},{"weight":"58","reps":"30"}]},
    {"name":"Разгибание ног сидя","sets":[{"weight":"45","reps":"20"},{"weight":"45","reps":"20"},{"weight":"45","reps":"20"}]},
    {"name":"Сгибание ног лёжа","sets":[{"weight":"31","reps":"15"},{"weight":"31","reps":"15"},{"weight":"31","reps":"15"}]},
    {"name":"Приседания со штангой узкая постановка","sets":[{"weight":"50","reps":"8"},{"weight":"50","reps":"8"},{"weight":"50","reps":"8"},{"weight":"50","reps":"8"}]},
    {"name":"Приводящие ног в тренажёре","sets":[{"weight":"49","reps":"10"},{"weight":"49","reps":"10"},{"weight":"49","reps":"10"}]},
    {"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"15","reps":"10"},{"weight":"15","reps":"10"},{"weight":"15","reps":"10"},{"weight":"15","reps":"10"}]},
    {"name":"Разводка гантелей стоя плечи","sets":[{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"}]},
    {"name":"Трицепс жим гантелей лёжа сведены","sets":[{"weight":"12","reps":"10"},{"weight":"12","reps":"10"},{"weight":"12","reps":"10"}]},
    {"name":"Трицепс косичка разведение в стороны стоя","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"}]}
  ]},
  {"date":"2026-01-28T13:00:00","exercises":[
    {"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"},{"weight":"18","reps":"8"}]},
    {"name":"Задние дельты лёжа скамья 30°","sets":[{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"},{"weight":"8","reps":"8"}]},
    {"name":"Разводка гантелей сидя в стороны","sets":[{"weight":"8","reps":"10"},{"weight":"8","reps":"10"},{"weight":"8","reps":"10"}]},
    {"name":"Подъём гантелей перед собой стоя","sets":[{"weight":"6","reps":"10"},{"weight":"6","reps":"10"},{"weight":"6","reps":"10"}]}
  ]},
  {"date":"2026-01-29T13:49:00","exercises":[
    {"name":"Тяга сверху имитация подтягиваний","sets":[{"weight":"68","reps":"6"},{"weight":"68","reps":"6"},{"weight":"68","reps":"6"},{"weight":"68","reps":"6"}]},
    {"name":"Тяга блока сидя поперечный хват","sets":[{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"}]},
    {"name":"Тяга блока одной рукой сидя грудью в спинку","sets":[{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"},{"weight":"31","reps":"10"}]},
    {"name":"Тяга гантели одной рукой в наклоне с упором","sets":[{"weight":"18","reps":"10"},{"weight":"18","reps":"10"},{"weight":"18","reps":"10"}]},
    {"name":"Тяга блок треугольная рукоять к груди","sets":[{"weight":"45","reps":"10"},{"weight":"45","reps":"10"},{"weight":"45","reps":"10"}]},
    {"name":"Бицепс скотт молот с/сет","sets":[{"weight":"13","reps":"10"},{"weight":"13","reps":"10"},{"weight":"13","reps":"10"}]},
    {"name":"Бицепс мягкий блок стоя","sets":[{"weight":"13","reps":"15"},{"weight":"13","reps":"15"},{"weight":"13","reps":"15"},{"weight":"13","reps":"15"}]}
  ]},
  {"date":"2026-02-02T13:00:00","exercises":[
    {"name":"Жим лёжа лавка 30° средний хват","sets":[{"weight":"50","reps":"12"},{"weight":"50","reps":"10"},{"weight":"50","reps":"5"},{"weight":"50","reps":"5"},{"weight":"50","reps":"5"}]},
    {"name":"Скоростной жим лёжа горизонтальная лавка","sets":[{"weight":"40","reps":"12"},{"weight":"40","reps":"12"},{"weight":"40","reps":"12"}]},
    {"name":"Жим гантелей лёжа горизонтальный сжатые","sets":[{"weight":"18","reps":"9"},{"weight":"18","reps":"9"},{"weight":"18","reps":"9"}]},
    {"name":"Трицепс гантели из-за головы сидя","sets":[{"weight":"8","reps":"12"},{"weight":"8","reps":"12"},{"weight":"8","reps":"12"},{"weight":"8","reps":"12"}]},
    {"name":"Трицепс с/сет мягкая рукоять","sets":[{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"}]},
    {"name":"Бицепс штанга з гриф стоя","sets":[{"weight":"27.5","reps":"10"},{"weight":"27.5","reps":"10"},{"weight":"27.5","reps":"10"},{"weight":"27.5","reps":"10"}]}
  ]},
  {"date":"2026-02-07T13:52:00","exercises":[
    {"name":"Тяга сверху имитация подтягиваний","sets":[{"weight":"68","reps":"7"},{"weight":"68","reps":"7"},{"weight":"68","reps":"7"},{"weight":"68","reps":"7"}]},
    {"name":"Тяга блока к груди сидя узкий хват","sets":[{"weight":"58","reps":"10"},{"weight":"58","reps":"10"},{"weight":"58","reps":"10"},{"weight":"58","reps":"10"}]},
    {"name":"Тяга блока одной рукой сидя с доворотом","sets":[{"weight":"28","reps":"7"},{"weight":"28","reps":"7"},{"weight":"28","reps":"7"},{"weight":"28","reps":"7"}]},
    {"name":"Тяга гантели одной рукой в наклоне с упором","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]},
    {"name":"Бицепс штанга стоя молот с/сет","sets":[{"weight":"25","reps":"6"},{"weight":"25","reps":"6"},{"weight":"25","reps":"6"}]},
    {"name":"Бицепс з гриф мягкий блок стоя","sets":[{"weight":"27","reps":"5"},{"weight":"27","reps":"5"},{"weight":"27","reps":"5"},{"weight":"27","reps":"5"},{"weight":"27","reps":"5"}]}
  ]},
  {"date":"2026-02-11T11:32:00","exercises":[
    {"name":"Разгибание ног сидя статика","sets":[{"weight":"63","reps":"30"},{"weight":"63","reps":"30"}]},
    {"name":"Разгибание ног сидя","sets":[{"weight":"54","reps":"12"},{"weight":"54","reps":"12"},{"weight":"54","reps":"12"}]},
    {"name":"Сгибание ног лёжа","sets":[{"weight":"36","reps":"12"},{"weight":"36","reps":"12"},{"weight":"36","reps":"12"}]},
    {"name":"Приседания со штангой широкая постановка","sets":[{"weight":"60","reps":"6"},{"weight":"60","reps":"6"},{"weight":"60","reps":"6"},{"weight":"60","reps":"6"},{"weight":"60","reps":"6"}]},
    {"name":"Приводящие ног в тренажёре","sets":[{"weight":"58","reps":"8"},{"weight":"58","reps":"8"},{"weight":"58","reps":"8"}]},
    {"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"},{"weight":"22","reps":"10"}]},
    {"name":"Разводка гантелей сидя в стороны плечи","sets":[{"weight":"10","reps":"6"},{"weight":"10","reps":"6"},{"weight":"10","reps":"6"},{"weight":"10","reps":"6"}]},
    {"name":"Задние дельты лёжа разведение","sets":[{"weight":"10","reps":"10"},{"weight":"10","reps":"10"},{"weight":"10","reps":"10"}]},
    {"name":"Трицепс косичка разведение в стороны стоя","sets":[{"weight":"40","reps":"10"},{"weight":"40","reps":"10"},{"weight":"40","reps":"10"}]}
  ]},
  {"date":"2026-02-13T14:22:00","exercises":[
    {"name":"Румынская тяга со штангой","sets":[{"weight":"60","reps":"10"},{"weight":"60","reps":"10"},{"weight":"60","reps":"10"},{"weight":"60","reps":"10"},{"weight":"60","reps":"10"}]},
    {"name":"Жим гантелей сидя вверх плечи","sets":[{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"},{"weight":"22","reps":"8"}]},
    {"name":"Задние дельты стоя в наклоне","sets":[{"weight":"10","reps":"9"},{"weight":"10","reps":"9"},{"weight":"10","reps":"9"}]},
    {"name":"Обратное разведение в кроссовере наклон","sets":[{"weight":"9","reps":"9"},{"weight":"9","reps":"9"},{"weight":"9","reps":"9"}]},
    {"name":"Разводка гантелей стоя до горизонта плечи","sets":[{"weight":"10","reps":"9"},{"weight":"10","reps":"9"},{"weight":"10","reps":"9"}]},
    {"name":"Подъём гантелей перед собой стоя","sets":[{"weight":"6","reps":"9"},{"weight":"6","reps":"9"},{"weight":"6","reps":"9"}]},
    {"name":"Трицепс прямой блок","sets":[{"weight":"45","reps":"10"},{"weight":"45","reps":"10"},{"weight":"45","reps":"10"}]}
  ]}
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
    c.execute("DELETE FROM meta WHERE key='history_loaded'")
    c.execute("DELETE FROM workouts")
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
            write_workout_to_sheet(session["date"], valid)

        # Summary for trainer screenshot
        date_label = fmt_date(session["date"]) if session.get("date") else "сегодня"
        text = f"🏋️ *Тренировка {date_label}*\n\n"
        for i, r in enumerate(valid):
            ex_info = next((e for e in exercises if e["name"] == r["name"]), None)
            sets_count = ex_info["sets"] if ex_info else "?"
            reps_count = ex_info["reps"] if ex_info else "?"
            weight = r["sets"][0].get("weight","") if r["sets"] else ""
            weight_str = f"{weight}кг" if weight else "б/в"
            text += f"*{i+1}. {r['name']}*\n"
            text += f"   {sets_count}×{reps_count} | {weight_str}\n\n"
        text += "Отличная работа! 💪"

        session["mode"] = None
        session["current_idx"] = -1
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        return

    ex = exercises[idx]
    msg = format_exercise_prompt(ex, idx, len(exercises))

    # Build quick reply buttons based on previous result
    _, sets_str = get_exact_result(ex["name"])
    
    # Try to get weight from exact or similar match
    last_weight = None
    if sets_str:
        try:
            last_weight = float(sets_str.split("кг")[0].strip())
        except:
            pass
    
    if last_weight is None:
        # Try similar exercise
        _, sim_date, sim_sets = find_similar_exercise(ex["name"])
        if sim_sets:
            try:
                last_weight = float(sim_sets.split("кг")[0].strip())
            except:
                pass

    if last_weight is not None:
        # Generate range: -3 to +5 from last weight, step 1
        step = 1.0 if last_weight == int(last_weight) else 0.5
        weights = []
        w = last_weight - 3
        while w <= last_weight + 5:
            if w > 0:
                val = int(w) if w == int(w) else w
                weights.append(str(val))
            w += step
        # Group into rows of 4
        buttons = []
        row = []
        for i, wt in enumerate(weights):
            row.append(wt)
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append(["—"])
    else:
        # No history at all — only dash
        buttons = [["—"]]

    markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
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

async def cmd_whoop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("⏳ Получаю данные из Whoop...")
    data = await get_whoop_data()
    if data:
        await save_whoop_to_sheet(data)
        msg = format_whoop_message(data)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Не удалось получить данные. Проверь WHOOP_EMAIL и WHOOP_PASSWORD в Railway.")

async def daily_whoop_job(context):
    """Daily job at 13:00 MSK to fetch Whoop data."""
    try:
        data = await get_whoop_data()
        if data and ALLOWED_USER_ID:
            await save_whoop_to_sheet(data)
            msg = format_whoop_message(data)
            if msg:
                await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Daily whoop job error: {e}")

async def cmd_importsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("⏳ Читаю данные из Google Sheets...")
    count = import_from_sheet()
    if count:
        await update.message.reply_text(f"✅ Импортировано {count} тренировок из таблицы!")
    else:
        await update.message.reply_text("❌ Не удалось импортировать. Проверь таблицу.")

async def cmd_exportsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("⏳ Выгружаю историю в Google Sheets...")
    count = export_history_to_sheet()
    if count:
        await update.message.reply_text(f"✅ Выгружено {count} записей в таблицу!")
    else:
        await update.message.reply_text("❌ Не удалось подключиться к таблице. Проверь переменную GOOGLE_CREDENTIALS.")

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
    # Auto-restore from Google Sheets if local DB is empty
    conn = sqlite3.connect("workouts.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM workouts")
    count = c.fetchone()[0]
    conn.close()
    if count == 0:
        logger.info("Local DB empty, restoring from Google Sheets...")
        import_from_sheet()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("exportsheet", cmd_exportsheet))
    app.add_handler(CommandHandler("importsheet", cmd_importsheet))
    app.add_handler(CommandHandler("whoop", cmd_whoop))
    
    # Daily Whoop job at 13:00 MSK = 10:00 UTC
    app.job_queue.run_daily(daily_whoop_job, time=dtime(hour=10, minute=0))
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
