import re
import random
import string
from telegram import (
    Update, ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

# توکن و شناسه کانال و گروه
TOKEN = "8373000722:AAGyGAi57JbUO6OLYEIxzsPHwItEcYGF74U"
CHANNEL_ID = "@mobsa_mazust"  # یا عدد آی‌دی کانال
GROUP_ID = -490898272467890  # گروه اعضا
COURSE_REG_GROUP_ID = -4909919273  # گروه ثبت‌نام دوره‌ها

# تعریف حالت‌ها
(
    MAIN_MENU,
    ABOUT_MENU,

    ASK_FULLNAME_FA,
    CONFIRM_FULLNAME_FA,

    ASK_FULLNAME_EN,
    CONFIRM_FULLNAME_EN,

    ASK_STUDENT_ID,
    CONFIRM_STUDENT_ID,

    ASK_NATIONAL_ID,
    CONFIRM_NATIONAL_ID,

    ASK_PHONE,
    CONFIRM_PHONE,

    ASK_MAJOR,
    CONFIRM_MAJOR,

    COURSE_SELECTION,
    COURSE_CONFIRMATION,
    COURSE_ASK_DETAILS
) = range(17)

# دیکشنری دوره‌ها (نام و آی‌دی پیام کانال برای فوروارد)
COURSES = {
    "انرژی های تجدیدپذیر": {"post_id": 123},
    "مدیریت انرژی": {"post_id": 124},
    "بهینه سازی مصرف": {"post_id": 125},
}

# کیبورد منوی اصلی
def get_main_keyboard():
    keyboard = [
        ["👥 عضویت در انجمن"],
        ["ℹ️ درباره انجمن"],
        ["📚 ثبتنام دوره‌ها"],
        ["📞 ارتباط با دبیر"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# کیبورد رشته‌ها
def get_majors_keyboard():
    majors = [
        "⚡️ مهندسی انرژی",
        "💡 مهندسی برق",
        "💻 مهندسی کامپیوتر",
        "🧪 مهندسی شیمی",
        "🏗️ مهندسی عمران",
        "🏭 مهندسی صنایع",
        "🛢️ مهندسی نفت",
        "🔢 ریاضیات و کاربردها",
        "🖥️ علوم کامپیوتر"
    ]
    keyboard = [[m] for m in majors]
    keyboard.append(["❌ ابطال عضویت"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# کیبورد درباره انجمن
def about_keyboard():
    keyboard = [
        ["📝 معرفی انجمن", "👥 شورای مرکزی"],
        ["🔙 بازگشت به منوی اصلی"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# کیبورد دوره‌ها
def get_courses_keyboard():
    keyboard = [[name] for name in COURSES.keys()]
    keyboard.append(["🔙 بازگشت به منوی اصلی"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# تابع تولید کد یکتا عضویت و ثبت‌نام دوره
def generate_membership_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def generate_registration_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# فرضیه: دیتابیس و توابع ذخیره وجود دارند و به صورت مثال:
def save_member_to_db(data):
    # ذخیره عضو در دیتابیس
    # اگر عضو تکراری بود False برگرداند
    # فرضاً اینجا True برگردانیم
    return True

def is_user_member(telegram_id):
    # چک کن آیا عضو هست یا نه
    # فرضاً True برگردون
    return True

async def save_registration_info(update, context, data):
    info = (
        f"ثبت‌نام دوره:\n"
        f"کاربر: {update.message.from_user.full_name} ({update.message.from_user.id})\n"
        f"دوره: {data['course']}\n"
        f"نام و نام خانوادگی: {data.get('fullname_fa','-')}\n"
        f"Fullname (EN): {data.get('fullname_en','-')}\n"
        f"شماره دانشجویی: {data.get('student_id','-')}\n"
        f"کد ملی: {data.get('national_id','-')}\n"
        f"تلفن: {data.get('phone','-')}\n"
        f"رشته: {data.get('major','-')}\n"
        f"کد تایید: {data.get('verify_code')}"
    )
    await context.bot.send_message(chat_id=COURSE_REG_GROUP_ID, text=info)


# --- مراحل ثبت‌نام عضویت ---

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not re.fullmatch(r"09\d{9}", text):
        await update.message.reply_text("لطفا شماره تماس 11 رقمی را با شروع 09 و فقط با اعداد انگلیسی وارد کنید.")
        return ASK_PHONE

    context.user_data['phone'] = text

    await update.message.reply_text(
        f"آیا شماره تماس شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup([["تایید", "رد"]], resize_keyboard=True)
    )
    return CONFIRM_PHONE

async def confirm_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "تایید":
        await update.message.reply_text(
            "لطفا رشته تحصیلی خود را انتخاب کنید.",
            reply_markup=get_majors_keyboard()
        )
        return ASK_MAJOR
    elif text == "رد":
        await update.message.reply_text("لطفا شماره تماس خود را دوباره وارد کنید.")
        return ASK_PHONE
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های تایید یا رد استفاده کنید.")
        return CONFIRM_PHONE

async def ask_major(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    majors = [
        "⚡️ مهندسی انرژی",
        "💡 مهندسی برق",
        "💻 مهندسی کامپیوتر",
        "🧪 مهندسی شیمی",
        "🏗️ مهندسی عمران",
        "🏭 مهندسی صنایع",
        "🛢️ مهندسی نفت",
        "🔢 ریاضیات و کاربردها",
        "🖥️ علوم کامپیوتر"
    ]

    if text not in majors:
        await update.message.reply_text("لطفا یکی از رشته‌های موجود در کیبورد را انتخاب کنید.")
        return ASK_MAJOR

    context.user_data['major'] = text

    await update.message.reply_text(
        f"آیا رشته تحصیلی شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup([["تایید", "رد"]], resize_keyboard=True)
    )
    return CONFIRM_MAJOR

async def confirm_major(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "تایید":
        return await finalize_registration(update, context)
    elif text == "رد":
        await update.message.reply_text("لطفا رشته تحصیلی خود را دوباره انتخاب کنید.", reply_markup=get_majors_keyboard())
        return ASK_MAJOR
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های تایید یا رد استفاده کنید.")
        return CONFIRM_MAJOR

async def finalize_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    membership_code = generate_membership_code()
    user_data['membership_code'] = membership_code
    user_id = update.message.from_user.id

    data_to_save = {
        'fullname_fa': user_data.get('fullname_fa', '-'),
        'fullname_e': user_data.get('fullname_e', '-'),
        'student_id': user_data.get('student_id', '-'),
        'national_id': user_data.get('national_id', '-'),
        'phone': user_data.get('phone', '-'),
        'major': user_data.get('major', '-'),
        'telegram_id': user_id,
        'membership_code': membership_code
    }

    saved = save_member_to_db(data_to_save)
    if not saved:
        await update.message.reply_text("شما قبلا ثبت نام کرده‌اید و اطلاعات تکراری است.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    await update.message.reply_text(
        f"🎉 عضویت شما با موفقیت ثبت شد!\n"
        f"کد عضویت شما: {membership_code}\n"
        f"به انجمن علمی دانشجویی مبسا خوش آمدید!",
        reply_markup=get_main_keyboard()
    )

    info_msg = (
        f"عضو جدید ثبت شد:\n"
        f"نام فارسی: {user_data.get('fullname_fa','-')}\n"
        f"نام انگلیسی: {user_data.get('fullname_e','-')}\n"
        f"شماره دانشجویی: {user_data.get('student_id','-')}\n"
        f"کد ملی: {user_data.get('national_id','-')}\n"
        f"شماره تماس: {user_data.get('phone','-')}\n"
        f"رشته تحصیلی: {user_data.get('major','-')}\n"
        f"آیدی تلگرام: @{update.message.from_user.username if update.message.from_user.username else user_id}\n"
        f"کد عضویت: {membership_code}"
    )
    await context.bot.send_message(chat_id=GROUP_ID, text=info_msg)
    return MAIN_MENU

# --- منوی درباره انجمن ---
async def about_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📝 معرفی انجمن":
        msgs = [
            """📝 نام و نوع فعالیت انجمن
نام انجمن، «انجمن علمی دانشجویی بین رشته ای مدیریت و بهینه سازی انرژی دانشگاه علم و فناوری
مازندران» می باشد. این انجمن با مشارکت داوطلبانه دانشجویان علاقه مند، به منظور توسعه علمی، تخصصی و پژوهشی در زمینه انرژی تشکیل
می گردد.
📌 انجمن صرفاً در زمینه علمی، تخصصی و پژوهشی فعالیت می نماید و کاملاً غیرسیاسی،
غیرحزبی و غیرصنفی است.""",

            """🏫 محل و حوزه فعالیت انجمن
مرکز اصلی انجمن در دانشگاه علم و فناوری مازندران در شهر بهشهر می‌باشد. حوزه فعالیت انجمن
بین رشته ای و در زمینه انرژی است. دانشجویان علاقه مند به حوزه انرژی از رشته‌های مهندسی
انرژی، برق، شیمی، صنایع، عمران، کامپیوتر، نفت و علوم کامپیوتر و ریاضیات و کاربردها می توانند عضو انجمن
شوند.""",

            """🎯 اهداف انجمن
به منظور گسترش و ارتقای علمی و پژوهشی در حوزه انرژی، این انجمن با اهداف زیر تشکیل شده است:
 • ایجاد همکاری علمی بین دانشجویان رشته‌های مختلف در حوزه انرژی
 • ارتقاء آگاهی تخصصی در زمینه انرژی‌های تجدیدپذیر و غیرتجدیدپذیر
 • برگزاری دوره‌ها، سخنرانی‌ها و کارگاه‌های تخصصی
 • انجام پروژه‌های پژوهشی مشترک
 • بازدیدهای علمی
 • حمایت از استارتاپ‌ها و ایده‌های نوآورانه دانشجویی
 • ترویج فرهنگ انرژی پایدار و مصرف بهینه
 • ارتباط با نهادهای علمی داخلی و بین المللی
 • انتشار محتوای علمی"""
        ]

        for msg in msgs:
            await update.message.reply_text(msg, reply_markup=about_keyboard())
        return ABOUT_MENU

    elif text == "👥 شورای مرکزی":
        members = [
            {
                "photo": "https://img3.stockfresh.com/files/d/drizzd/m/49/7237033_stock-photo-the-word-admin-and-gear-wheel---3d-rendering.jpg",
                "caption": "دبیر انجمن\nعلی دایی\nali@example.com"
            },
            {
                "photo": "data:image/png;base64,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"
            }
        ]
        for m in members:
            if 'photo' in m:
                await update.message.reply_photo(photo=m['photo'], caption=m.get('caption', ''), reply_markup=about_keyboard())
            else:
                await update.message.reply_text(m.get('caption', ''), reply_markup=about_keyboard())
        return ABOUT_MENU

    elif text == "🔙 بازگشت به منوی اصلی":
        await update.message.reply_text("به منوی اصلی بازگشتید.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    else:
        await update.message.reply_text("لطفا از دکمه‌های موجود استفاده کنید.", reply_markup=about_keyboard())
        return ABOUT_MENU


# --- منوی اصلی ---
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "👥 عضویت در انجمن":
        await update.message.reply_text("لطفا نام و نام خانوادگی خود را به فارسی وارد کنید.\nمثال: علی دایی", reply_markup=ReplyKeyboardMarkup([["❌ ابطال عضویت"]], resize_keyboard=True))
        return ASK_FULLNAME_FA

    elif text == "ℹ️ درباره انجمن":
        await update.message.reply_text("لطفا یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=about_keyboard())
        return ABOUT_MENU

    elif text == "📚 ثبتنام دوره‌ها":
        return await course_registration_start(update, context)

    elif text == "📞 ارتباط با دبیر":
        await update.message.reply_text("برای ارتباط با دبیر لطفا به @username مراجعه کنید.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    else:
        await update.message.reply_text("لطفا از دکمه‌های منوی اصلی استفاده کنید.", reply_markup=get_main_keyboard())
        return MAIN_MENU


# --- ثبت‌نام دوره‌ها ---

async def course_registration_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "لطفا دوره مورد نظر خود را انتخاب کنید:",
        reply_markup=get_courses_keyboard()
    )
    return COURSE_SELECTION

async def course_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 بازگشت به منوی اصلی":
        await update.message.reply_text("بازگشت به منوی اصلی.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if text not in COURSES:
        await update.message.reply_text("لطفا یکی از دوره‌های موجود را انتخاب کنید.")
        return COURSE_SELECTION

    context.user_data['selected_course'] = text

    # فوروارد پست دوره از کانال به کاربر
    post_id = COURSES[text]['post_id']
    try:
        await context.bot.forward_message(
            chat_id=update.message.chat_id,
            from_chat_id=CHANNEL_ID,
            message_id=post_id
        )
    except Exception as e:
        print(f"Error forwarding post: {e}")

    await update.message.reply_text(
        f"آیا مطمئن هستید که می‌خواهید در دوره '{text}' ثبت‌نام کنید؟",
        reply_markup=ReplyKeyboardMarkup([["بله", "خیر"]], resize_keyboard=True)
    )
    return COURSE_CONFIRMATION

async def course_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "خیر":
        await update.message.reply_text("لطفا دوباره دوره مورد نظر خود را انتخاب کنید:", reply_markup=get_courses_keyboard())
        return COURSE_SELECTION
    elif text == "بله":
        course = context.user_data['selected_course']
        telegram_id = update.message.from_user.id
        if is_user_member(telegram_id):
            registration_code = generate_registration_code()
            context.user_data['registration_code'] = registration_code
            await update.message.reply_text(
                f"ثبت‌نام شما در دوره '{course}' تایید شد.\nکد تایید شما: {registration_code}",
                reply_markup=get_main_keyboard()
            )
            await save_registration_info(update, context, {
                'course': course,
                'fullname_fa': '-',
                'fullname_en': '-',
                'student_id': '-',
                'national_id': '-',
                'phone': '-',
                'major': '-',
                'verify_code': registration_code
            })
            return MAIN_MENU
        else:
            await update.message.reply_text(
                "شما عضو انجمن نیستید. لطفا مشخصات خود را وارد کنید.",
                reply_markup=ReplyKeyboardMarkup([["❌ ابطال ثبت‌نام"]], resize_keyboard=True)
            )
            return COURSE_ASK_DETAILS
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های بله یا خیر استفاده کنید.")
        return COURSE_CONFIRMATION

async def course_ask_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ ابطال ثبت‌نام":
        await update.message.reply_text("ثبت‌نام لغو شد.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # در این نمونه فقط نام فارسی گرفته شده
    context.user_data['fullname_fa'] = text

    registration_code = generate_registration_code()
    context.user_data['registration_code'] = registration_code
    course = context.user_data['selected_course']

    await update.message.reply_text(
        f"ثبت‌نام شما در دوره '{course}' تایید شد.\nکد تایید شما: {registration_code}",
        reply_markup=get_main_keyboard()
    )

    await save_registration_info(update, context, {
        'course': course,
        'fullname_fa': context.user_data.get('fullname_fa', '-'),
        'fullname_en': context.user_data.get('fullname_en', '-'),
        'student_id': context.user_data.get('student_id', '-'),
        'national_id': context.user_data.get('national_id', '-'),
        'phone': context.user_data.get('phone', '-'),
        'major': context.user_data.get('major', '-'),
        'verify_code': registration_code
    })
    return MAIN_MENU


# --- ثبت‌نام عضویت (شروع از نام فارسی) ---

async def ask_fullname_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # فقط حروف فارسی و فاصله قبول شود
    if not re.fullmatch(r"[آ-ی\s]{3,50}", text):
        await update.message.reply_text("لطفا فقط نام و نام خانوادگی خود را به فارسی و با حداقل ۳ حرف وارد کنید.")
        return ASK_FULLNAME_FA

    context.user_data['fullname_fa'] = text
    await update.message.reply_text(
        f"آیا نام و نام خانوادگی شما '{text}' است؟",
        reply_markup=ReplyKeyboardMarkup([["تایید", "رد"]], resize_keyboard=True)
    )
    return CONFIRM_FULLNAME_FA

async def confirm_fullname_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "تایید":
        await update.message.reply_text("لطفا نام و نام خانوادگی خود را به انگلیسی وارد کنید.\nمثال: Ali Daei", reply_markup=ReplyKeyboardMarkup([["❌ ابطال عضویت"]], resize_keyboard=True))
        return ASK_FULLNAME_EN
    elif text == "رد":
        await update.message.reply_text("لطفا نام و نام خانوادگی خود را دوباره به فارسی وارد کنید.")
        return ASK_FULLNAME_FA
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های تایید یا رد استفاده کنید.")
        return CONFIRM_FULLNAME_FA

async def ask_fullname_en(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    # چک ساده فقط حروف انگلیسی و فاصله
    if not re.fullmatch(r"[a-zA-Z\s]{3,50}", text):
        await update.message.reply_text("لطفا فقط نام و نام خانوادگی خود را به انگلیسی وارد کنید.")
        return ASK_FULLNAME_EN

    context.user_data['fullname_e'] = text
    await update.message.reply_text(
        f"آیا نام و نام خانوادگی شما '{text}' است؟",
        reply_markup=ReplyKeyboardMarkup([["تایید", "رد"]], resize_keyboard=True)
    )
    return CONFIRM_FULLNAME_EN

async def confirm_fullname_en(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "تایید":
        await update.message.reply_text("لطفا شماره دانشجویی خود را وارد کنید.\nمثال: 12345678", reply_markup=ReplyKeyboardMarkup([["❌ ابطال عضویت"]], resize_keyboard=True))
        return ASK_STUDENT_ID
    elif text == "رد":
        await update.message.reply_text("لطفا نام و نام خانوادگی خود را دوباره به انگلیسی وارد کنید.")
        return ASK_FULLNAME_EN
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های تایید یا رد استفاده کنید.")
        return CONFIRM_FULLNAME_EN

async def ask_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not re.fullmatch(r"\d{5,10}", text):
        await update.message.reply_text("لطفا شماره دانشجویی را فقط با اعداد وارد کنید.")
        return ASK_STUDENT_ID

    context.user_data['student_id'] = text
    await update.message.reply_text(
        f"آیا شماره دانشجویی شما '{text}' است؟",
        reply_markup=ReplyKeyboardMarkup([["تایید", "رد"]], resize_keyboard=True)
    )
    return CONFIRM_STUDENT_ID

async def confirm_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "تایید":
        await update.message.reply_text("لطفا کد ملی خود را وارد کنید.\nمثال: 1234567890", reply_markup=ReplyKeyboardMarkup([["❌ ابطال عضویت"]], resize_keyboard=True))
        return ASK_NATIONAL_ID
    elif text == "رد":
        await update.message.reply_text("لطفا شماره دانشجویی خود را دوباره وارد کنید.")
        return ASK_STUDENT_ID
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های تایید یا رد استفاده کنید.")
        return CONFIRM_STUDENT_ID

async def ask_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard())
        return MAIN_MENU

    if not re.fullmatch(r"\d{10}", text):
        await update.message.reply_text("لطفا کد ملی 10 رقمی را فقط با عدد وارد کنید.")
        return ASK_NATIONAL_ID

    context.user_data['national_id'] = text
    await update.message.reply_text(
        f"آیا کد ملی شما '{text}' است؟",
        reply_markup=ReplyKeyboardMarkup([["تایید", "رد"]], resize_keyboard=True)
    )
    return CONFIRM_NATIONAL_ID

async def confirm_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "تایید":
        await update.message.reply_text("لطفا شماره تماس خود را وارد کنید.\nمثال: 09123456789", reply_markup=ReplyKeyboardMarkup([["❌ ابطال عضویت"]], resize_keyboard=True))
        return ASK_PHONE
    elif text == "رد":
        await update.message.reply_text("لطفا کد ملی خود را دوباره وارد کنید.")
        return ASK_NATIONAL_ID
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های تایید یا رد استفاده کنید.")
        return CONFIRM_NATIONAL_ID


# --- هندلرها ---
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],

            ABOUT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, about_menu)],

            ASK_FULLNAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_fullname_fa)],
            CONFIRM_FULLNAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_fullname_fa)],

            ASK_FULLNAME_EN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_fullname_en)],
            CONFIRM_FULLNAME_EN: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_fullname_en)],

            ASK_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_student_id)],
            CONFIRM_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_student_id)],

            ASK_NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_national_id)],
            CONFIRM_NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_national_id)],

            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            CONFIRM_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_phone)],

            ASK_MAJOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_major)],
            CONFIRM_MAJOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_major)],

            COURSE_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_selection_handler)],
            COURSE_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_confirmation_handler)],
            COURSE_ASK_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_ask_details_handler)],
        },
        fallbacks=[]
    )

    application.add_handler(conv_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
