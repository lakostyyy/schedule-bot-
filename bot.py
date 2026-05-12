import logging
import os
import csv
import io
import urllib.request
from datetime import datetime, time as dtime
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВТЕ_ТОКЕН")
SPREADSHEET_ID = "1TH0xjDIvrexAU1B8bdIK5DxFMlRUd_nlYe5rDSyj3fU"
SHEET_GID = "1429881371"
CLASS_NAME = "10а"
TIMEZONE = pytz.timezone("Europe/Kyiv")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LESSON_TIMES = [
    (dtime(9, 0),  dtime(9, 45)),
    (dtime(9, 50), dtime(10, 35)),
    (dtime(10, 45), dtime(11, 30)),
    (dtime(11, 40), dtime(12, 20)),
    (dtime(12, 40), dtime(13, 20)),
    (dtime(13, 40), dtime(14, 20)),
    (dtime(14, 25), dtime(15, 10)),
    (dtime(15, 15), dtime(16, 0)),
]

BREAK_TIMES = [
    (dtime(9, 45),  dtime(9, 50),  5,  "перерва"),
    (dtime(10, 35), dtime(10, 45), 10, "перерва"),
    (dtime(11, 30), dtime(11, 40), 10, "перерва"),
    (dtime(12, 20), dtime(12, 40), 20, "обід"),
    (dtime(13, 20), dtime(13, 40), 20, "перерва"),
    (dtime(14, 20), dtime(14, 25), 5,  "перерва"),
    (dtime(15, 10), dtime(15, 15), 5,  "перерва"),
]

DAY_NAMES = {
    0: "ПОНЕДІЛОК",
    1: "ВІВТОРОК",
    2: "СЕРЕДА",
    3: "ЧЕТВЕР",
    4: "П'ЯТНИЦЯ",
}

FALLBACK_SCHEDULE = {
    "ПОНЕДІЛОК": {1:"Література",2:"Математика",3:"Історія України",4:"Англійська мова",5:"Хімія",6:"Фізична культура"},
    "ВІВТОРОК":  {1:"Фізика",2:"Література",3:"Математика",4:"Математика",5:"Англійська мова",6:"Українська мова"},
    "СЕРЕДА":    {1:"Проєкт менедж",2:"Проф орієнт",3:"Інформатика",4:"Інформатика",5:"Англійська мова",6:"Фізика"},
    "ЧЕТВЕР":    {1:"Українська мова",2:"Англійська мова",3:"Всесвітня історія",4:"Всесвітня історія",5:"Математика",6:"Біологія"},
    "П'ЯТНИЦЯ": {1:"Емпатика",2:"Англійська мова",3:"Українська мова",4:"Англ 1",5:"Хімія",6:"Захист України"},
}

ROOMS = {
    "ПОНЕДІЛОК": {1:"501",2:"206",3:"302",4:"205",5:"305",6:"—",7:"Шахи Сергій",8:"303"},
    "ВІВТОРОК":  {1:"304",2:"204",3:"206",4:"206",5:"205",6:"203",7:"306",8:"Стадіон"},
    "СЕРЕДА":    {1:"04",2:"04",3:"301",4:"301",5:"205",6:"304",7:"303",8:"203"},
    "ЧЕТВЕР":    {1:"204",2:"205",3:"204",4:"204",5:"Сушка",6:"206",7:"206",8:"—"},
    "П'ЯТНИЦЯ": {1:"501",2:"205",3:"304",4:"306",5:"305",6:"206",7:"Шахи Сергій",8:"—"},
}

_cache = {}
_cache_date = None


def fetch_csv():
    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={SHEET_GID}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        logger.error(f"CSV error: {e}")
        return None


def parse_csv(content):
    rows = list(csv.reader(io.StringIO(content)))
    schedule = {d: {} for d in DAY_NAMES.values()}
    current_day = None
    class_col = None
    day_keywords = {
        "ПОНЕДІЛОК": "ПОНЕДІЛОК",
        "ВІВТОРОК":  "ВІВТОРОК",
        "СЕРЕДА":    "СЕРЕДА",
        "ЧЕТВЕР":    "ЧЕТВЕР",
        "П'ЯТНИЦЯ": "П'ЯТНИЦЯ",
        "ПЯТНИЦЯ":  "П'ЯТНИЦЯ",
    }
    for ri, row in enumerate(rows):
        joined = " ".join(row).upper().strip()
        for kw, day in day_keywords.items():
            if kw in joined and len(joined) < 60:
                current_day = day
                class_col = None
                for fr in rows[ri:ri+5]:
                    for ci, cell in enumerate(fr):
                        if CLASS_NAME.lower() in cell.lower():
                            class_col = ci
                            break
                    if class_col is not None:
                        break
                break
        if current_day is None or class_col is None:
            continue
        first = row[0].strip() if row else ""
        if first.isdigit() and 1 <= int(first) <= 8:
            num = int(first)
            if class_col < len(row):
                subj = row[class_col].strip()
                if subj and subj not in ["", "-", "—"]:
                    schedule[current_day][num] = subj
    total = sum(len(v) for v in schedule.values())
    return schedule if total >= 5 else FALLBACK_SCHEDULE


def get_schedule():
    global _cache, _cache_date
    today = datetime.now(TIMEZONE).date()
    if _cache_date == today and _cache:
        return _cache
    csv_data = fetch_csv()
    _cache = parse_csv(csv_data) if csv_data else FALLBACK_SCHEDULE
    _cache_date = today
    return _cache


def t2m(t):
    return t.hour * 60 + t.minute


def get_status(schedule):
    now = datetime.now(TIMEZONE)
    nm = t2m(now.time())
    wd = now.weekday()
    if wd >= 5:
        return {"type": "weekend"}
    day = DAY_NAMES[wd]
    ds = schedule.get(day, {})
    dr = ROOMS.get(day, {})
    for i, (s, e) in enumerate(LESSON_TIMES):
        if t2m(s) <= nm < t2m(e):
            return {
                "type": "lesson",
                "num": i+1,
                "subject": ds.get(i+1, "—"),
                "room": dr.get(i+1, ""),
                "remaining": t2m(e) - nm,
                "next": ds.get(i+2),
                "next_room": dr.get(i+2, ""),
                "break": BREAK_TIMES[i] if i < len(BREAK_TIMES) else None
            }
    for i, (s, e, l, lb) in enumerate(BREAK_TIMES):
        if t2m(s) <= nm < t2m(e):
            return {
                "type": "break",
                "label": lb,
                "remaining": t2m(e) - nm,
                "next_num": i+2,
                "next": ds.get(i+2, "—"),
                "next_room": dr.get(i+2, ""),
            }
    if nm < t2m(LESSON_TIMES[0][0]):
        return {"type": "before", "first": ds.get(1, "—"), "first_room": dr.get(1, ""), "min": t2m(LESSON_TIMES[0][0]) - nm}
    return {"type": "after"}


def fmt_status(s):
    t = s["type"]
    if t == "weekend":
        return "🎉 Сьогодні вихідний!"
    if t == "lesson":
        room = s.get("room", "")
        room_str = f" 🚪 Каб. *{room}*" if room and room != "—" else ""
        m = f"📚 *{s['num']} урок:* {s['subject']}{room_str}\n⏳ Залишилось: *{s['remaining']} хв*"
        if s["break"]:
            _, _, l, lb = s["break"]
            m += f"\n{'🍽' if lb=='обід' else '☕'} Далі: {lb} ({l} хв)"
        if s["next"]:
            next_room = s.get("next_room", "")
            next_room_str = f" (каб. {next_room})" if next_room and next_room != "—" else ""
            m += f"\n📖 Після: {s['next']}{next_room_str}"
        return m
    if t == "break":
        e = "🍽" if s["label"] == "обід" else "☕"
        room = s.get("next_room", "")
        room_str = f" (каб. {room})" if room and room != "—" else ""
        return f"{e} *{s['label'].capitalize()}*\n⏳ Залишилось: *{s['remaining']} хв*\n📚 Далі: {s['next_num']} урок — {s['next']}{room_str}"
    if t == "before":
        room = s.get("first_room", "")
        room_str = f" (каб. {room})" if room and room != "—" else ""
        return f"🔔 До першого уроку: *{s['min']} хв*\n📖 Перший: {s['first']}{room_str}"
    return "🏠 Уроки закінчились!"


def fmt_day(day, ds):
    if not ds:
        return f"📅 *{day}*\nНемає даних"
    dr = ROOMS.get(day, {})
    msg = f"📅 *{day}*\n\n"
    for i, (s, e) in enumerate(LESSON_TIMES):
        num = i + 1
        subj = ds.get(num, "—")
        room = dr.get(num, "")
        room_str = f" 🚪{room}" if room and room != "—" else ""
        msg += f"`{num}.` {s.strftime('%H:%M')}–{e.strftime('%H:%M')} {subj}{room_str}\n"
        if i < len(BREAK_TIMES):
            _, _, l, lb = BREAK_TIMES[i]
            msg += f"     {'🍽' if lb=='обід' else '☕'} {lb} {l} хв\n"
    return msg


LUNCH_MENU = {
    "ПОНЕДІЛОК": {
        "перекус": "🥪 Бутерброди з сиром, шинкою, яблуко, апельсин, банан, печиво, компот",
        "обід": "🍲 Суп курячий з яйцем та грінками\n🍝 Мак енд чіз / Булгур\n🍗 Чілі корн карне / фрикадельки курячі парові\n🥗 Салат з маринованих огірків та капусти",
        "полуденок": "🥞 Млинці з джемом, сиром, узвар",
    },
    "ВІВТОРОК": {
        "перекус": "🧁 Домашній кекс з родзинками, банан, апельсин, яблуко, узвар",
        "обід": "🍲 Борщ червоний український зі сметаною\n🍚 Плов з булгура та свининою / макарони\n🥦 Овочі парові / салат з червоної капусти з соусом «вінігрет»",
        "полуденок": "🍎 Шарлотка з яблуками, компот ягідний",
    },
    "СЕРЕДА": {
        "перекус": "🍳 Фрітата з сиром, печиво, фрукти, компот",
        "обід": "🍲 Сочевичний суп-пюре\n🥟 Пельмені домашні зі сметаною, кетчупом / гречка з вершковим маслом\n🥔 Вареники з картоплею / куряче філе печене\n🥗 Вінегрет",
        "полуденок": "🥞 Панкейк з джемом або сметаною, компот ягідний",
    },
    "ЧЕТВЕР": {
        "перекус": "🥧 Пиріг закритий з яйцем та шпинатом, яблука, банани, апельсини, узвар",
        "обід": "🍲 Мінестроне\n🍚 Рис розсипчастий / відварна картопля з вершковим маслом\n🐟 Рибні стіки / котлети курячі\n🥕 Морква по-корейськи / Капуста квашена",
        "полуденок": "🥐 Слойка з начинкою, компот ягідний",
    },
    "П'ЯТНИЦЯ": {
        "перекус": "🥧 Пиріг ягідний, яблуко, банан, апельсин, компот ягідний",
        "обід": "🍲 Суп квасолевий\n🌾 Булгур / макарони з сиром\n🍗 Ліниві голубці / філе куряче печене\n🥗 Асорті овочеве",
        "полуденок": "🧀 Запіканка сирна із сметаною, компот ягідний",
    },
}


async def cmd_lunch(u: Update, c):
    wd = datetime.now(TIMEZONE).weekday()
    if wd >= 5:
        await u.message.reply_text("🎉 Сьогодні вихідний — їдальня не працює!")
        return
    day = DAY_NAMES[wd]
    menu = LUNCH_MENU.get(day, {})
    msg = f"🍽 *Меню на {day}*\n\n"
    msg += f"☕ *Перекус:*\n{menu.get('перекус', '—')}\n\n"
    msg += f"🍴 *Обід:*\n{menu.get('обід', '—')}\n\n"
    msg += f"🍰 *Полуденок:*\n{menu.get('полуденок', '—')}"
    await u.message.reply_text(msg, parse_mode="Markdown")


async def cmd_start(u: Update, c):
    await u.message.reply_text(
        "👋 Привіт! Бот розкладу *10А*\n\n"
        "/now — що зараз\n/today — сьогодні\n/tomorrow — завтра\n"
        "/week — весь тиждень\n/mon /tue /wed /thu /fri — конкретний день\n"
        "/lunch — меню їдальні на сьогодні",
        parse_mode="Markdown"
    )


async def cmd_now(u: Update, c):
    await u.message.reply_text(fmt_status(get_status(get_schedule())), parse_mode="Markdown")


async def cmd_today(u: Update, c):
    wd = datetime.now(TIMEZONE).weekday()
    if wd >= 5:
        await u.message.reply_text("🎉 Вихідний!")
        return
    day = DAY_NAMES[wd]
    await u.message.reply_text(fmt_day(day, get_schedule().get(day, {})), parse_mode="Markdown")


async def cmd_tomorrow(u: Update, c):
    wd = (datetime.now(TIMEZONE).weekday() + 1) % 7
    if wd >= 5:
        await u.message.reply_text("🎉 Завтра вихідний!")
        return
    day = DAY_NAMES[wd]
    await u.message.reply_text(fmt_day(day, get_schedule().get(day, {})), parse_mode="Markdown")


async def cmd_week(u: Update, c):
    s = get_schedule()
    text = "\n".join(fmt_day(d, s.get(d, {})) for d in DAY_NAMES.values())
    await u.message.reply_text(text, parse_mode="Markdown")


async def cmd_day(u: Update, c, di: int):
    day = DAY_NAMES[di]
    await u.message.reply_text(fmt_day(day, get_schedule().get(day, {})), parse_mode="Markdown")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("mon", lambda u, c: cmd_day(u, c, 0)))
    app.add_handler(CommandHandler("tue", lambda u, c: cmd_day(u, c, 1)))
    app.add_handler(CommandHandler("wed", lambda u, c: cmd_day(u, c, 2)))
    app.add_handler(CommandHandler("thu", lambda u, c: cmd_day(u, c, 3)))
    app.add_handler(CommandHandler("fri", lambda u, c: cmd_day(u, c, 4)))
    app.add_handler(CommandHandler("lunch", cmd_lunch))
    logger.info("Бот запущено!")
    app.run_polling()


if __name__ == "__main__":
    main()
