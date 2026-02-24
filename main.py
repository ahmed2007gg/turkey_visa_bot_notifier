import json
import logging
import asyncio
import os
import re
import requests
from datetime import datetime
from typing import Set, Dict
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

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

# إدارة المشتركين
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

# إدارة حالة المواعيد (لمنع تكرار الإشعارات لنفس الموعد)
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
            logger.error(f"Failed to fetch {url}, status: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.find_all("tr")
        available_dates = []
        
        for row in rows:
            text = row.get_text(" ", strip=True)
            # المواعيد المتاحة عادة تحتوي على كلمة "Available" أو لا تحتوي على "Reserved"
            # بناءً على الكود السابق للمستخدم والتحليل:
            if "Available" in text:
                available_dates.append(text)
            elif any(c.isdigit() for c in text) and "Reserved" not in text and len(text) > 5:
                # هذا النمط للأيام التي تظهر كتاريخ فقط دون "Reserved"
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
            "✅ تم الاشتراك في الإشعارات!\n\n"
            "سأرسل لك تنبيهاً عند توفر مواعيد جديدة في:\n"
            "• وهران (تقويم 7)\n"
            "• الجزائر العاصمة (تقويم 9)\n\n"
            "الأوامر المتاحة:\n"
            "/stop - إيقاف الإشعارات\n"
            "/status - حالة البوت\n"
            "/dates - عرض آخر المواعيد المعروفة\n"
            "/help - المساعدة"
        )
    else:
        welcome_msg = "أنت مشترك بالفعل! سأوافيك بكل جديد فور توفره."
    
    await update.message.reply_text(welcome_msg)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subs = load_subs()
    if chat_id in subs:
        subs.discard(chat_id)
        save_subs(subs)
        await update.message.reply_text("تم إلغاء الاشتراك ❌. لن تصلك إشعارات بعد الآن.")
    else:
        await update.message.reply_text("أنت غير مشترك أصلاً.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت يعمل بنجاح 🟢 ويقوم بفحص المواعيد كل 5 دقائق.")

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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📋 أوامر البوت:\n\n"
        "/start - الاشتراك في الإشعارات\n"
        "/stop - إيقاف الإشعارات\n"
        "/status - حالة البوت\n"
        "/dates - عرض آخر المواعيد المعروفة\n"
        "/help - عرض هذه الرسالة"
    )
    await update.message.reply_text(help_text)

# المهمة الدورية للفحص
async def check_loop(app: Application):
    logger.info("Starting check loop...")
    while True:
        try:
            subs = load_subs()
            if not subs:
                logger.info("No subscribers, skipping check.")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            last_state = load_state()
            new_state = {}
            notifications = []

            for city, url in CALENDARS.items():
                current_dates = fetch_available_dates(url)
                new_state[city] = current_dates
                
                # تحديد المواعيد الجديدة فعلياً (التي لم تكن موجودة في الفحص السابق)
                old_dates = set(last_state.get(city, []))
                truly_new = [d for d in current_dates if d not in old_dates]
                
                if truly_new:
                    notifications.append(f"🚨 مواعيد جديدة متاحة في {city}:\n" + "\n".join([f"✅ {d}" for d in truly_new]))

            if notifications:
                full_msg = "\n\n".join(notifications) + "\n\n🏃‍♂️ سارع بالحجز فوراً عبر الموقع!"
                for chat_id in subs:
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=full_msg)
                    except Exception as e:
                        logger.error(f"Failed to send message to {chat_id}: {e}")
                
                # تحديث الحالة فقط عند وجود تغيير
                save_state(new_state)
            else:
                logger.info("No new dates found.")

        except Exception as e:
            logger.error(f"Error in check loop: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)

# تشغيل البوت
async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        return

    # بناء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()

    # إضافة الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("dates", get_dates))
    application.add_handler(CommandHandler("help", help_command))

    # بدء المهمة الدورية في الخلفية
    asyncio.create_task(check_loop(application))

    # تشغيل البوت
    logger.info("Bot is starting...")
    await application.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}")
