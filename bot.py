import os
from pymongo import MongoClient
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)
from telegram import Update, ReplyKeyboardMarkup

# خواندن متغیرهای محیطی
MONGODB_URI = os.getenv("MONGODB_URI")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PRIVATE_GROUP_CHAT_ID = int(os.getenv("PRIVATE_GROUP_CHAT_ID"))

client = MongoClient(MONGODB_URI)
db = client["energy_club"]
collection = db["registrations"]

(
    COURSE_SELECTION,
    NAME_FA, NAME_EN, FIELD, PHONE, NATIONAL_CODE, STUDENT_ID
) = range(7)

fields_keyboard = [
    ["⚡️ 1- مهندسی انرژی", "🔌 2- مهندسی برق", "💻 3- مهندسی کامپیوتر"],
    ["🧪 4- مهندسی شیمی", "🏗️ 5- مهندسی عمران", "🏭 6- مهندسی صنایع"],
    ["📐 7- ریاضیات و کاربردها", "🖥️ 8- علوم کامپیوتر", "🛢️ 9- مهندسی نفت"]
]

active_courses = [
    "1- بازدید از نیروگاه علی آباد"
]

async def courses_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not active_courses:
        await update.message.reply_text("اکنون دوره فعالی در دسترس نیست.")
        return ConversationHandler.END

    keyboard = [[course] for course in active_courses]
    keyboard.append(["🔙 بازگشت"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text("لطفا دوره مورد نظر خود را انتخاب کنید:", reply_markup=reply_markup)
    return COURSE_SELECTION

async def course_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 بازگشت":
        await update.message.reply_text("به منوی اصلی برگشتید.")
        return ConversationHandler.END

    context.user_data['selected_course'] = text
    await update.message.reply_text("لطفا نام و نام خانوادگی فارسی خود را وارد کنید:")
    return NAME_FA

async def name_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name_fa'] = update.message.text
    await update.message.reply_text("لطفا نام و نام خانوادگی انگلیسی خود را وارد کنید:")
    return NAME_EN

async def name_en(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name_en'] = update.message.text

    reply_markup = ReplyKeyboardMarkup(fields_keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("رشته تحصیلی خود را انتخاب کنید:", reply_markup=reply_markup)
    return FIELD

async def field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['field'] = update.message.text
    await update.message.reply_text("شماره تماس خود را وارد کنید:")
    return PHONE

async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("کد ملی خود را وارد کنید:")
    return NATIONAL_CODE

async def national_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    national_code = update.message.text
    context.user_data['national_code'] = national_code

    # چک ثبت نام قبلی
    if collection.find_one({"national_code": national_code}):
        await update.message.reply_text("شما قبلا ثبت‌نام کرده‌اید. ثبت‌نام مجدد انجام نخواهد شد.")
        return ConversationHandler.END

    await update.message.reply_text("شماره دانشجویی خود را وارد کنید:")
    return STUDENT_ID

async def student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['student_id'] = update.message.text

    data = {
        "selected_course": context.user_data.get("selected_course"),
        "name_fa": context.user_data.get("name_fa"),
        "name_en": context.user_data.get("name_en"),
        "field": context.user_data.get("field"),
        "phone": context.user_data.get("phone"),
        "national_code": context.user_data.get("national_code"),
        "student_id": context.user_data.get("student_id"),
    }

    collection.insert_one(data)

    admin_text = (
        f"ثبت‌نام جدید در دوره:\n"
        f"دوره: {data['selected_course']}\n"
        f"نام فارسی: {data['name_fa']}\n"
        f"نام انگلیسی: {data['name_en']}\n"
        f"رشته تحصیلی: {data['field']}\n"
        f"شماره تماس: {data['phone']}\n"
        f"کد ملی: {data['national_code']}\n"
        f"شماره دانشجویی: {data['student_id']}"
    )
    await context.bot.send_message(chat_id=PRIVATE_GROUP_CHAT_ID, text=admin_text)

    await update.message.reply_text("ثبت‌نام شما با موفقیت انجام شد.\nبا تشکر از شرکت شما.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("فرایند ثبت‌نام لغو شد.")
    return ConversationHandler.END

if __name__ == '__main__':
    from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler, ConversationHandler

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🗓️ 3- ثبتنام دوره‌ها$"), courses_start)],
        states={
            COURSE_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_selected)],
            NAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_fa)],
            NAME_EN: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_en)],
            FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, field)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone)],
            NATIONAL_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, national_code)],
            STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_id)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.run_polling()
