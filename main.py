import json
import logging
import asyncio
import os
import requests
from datetime import datetime
from typing import Set, Dict
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# الإعدادات
BOT_TOKEN = "8329563352:AAFO7RcTJoBFzV7llClLi-QijzSWHMR75Rg"
CHECK_INTERVAL = 300  # كل 5 دقائق
SUB_FILE = "subscribers.json"
STATE_FILE = "last_known_dates.json"

CALENDARS = {
    "الجزائر العاصمة": "https://appointment.mosaicvisa.com/calendar/9",
    "وهران": "https://appointment.mosaicvisa.com/calendar/7",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# إعداد السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# إدارة المشتركين (أفراد، مجموعات، قنوات)
def load_subs() -> Set[int]:
    if os.path.exists(SUB_FILE):
        try:
            with open(SUB_FILE, "r") as f:
                return set(json.load(f))
        except Exception as e:
            logger.error(f"Error loading subscribers: {e}")
    return set()

def save_subs(data: Set[int]):
    try:
        with open(SUB_FILE, "w") as f:
            json.dump(list(data), f)
    except Exception as e:
        logger.error(f"Error saving subscribers: {e}")

# إدارة حالة المواعيد
def load_state() -> Dict[str, list]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading state: {e}")
    return {city: [] for city in CALENDARS}

def save_state(state: Dict[str, list]):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

# جلب وفحص المواعيد
def fetch_available_dates(url: str) -> list:
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.find_all("tr")
        available_dates = []
        
        for row in rows:
            text = row.get_text(" ", strip=True)
            if "Available" in text:
                available_dates.append(text)
            elif any(c.isdigit() for c in text) and "Reserved" not in text and len(text) > 5:
                available_dates.append(text)
                
        return available_dates
    except Exception as e:
        logger.error(f"Error fetching dates from {url}: {e}")
        return []

# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subs = load_subs()
    if chat_id not in subs:
        subs.add(chat_id)
        save_subs(subs)
        welcome_msg = (
            "✅ تم تفعيل الإشعارات لهذه الدردشة!\n\n"
            "سأرسل تنبيهاً هنا عند توفر مواعيد جديدة في:\n"
            "• وهران (تقويم 7)\n"
            "• الجزائر العاصمة (تقويم 9)\n\n"
            "الأوامر المتاحة:\n"
            "/stop - إيقاف الإشعارات\n"
            "/status - حالة البوت\n"
            "/dates - عرض آخر المواعيد المعروفة"
        )
    else:
        welcome_msg = "الإشعارات مفعلة بالفعل لهذه الدردشة!"
    await update.message.reply_text(welcome_msg)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subs = load_subs()
    if chat_id in subs:
        subs.discard(chat_id)
        save_subs(subs)
        await update.message.reply_text("تم إيقاف الإشعارات لهذه الدردشة ❌.")
    else:
        await update.message.reply_text("الإشعارات غير مفعلة أصلاً.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت يعمل بنجاح 🟢 ويقوم بمراقبة المواعيد دورياً.")

async def get_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    msg = "📅 آخر مواعيد تم رصدها:\n\n"
    for city, dates in state.items():
        msg += f"📍 {city}:\n"
        if dates:
            msg += "\n".join([f"• {d}" for d in dates])
        else:
            msg += "لا توجد مواعيد متاحة حالياً."
        msg += "\n\n"
    await update.message.reply_text(msg)

# معالج لحفظ الدردشة تلقائياً عند إضافة البوت لمجموعة أو قناة
async def on_new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subs = load_subs()
    if chat_id not in subs:
        subs.add(chat_id)
        save_subs(subs)
        logger.info(f"New chat registered: {chat_id} ({update.effective_chat.type})")
        try:
            await context.bot.send_message(
                chat_id=chat_id, 
                text="✅ شكراً لإضافتي! سأقوم بإرسال إشعارات مواعيد فيزا تركيا هنا تلقائياً."
            )
        except:
            pass

# المهمة الدورية باستخدام JobQueue
async def check_for_updates(context: ContextTypes.DEFAULT_TYPE):
    subs = load_subs()
    if not subs:
        return

    last_state = load_state()
    new_state = {}
    notifications = []

    for city, url in CALENDARS.items():
        current_dates = fetch_available_dates(url)
        new_state[city] = current_dates
        
        old_dates = set(last_state.get(city, []))
        truly_new = [d for d in current_dates if d not in old_dates]
        
        if truly_new:
            notifications.append(f"🚨 مواعيد جديدة متاحة في {city}:\n" + "\n".join([f"✅ {d}" for d in truly_new]))

    if notifications:
        full_msg = "\n\n".join(notifications) + "\n\n🏃‍♂️ سارع بالحجز فوراً عبر الموقع!"
        for chat_id in subs:
            try:
                await context.bot.send_message(chat_id=chat_id, text=full_msg)
            except Exception as e:
                # إذا قام المستخدم بحظر البوت أو تمت إزالته من المجموعة، نحذفه من القائمة
                if "Forbidden" in str(e) or "chat not found" in str(e).lower():
                    subs.discard(chat_id)
                    save_subs(subs)
                logger.error(f"Failed to send to {chat_id}: {e}")
        save_state(new_state)

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("dates", get_dates))

    # معالجة الرسائل الجديدة لحفظ الدردشات (المجموعات والقنوات)
    # ملاحظة: بالنسبة للقنوات، يحتاج البوت أن يكون مديراً (Admin)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_new_chat))

    # جدولة المهمة الدورية
    job_queue = application.job_queue
    job_queue.run_repeating(check_for_updates, interval=CHECK_INTERVAL, first=10)

    # تشغيل البوت
    logger.info("Bot is starting with Group/Channel support...")
    application.run_polling()

if __name__ == "__main__":
    main()
