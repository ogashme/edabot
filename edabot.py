#!/usr/bin/env python3
# edabot.py
# EdaBot Premium - Telegram diet bot (Uz/Ru), image + text, JSON storage.
# Requirements: pip install pytelegrambotapi openai python-dateutil
# Usage: edit TELEGRAM_TOKEN and OPENAI_API_KEY, then run: python edabot.py

import telebot
import openai
import json
import os
import re
from datetime import date, datetime
from dateutil import relativedelta

# ========== CONFIG (PUT YOUR KEYS HERE) ==========
TELEGRAM_TOKEN = "8486086116:AAGHEttX4xFVrLTOJSIe1nxWAXlv9aE_G40"
OPENAI_API_KEY = "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"

# Model names: adjust if needed in your OpenAI account
MODEL_TEXT = "gpt-4-turbo"       # for text parsing
MODEL_IMAGE = "gpt-4-turbo"      # vision-capable model (change if your account uses different name)

DATA_FILE = "user_data.json"
IMAGES_DIR = "images"

os.makedirs(IMAGES_DIR, exist_ok=True)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai.api_key = OPENAI_API_KEY

# In-progress setup states
pending_profiles = {}  # user_id -> state dict

# ----------------- Utilities -----------------
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def calculate_age(birth_str):
    try:
        if "-" in birth_str:
            b = datetime.strptime(birth_str, "%Y-%m-%d").date()
        elif "." in birth_str:
            b = datetime.strptime(birth_str, "%d.%m.%Y").date()
        else:
            # treat as year or as numeric age
            if len(birth_str) == 4 and birth_str.isdigit():
                b = datetime.strptime(birth_str, "%Y").date()
            else:
                return int(birth_str)
        today = date.today()
        rd = relativedelta.relativedelta(today, b)
        return rd.years
    except Exception:
        try:
            return int(birth_str)
        except Exception:
            return None

def compute_bmr_tdee(sex, age, weight, height, activity):
    if sex == 'male':
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    factor = 1.2 if activity == 'low' else 1.55 if activity == 'medium' else 1.725
    tdee = bmr * factor
    return round(bmr), round(tdee)

def get_today_str():
    return str(date.today())

def ensure_user(data, user_id):
    if user_id not in data:
        data[user_id] = {"profile": None, "history": {}}
    return data

def parse_kcal_from_text(text):
    text_low = text.lower().replace(",", ".")
    m = re.search(r"(\d{1,5})\s?kcal", text_low)
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{1,5})\s?cal\b", text_low)
    if m2:
        return int(m2.group(1))
    m3 = re.search(r"(\d{2,5})", text_low)
    if m3:
        # heuristic: first reasonably large number is kcal
        return int(m3.group(1))
    return 0

# --------------- Messages (Uz / Ru) ---------------
MESS = {
    "welcome": {
        "uz": "🍎 Salom! Men EdaBot — dietangizni kuzatuvchi botman.\nTilni tanlang: uz yoki ru (masalan: uz)",
        "ru": "🍎 Привет! Я EdaBot — бот для отслеживания питания.\nВыберите язык: uz или ru (например: ru)"
    },
    "ask_sex": {
        "uz": "Jinsingizni kiriting: erkak yoki ayol",
        "ru": "Введите ваш пол: мужской или женский"
    },
    "ask_birth": {
        "uz": "Tug‘ilgan yilingizni yoki sanangizni kiriting (YYYY yoki DD.MM.YYYY):",
        "ru": "Введите год или дату рождения (YYYY или DD.MM.YYYY):"
    },
    "ask_weight": {
        "uz": "Vazningizni (kg) yozing (misol: 72):",
        "ru": "Введите ваш вес (кг), например: 72:"
    },
    "ask_height": {
        "uz": "Bo‘yingizni (sm) yozing (misol: 175):",
        "ru": "Введите ваш рост (см), например: 175:"
    },
    "ask_activity": {
        "uz": "Faollik darajangizni tanlang: kam / o'rtacha / yuqori",
        "ru": "Выберите уровень активности: низкий / средний / высокий"
    },
    "ask_goal": {
        "uz": "Maqsadingizni tanlang: ozish / saqlash / oshish",
        "ru": "Выберите цель: похудение / поддержание / набор"
    },
    "profile_done": {
        "uz": "✅ Profil saqlandi! Endi ovqat ayting (matn yoki rasm yuboring). /hisobot buyrug‘i orqali kunlik summani ko‘ring.",
        "ru": "✅ Профиль сохранен! Теперь отправьте блюдо (текст или фото). Команда /hisobot покажет суммарную калорийность за день."
    },
    "no_profile": {
        "uz": "Profil topilmadi. Iltimos /start orqali profildan boshlang.",
        "ru": "Профиль не найден. Пожалуйста, начните с /start."
    },
    "today_report": {
        "uz": "📊 Bugungi jami: {total} kcal. Maqsad: {goal} kcal. Qolgan: {left} kcal.",
        "ru": "📊 Сегодня всего: {total} kcal. Цель: {goal} kcal. Осталось: {left} kcal."
    }
}

# --------------- Handlers -----------------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = str(message.from_user.id)
    pending_profiles[user_id] = {"step": "lang"}
    bot.reply_to(message, MESS["welcome"]["uz"])

@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    data = load_data()
    user_id = str(message.from_user.id)
    if user_id in data and data[user_id].get("profile"):
        p = data[user_id]["profile"]
        lang = p.get("lang", "uz")
        if lang == "ru":
            txt = (f"Профиль:\nПол: {p.get('sex')}\nВозраст: {p.get('age')}\nВес: {p.get('weight')} kg\n"
                   f"Рост: {p.get('height')} cm\nАктивность: {p.get('activity')}\nЦель: {p.get('goal')}\n"
                   f"Рекомендуемая калорийность: {p.get('recommended')} kcal")
        else:
            txt = (f"Profil:\nJins: {p.get('sex')}\nYosh: {p.get('age')}\nVazn: {p.get('weight')} kg\n"
                   f"Bo'y: {p.get('height')} cm\nFaollik: {p.get('activity')}\nMaqsad: {p.get('goal')}\n"
                   f"Tavsiya: {p.get('recommended')} kcal")
        bot.reply_to(message, txt)
    else:
        bot.reply_to(message, MESS["no_profile"]["uz"])

@bot.message_handler(commands=['hisobot'])
def cmd_report(message):
    data = load_data()
    user_id = str(message.from_user.id)
    if user_id not in data or not data[user_id].get("profile"):
        bot.reply_to(message, MESS["no_profile"]["uz"])
        return
    today = get_today_str()
    total = 0
    rec = data[user_id]["profile"].get("recommended", 0)
    lang = data[user_id]["profile"].get("lang", "uz")
    entries = data[user_id].get("history", {}).get(today, [])
    for e in entries:
        total += e.get("kcal", 0)
    left = rec - total
    if lang == "ru":
        bot.reply_to(message, MESS["today_report"]["ru"].format(total=total, goal=rec, left=left))
    else:
        bot.reply_to(message, MESS["today_report"]["uz"].format(total=total, goal=rec, left=left))

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    user_id = str(message.from_user.id)
    text = message.text.strip()
    low = text.lower()
    # Setup flow
    if user_id in pending_profiles:
        state = pending_profiles[user_id]
        step = state.get("step")
        # LANGUAGE
        if step == "lang":
            if low in ["uz", "uzbek", "o'zbek", "uzbekcha"]:
                state["lang"] = "uz"
            elif low in ["ru", "rus", "рус"]:
                state["lang"] = "ru"
            else:
                state["lang"] = "uz"
            state["step"] = "sex"
            bot.reply_to(message, MESS["ask_sex"][state["lang"]])
            return
        # SEX
        if step == "sex":
            lang = state.get("lang", "uz")
            if low in ["erkak", "male", "m", "мужчина", "мужской", "male"]:
                state["sex"] = "male"
            elif low in ["ayol", "female", "f", "женщина", "женский", "female"]:
                state["sex"] = "female"
            else:
                bot.reply_to(message, MESS["ask_sex"][lang])
                return
            state["step"] = "birth"
            bot.reply_to(message, MESS["ask_birth"][lang])
            return
        # BIRTH / AGE
        if step == "birth":
            lang = state.get("lang", "uz")
            age = calculate_age(text)
            if age is None:
                bot.reply_to(message, MESS["ask_birth"][lang])
                return
            state["age"] = age
            state["step"] = "weight"
            bot.reply_to(message, MESS["ask_weight"][lang])
            return
        # WEIGHT
        if step == "weight":
            lang = state.get("lang", "uz")
            try:
                w = float(text.replace(",", "."))
                state["weight"] = w
                state["step"] = "height"
                bot.reply_to(message, MESS["ask_height"][lang])
                return
            except Exception:
                bot.reply_to(message, MESS["ask_weight"][lang])
                return
        # HEIGHT
        if step == "height":
            lang = state.get("lang", "uz")
            try:
                h = float(text.replace(",", "."))
                state["height"] = h
                state["step"] = "activity"
                bot.reply_to(message, MESS["ask_activity"][lang])
                return
            except Exception:
                bot.reply_to(message, MESS["ask_height"][lang])
                return
        # ACTIVITY
        if step == "activity":
            lang = state.get("lang", "uz")
            if low in ["kam", "low", "низкий", "nizkiy"]:
                a = "low"
            elif low in ["o'rtacha", "ortacha", "medium", "средний", "sredniy"]:
                a = "medium"
            elif low in ["yuqori", "yuq", "high", "высокий"]:
                a = "high"
            else:
                bot.reply_to(message, MESS["ask_activity"][lang])
                return
            state["activity"] = a
            state["step"] = "goal"
            bot.reply_to(message, MESS["ask_goal"][lang])
            return
        # GOAL
        if step == "goal":
            lang = state.get("lang", "uz")
            if low in ["ozish", "pohudenie", "похудение", "loss"]:
                g = "loss"
            elif low in ["saqlash", "saqlab turish", "support", "поддержание", "maintain"]:
                g = "maintain"
            elif low in ["oshish", "kilo olish", "gain", "набор"]:
                g = "gain"
            else:
                bot.reply_to(message, MESS["ask_goal"][lang])
                return
            state["goal"] = g
            data = load_data()
            ensure_user(data, user_id)
            sex = state.get("sex")
            age = int(state.get("age"))
            weight = float(state.get("weight"))
            height = float(state.get("height"))
            activity = state.get("activity")
            bmr, tdee = compute_bmr_tdee(sex, age, weight, height, activity)
            if g == "loss":
                recommended = max(1000, round(tdee - 500))
            elif g == "gain":
                recommended = round(tdee + 500)
            else:
                recommended = round(tdee)
            profile = {
                "lang": state.get("lang", "uz"),
                "sex": sex,
                "age": age,
                "weight": weight,
                "height": height,
                "activity": activity,
                "goal": g,
                "bmr": bmr,
                "tdee": tdee,
                "recommended": recommended
            }
            data[user_id]["profile"] = profile
            save_data(data)
            pending_profiles.pop(user_id, None)
            bot.reply_to(message, MESS["profile_done"][profile["lang"]])
            return

    # If not in setup flow - treat as food description
    data = load_data()
    if user_id not in data or not data[user_id].get("profile"):
        bot.reply_to(message, MESS["no_profile"]["uz"])
        return
    profile = data[user_id]["profile"]
    lang = profile.get("lang", "uz")

    # Call OpenAI to estimate kcal and macronutrients
    prompt_system = ("You are a professional dietitian. When user sends food + portion, respond in the user's language "
                     "with short lines: 'Item — NUMBER kcal, P:xxg F:xxg C:xxg' and ensure kcal is an integer followed by 'kcal'.")
    prompt_user = f"User input: {text}\nReturn only the items with kcal and macros in short format."

    try:
        response = openai.ChatCompletion.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ],
            max_tokens=250
        )
        answer = response.choices[0].message["content"].strip()
    except Exception as e:
        answer = f"OpenAI error: {e}"
    kcal = parse_kcal_from_text(answer)

    # Save entry
    today = get_today_str()
    ensure_user(data, user_id)
    user_hist = data[user_id].setdefault("history", {})
    day_list = user_hist.setdefault(today, [])
    entry = {
        "time": datetime.now().isoformat(),
        "input": text,
        "kcal": kcal,
        "detail": answer
    }
    day_list.append(entry)
    save_data(data)

    if lang == "ru":
        bot.reply_to(message, f"🍽️ {answer}\n\n📈 Сегодня: {sum(x.get('kcal',0) for x in day_list)} kcal (Рекомендация: {profile.get('recommended')} kcal)")
    else:
        bot.reply_to(message, f"🍽️ {answer}\n\n📈 Bugun: {sum(x.get('kcal',0) for x in day_list)} kcal (Tavsiya: {profile.get('recommended')} kcal)")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = str(message.from_user.id)
    data = load_data()
    if user_id not in data or not data[user_id].get("profile"):
        bot.reply_to(message, MESS["no_profile"]["uz"])
        return
    profile = data[user_id]["profile"]
    lang = profile.get("lang", "uz")

    # Download highest resolution photo
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    filename = f"{user_id}_{int(datetime.now().timestamp())}.jpg"
    path = os.path.join(IMAGES_DIR, filename)
    with open(path, "wb") as f:
        f.write(downloaded)

    # Build accessible URL for the image (OpenAI must be able to fetch it)
    # NOTE: this works if your machine/server is publicly accessible or Telegram file URL is reachable by OpenAI.
    image_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"

    prompt_system = ("You are a dietitian that analyzes food photos. Identify visible foods and estimate kcal for reasonable portion sizes. "
                     "Return short lines: 'Item — NUMBER kcal, P:xxg F:xxg C:xxg'. Respond in the user's language.")
    prompt_user = f"Analyze the image: {image_url}\nReturn items and approximate kcal and macros."

    try:
        response = openai.ChatCompletion.create(
            model=MODEL_IMAGE,
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ],
            max_tokens=400
        )
        answer = response.choices[0].message["content"].strip()
    except Exception as e:
        answer = f"Image analysis failed: {e}"

    kcal = parse_kcal_from_text(answer)

    # Save entry with image path
    today = get_today_str()
    ensure_user(data, user_id)
    user_hist = data[user_id].setdefault("history", {})
    day_list = user_hist.setdefault(today, [])
    entry = {
        "time": datetime.now().isoformat(),
        "input": f"photo:{filename}",
        "image_path": path,
        "kcal": kcal,
        "detail": answer
    }
    day_list.append(entry)
    save_data(data)

    if lang == "ru":
        bot.reply_to(message, f"🖼️ Анализ:\n{answer}\n\n📈 Сегодня: {sum(x.get('kcal',0) for x in day_list)} kcal (Рекомендация: {profile.get('recommended')} kcal)")
    else:
        bot.reply_to(message, f"🖼️ Tahlil:\n{answer}\n\n📈 Bugun: {sum(x.get('kcal',0) for x in day_list)} kcal (Tavsiya: {profile.get('recommended')} kcal)")

# --------------- Start polling ---------------
if __name__ == "__main__":
    print("EdaBot ishga tushmoqda...")
    try:
        bot.polling(none_stop=True)
    except KeyboardInterrupt:
        print("To'xtatildi.")
