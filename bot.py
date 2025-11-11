import sqlite3
import random
import json
import re
from telegram import (
    Update, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters,
    ConversationHandler, ContextTypes
)
from telegram import InputMediaPhoto
from dotenv import load_dotenv
import os
# ======================= [BEGIN PATCH: Course Registrations View/Export] =======================
# توابع کمکی دیتابیس برای ثبت‌نام‌های دوره (Full) و پروفایل عضو:

def get_course_registrations_full(course_id: int):
    """
    برمی‌گرداند لیست تاپل‌ها:
    (reg_id, telegram_id, fullname_fa, student_id, national_id, phone, registration_code, is_member)
    """
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, telegram_id, fullname_fa, student_id, national_id, phone, registration_code, is_member
        FROM course_registrations
        WHERE course_id=?
        ORDER BY id ASC
    """, (course_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_member_profile_by_telegram(telegram_id: int):
    """
    برمی‌گرداند: (fullname_e, major, membership_code) اگر عضو ثبت‌شده باشد، وگرنه (None, None, None)
    """
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT fullname_e, major, membership_code
        FROM members
        WHERE telegram_id=?
    """, (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1], row[2]
    return None, None, None


def delete_registration_by_id(reg_id: int):
    """
    ردیف course_registrations را حذف می‌کند و registered_count دوره را یک واحد کم می‌کند.
    """
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()

    # ابتدا course_id را پیدا کن
    cursor.execute("SELECT course_id FROM course_registrations WHERE id=?", (reg_id,))
    r = cursor.fetchone()
    if not r:
        conn.close()
        return False
    course_id = r[0]

    # حذف
    cursor.execute("DELETE FROM course_registrations WHERE id=?", (reg_id,))
    # کم کردن شمارنده
    cursor.execute("UPDATE courses SET registered_count = CASE WHEN registered_count>0 THEN registered_count-1 ELSE 0 END WHERE id=?", (course_id,))
    conn.commit()
    conn.close()
    return True


def _format_view_message_per_person(fullname_fa, fullname_e, student_id, national_id, phone, major, membership_code):
    # membership text
    membership_text = membership_code if membership_code else "غیر عضو"
    # اگر رشته ایموجی نداشت، پیش‌فرض 📘 بگذاریم
    major_text = major or "—"
    if major_text and not any(ch in major_text for ch in ["⚡️","💡","💻","🧪","🏗️","🏭","🛢️","🔢","🖥️","📘"]):
        major_text = f"📘 {major_text}"

    # قالب دقیق خواسته‌شده
    lines = [
        f"👤 {fullname_fa or '—'}",
        f"نام انگلیسی: {fullname_e or '—'}",
        f"شماره دانشجویی: {student_id or '—'}",
        f"کدملی: {national_id or '—'}",
        f"شماره تماس: {phone or '—'}",
        f"رشته تحصیلی: {major_text}",
        f"کد عضویت: {membership_text}",
    ]
    return "\n".join(lines)


async def _send_course_regs_view_per_person(update, context, regs: list):
    """
    برای هر ثبت‌نام یک پیام با دکمه حذف می‌فرستد.
    """
    for (reg_id, tg_id, fullname_fa, student_id, national_id, phone, reg_code, is_member) in regs:
        fullname_e, major, membership_code = get_member_profile_by_telegram(tg_id)
        msg = _format_view_message_per_person(fullname_fa, fullname_e, student_id, national_id, phone, major, membership_code)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ حذف از لیست", callback_data=f"del_reg_{reg_id}")]])
        await update.message.reply_text(msg, reply_markup=kb)


async def _send_course_regs_export(update, context, course_id: int, regs: list):
    """
    متن تجمیعی (در چند پیام اگر طولانی شد) + فایل CSV UTF-8 BOM ارسال می‌کند.
    """
    # 1) متن تجمیعی
    blocks = []
    for idx, (reg_id, tg_id, fullname_fa, student_id, national_id, phone, reg_code, is_member) in enumerate(regs, start=1):
        fullname_e, major, membership_code = get_member_profile_by_telegram(tg_id)
        membership_text = membership_code if membership_code else "غیر عضو"
        major_text = major or "—"
        if major_text and not any(ch in major_text for ch in ["⚡️","💡","💻","🧪","🏗️","🏭","🛢️","🔢","🖥️","📘"]):
            major_text = f"📘 {major_text}"
        block = (
            f"{idx}. نام فارسی: {fullname_fa or '—'}\n"
            f"کدملی: {national_id or '—'}\n"
            f"شماره دانشجویی: {student_id or '—'}\n"
            f"رشته تحصیلی: {major_text}\n"
            f"شماره تماس: {phone or '—'}\n"
            f"کد عضویت: {membership_text}"
        )
        blocks.append(block)

    # خرد کردن پیام‌ها بر اساس محدودیت کاراکتر
    chunk = []
    for b in blocks:
        chunk.append(b)
        if sum(len(x) + 2 for x in chunk) > 3500:
            await update.message.reply_text("\n\n".join(chunk))
            chunk = []
    if chunk:
        await update.message.reply_text("\n\n".join(chunk))

    # 2) ساخت CSV
    import io, csv, datetime
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["full_name_fa","full_name_en","student_id","national_id","phone","major","membership_code","is_member","registration_code"])
    for (reg_id, tg_id, fullname_fa, student_id, national_id, phone, reg_code, is_member) in regs:
        fullname_e, major, membership_code = get_member_profile_by_telegram(tg_id)
        writer.writerow([
            fullname_fa or "",
            fullname_e or "",
            student_id or "",
            national_id or "",
            phone or "",
            major or "",
            membership_code or ("غیر عضو"),
            1 if is_member else 0,
            reg_code or ""
        ])
    csv_bytes = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    csv_bytes.name = f"registrations_{course_id}_{ts}.csv"
    await update.message.reply_document(csv_bytes, caption="🧾 خروجی CSV ثبت‌نام‌کنندگان")


# ---------- Callback: باز کردن منوی لیست ثبت‌نام‌کنندگان برای یک دوره ----------
async def open_course_reg_list(query, context, course_id: int):
    context.user_data["list_course_id"] = course_id
    await query.message.reply_text("یکی از گزینه‌ها را انتخاب کنید:", reply_markup=get_course_regs_keyboard())


async def admin_open_course_regs(update, context):
    """
    وقتی ادمین روی دکمه‌ی inline «📋 لیست ثبت‌نام‌کنندگان» کلیک می‌کند.
    callback_data = list_registrations_<course_id>
    """
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ شما دسترسی ادمین ندارید.")
        return
    try:
        course_id = int(query.data.split("_")[2])
    except Exception:
        await query.edit_message_text("داده نامعتبر است.")
        return
    await open_course_reg_list(query, context, course_id)


# ---------- Callback: حذف یک ثبت‌نام ----------
async def admin_delete_registration(update, context):
    """
    callback_data = del_reg_<reg_id>
    """
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ شما دسترسی ادمین ندارید.")
        return
    try:
        reg_id = int(query.data.split("_")[2])
    except Exception:
        await query.edit_message_text("داده نامعتبر است.")
        return

    ok = delete_registration_by_id(reg_id)
    if ok:
        try:
            await query.edit_message_text("✅ از لیست حذف شد.")
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ از لیست حذف شد.")
    else:
        await query.edit_message_text("⚠️ موردی برای حذف یافت نشد یا قبلاً حذف شده است.")

# ======================= [END PATCH] =======================


# بارگذاری فایل .env
load_dotenv()

# خواندن متغیرها از .env
TOKEN = os.getenv("TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))   # آیدی گروه ادمین برای عضویت
COURSE_GROUP_ID = int(os.getenv("COURSE_GROUP_ID"))  # آیدی گروه جداگانه برای ثبت‌نام دوره‌ها
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # آیدی ادمین
ELECTION_RESULTS_GROUP_ID = int(os.getenv("ELECTION_RESULTS_GROUP_ID"))  # آیدی گروه جدید برای نتایج انتخابات

# وضعیت عضویت: True = فعال، False = غیرفعال
membership_active = True

# وضعیت انتخابات: True = فعال، False = غیرفعال
election_active = False

# حالت‌های مکالمه
MAIN_MENU = 0
ABOUT_MENU = 1
ADMIN_PANEL = 2
ADMIN_COURSE_MENU = 3  # منوی دوره‌ها برای ادمین
USER_COURSE_MENU = 4   # منوی دوره‌ها برای کاربر
(ASK_FULLNAME_FA, CONFIRM_FULLNAME_FA,
 ASK_FULLNAME_EN, CONFIRM_FULLNAME_EN,
 ASK_STUDENT_ID, CONFIRM_STUDENT_ID,
 ASK_NATIONAL_ID, CONFIRM_NATIONAL_ID,
 ASK_PHONE, CONFIRM_PHONE,
 ASK_MAJOR, CONFIRM_MAJOR,
 ASK_SECRETARY_MESSAGE, CONFIRM_SECRETARY_MESSAGE,
 ASK_ABOUT_MESSAGE, CONFIRM_ABOUT_MESSAGE,
 ASK_COUNCIL_MESSAGE, CONFIRM_COUNCIL_MESSAGE, ASK_COUNCIL_PHOTO,
 ASK_COURSE_NAME, CONFIRM_COURSE_NAME,
 ASK_COURSE_CAPACITY, CONFIRM_COURSE_CAPACITY,
 ASK_COURSE_PHOTO, ASK_COURSE_CAPTION, CONFIRM_COURSE_CAPTION,
 ASK_COURSE_CARD, CONFIRM_COURSE_CARD,
 ASK_COURSE_PRICE_MEMBER, CONFIRM_COURSE_PRICE_MEMBER,
 ASK_COURSE_PRICE_NON_MEMBER, CONFIRM_COURSE_PRICE_NON_MEMBER,
 SELECT_COURSE, CONFIRM_COURSE_SELECTION,
 ASK_COURSE_FULLNAME_FA, CONFIRM_COURSE_FULLNAME_FA,
 ASK_COURSE_STUDENT_ID, CONFIRM_COURSE_STUDENT_ID,
 ASK_COURSE_NATIONAL_ID, CONFIRM_COURSE_NATIONAL_ID,
 ASK_COURSE_PHONE, CONFIRM_COURSE_PHONE,
 PAYMENT_CONFIRMATION, UPLOAD_PAYMENT_PROOF) = range(5, 49)
ADMIN_ELECTION_MENU = 49
ASK_CANDIDATE_NAME = 50
CONFIRM_CANDIDATE_NAME = 51
ASK_CANDIDATE_FIELD = 52
CONFIRM_CANDIDATE_FIELD = 53
ASK_CANDIDATE_DESC = 54
CONFIRM_CANDIDATE_DESC = 55
ASK_CANDIDATE_PHOTO = 56
USER_ELECTION_MENU = 57
ASK_COUNCIL_SLOT, ASK_COUNCIL_TEXT, CONFIRM_COUNCIL_TEXT, ASK_COUNCIL_PHOTO2, CONFIRM_COUNCIL_SAVE = range(600, 605)

# --- کیبورد‌ها ---


def get_main_keyboard(user_id: int | None = None):
    keyboard = [
        ["🤝 عضویت در انجمن"],
        ["🗂️ درباره انجمن"],
        ["📚 ثبت‌نام دوره‌ها"],
        ["💬 ارتباط با دبیر"],
        ["🗳️ انتخابات"]
    ]
    if user_id == ADMIN_ID:
        keyboard.append(["🛠 پنل ادمین"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


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
        "🖥️ علوم کامپیوتر",
        "🌀 سایر رشته ها "
    ]
    keyboard = [[m] for m in majors]
    keyboard.append(["❌ ابطال عضویت"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- افزوده جدید: کیبورد ساده‌ی رشته‌ها مخصوص انتخابات (بدون ابطال عضویت) ---
def get_majors_keyboard_election():
    majors = [
        "⚡️ مهندسی انرژی",
        "💡 مهندسی برق",
        "💻 مهندسی کامپیوتر",
        "🧪 مهندسی شیمی",
        "🏗️ مهندسی عمران",
        "🏭 مهندسی صنایع",
        "🛢️ مهندسی نفت",
        "🔢 ریاضیات و کاربردها",
        "🖥️ علوم کامپیوتر",
        "🌀 سایر رشته ها "
    ]
    keyboard = [[m] for m in majors]
    keyboard.append(["لغو"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def about_keyboard():
    keyboard = [
        ["📝 معرفی انجمن", "👥 شورای مرکزی"],
        ["🔙 بازگشت به منوی اصلی"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["لیست اعضا"],
        ["فعال/غیرفعالسازی عضویت"],
        ["دبیر"],
        ["اهداف"],
        ["شورا"],
        ["دوره‌ها"],
        ["انتخابات"],
        ["بازگشت"]
    ], resize_keyboard=True)



def get_course_regs_keyboard():
    return ReplyKeyboardMarkup([
        ["📤 صدور", "📖 مشاهده"],
        ["بازگشت"]
    ], resize_keyboard=True)
def get_members_list_keyboard():
    return ReplyKeyboardMarkup([
        ["📤 صدور", "📖 مشاهده"],
        ["بازگشت"]
    ], resize_keyboard=True)

def chunk_list(items, size=15):
    for i in range(0, len(items), size):
        yield items[i:i+size]


def council_slots_keyboard():
    # کیبورد انتخاب یکی از شش شورا با اعداد فارسی
    return ReplyKeyboardMarkup(
        [["شورا۱", "شورا۲", "شورا۳"],
         ["شورا۴", "شورا۵", "شورا۶"],
         ["بازگشت"]],
        resize_keyboard=True
    )


def get_courses_keyboard():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM courses')
    courses = cursor.fetchall()
    conn.close()
    keyboard = [[course[0]] for course in courses]
    keyboard.append(["➕ افزودن دوره"])
    keyboard.append(["بازگشت"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_course_management_keyboard(course_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "❌ حذف دوره", callback_data=f"delete_course_{course_id}")],
        [InlineKeyboardButton("📋 لیست ثبت‌نام‌کنندگان",
                              callback_data=f"list_registrations_{course_id}")]
    ])


def get_user_courses_keyboard():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT name FROM courses WHERE capacity > registered_count')
    courses = cursor.fetchall()
    conn.close()
    if not courses:
        return None
    keyboard = [[course[0]] for course in courses]
    keyboard.append(["🔙 بازگشت به منوی اصلی"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_payment_confirmation_keyboard():
    return ReplyKeyboardMarkup([["واریز کردم"]], resize_keyboard=True)


def get_admin_election_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ افزودن کاندیدا"],
        ["فعال/غیرفعال انتخابات"],
        ["📋 مشاهده آرا"],
        ["🗑️ حذف کاندیدا"],
        ["🏁 پایان انتخابات"],
        ["بازگشت"]
    ], resize_keyboard=True)


def build_delete_candidates_keyboard():
    candidates = get_all_candidates()
    if not candidates:
        return None
    rows = [
        [InlineKeyboardButton(
            f"🗑️ حذف {name}", callback_data=f"delete_cand_{cid}")]
        for cid, name in candidates
    ]
    return InlineKeyboardMarkup(rows)


def get_candidates_keyboard(for_voting=True, selected=[]):
    candidates = get_all_candidates()
    keyboard = []
    for cand in candidates:
        cand_id, name = cand
        btn_text = f"✅ {name}" if cand_id in selected else name
        keyboard.append([InlineKeyboardButton(
            btn_text, callback_data=f"vote_{cand_id}" if for_voting else f"admin_cand_{cand_id}")])
    if for_voting:
        keyboard.append([InlineKeyboardButton(
            "تایید رای (حداکثر ۵)", callback_data="vote_done")])
    return InlineKeyboardMarkup(keyboard)


def get_candidate_management_keyboard(cand_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "❌ حذف کاندیدا", callback_data=f"delete_cand_{cand_id}")]
    ])

# --- دیتابیس ---


def init_db():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    # جدول اعضا
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fullname_fa TEXT,
            fullname_e TEXT,
            student_id TEXT UNIQUE,
            national_id TEXT UNIQUE,
            phone TEXT,
            major TEXT,
            telegram_id INTEGER UNIQUE,
            membership_code TEXT UNIQUE
        )
    ''')
    # جدول برای ذخیره پیام ارتباط با دبیر
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS secretary_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT
        )
    ''')
    cursor.execute('SELECT COUNT(*) FROM secretary_message')
    if cursor.fetchone()[0] == 0:
        default_secretary_message = (
            "📞 ارتباط با دبیر انجمن علمی مبسا:\n\n"
            "📱 شماره تماس: 09121234567\n"
            "💬 آیدی تلگرام: @mabsa_Admin\n"
            "✉️ ایمیل: mabsa.admin@example.com"
        )
        cursor.execute(
            'INSERT INTO secretary_message (message_text) VALUES (?)', (default_secretary_message,))
    # جدول برای ذخیره پیام معرفی انجمن
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS about_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT
        )
    ''')
    cursor.execute('SELECT COUNT(*) FROM about_message')
    if cursor.fetchone()[0] == 0:
        default_about_message = (
            "🎯 اهداف انجمن\n"
            "به منظور گسترش و ارتقای علمی و پژوهشی در حوزه انرژی، این انجمن با اهداف زیر تشکیل شده است:\n"
            " • ایجاد همکاری علمی بین دانشجویان رشته‌های مختلف در حوزه انرژی\n"
            " • ارتقاء آگاهی تخصصی در زمینه انرژی‌های تجدیدپذیر و غیرتجدیدپذیر\n"
            " • برگزاری دوره‌ها، سخنرانی‌ها و کارگاه‌های تخصصی\n"
            " • انجام پروژه‌های پژوهشی مشترک\n"
            " • بازدیدهای علمی\n"
            " • حمایت از استارتاپ‌ها و ایده‌های نوآورانه دانشجویی\n"
            " • ترویج فرهنگ انرژی پایدار و مصرف بهینه\n"
            " • ارتباط با نهادهای علمی داخلی و بین المللی\n"
            " • انتشار محتوای علمی"
        )
        cursor.execute(
            'INSERT INTO about_message (message_text) VALUES (?)', (default_about_message,))
    # جدول برای ذخیره پیام و تصویر شورای مرکزی
        # --- NEW: جدول چند-اسلاتی شورای مرکزی (۶ ردیف مستقل) ---
        # جدول جدید برای 6 پیام/عکس شورای مرکزی (اسلات 1..6)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS council_messages (
            slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 6),
            message_text TEXT,
            photo_url TEXT
        )
    ''')
    # اگر خالی بود، 6 ردیف پیش‌فرض بساز
    cursor.execute('SELECT COUNT(*) FROM council_messages')
    if (cursor.fetchone()[0] or 0) == 0:
        default_texts = [
            "👥 شورای مرکزی - شورا ۱\nتوضیحات پیش‌فرض",
            "👥 شورای مرکزی - شورا ۲\nتوضیحات پیش‌فرض",
            "👥 شورای مرکزی - شورا ۳\nتوضیحات پیش‌فرض",
            "👥 شورای مرکزی - شورا ۴\nتوضیحات پیش‌فرض",
            "👥 شورای مرکزی - شورا ۵\nتوضیحات پیش‌فرض",
            "👥 شورای مرکزی - شورا ۶\nتوضیحات پیش‌فرض",
        ]
        default_photo = None  # در صورت نیاز می‌توانی یک URL/FILE_ID پیش‌فرض بدهی
        for i in range(1, 7):
            cursor.execute(
                'INSERT INTO council_messages (slot, message_text, photo_url) VALUES (?, ?, ?)',
                (i, default_texts[i-1], default_photo)
            )

    # جدول برای ذخیره ثبت‌نام‌های دوره‌ها
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS course_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER,
            telegram_id INTEGER,
            fullname_fa TEXT,
            student_id TEXT,
            national_id TEXT,
            phone TEXT,
            payment_proof TEXT,
            registration_code TEXT UNIQUE,
            is_member BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')
    # جدول جدید برای کاندیداها
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            field TEXT,
            desc TEXT,
            photo TEXT
        )
    ''')
    # جدول جدید برای آرا
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            voted_candidates TEXT  -- JSON string of list
        )
    ''')
    conn.commit()
    conn.close()


def get_secretary_message():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT message_text FROM secretary_message WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else (
        "📞 ارتباط با دبیر انجمن علمی مبسا:\n\n"
        "📱 شماره تماس: 09121234567\n"
        "💬 آیدی تلگرام: @mabsa_Admin\n"
        "✉️ ایمیل: mabsa.admin@example.com"
    )


def get_membership_code_by_telegram_id(telegram_id: int) -> str | None:
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT membership_code FROM members WHERE telegram_id=?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def update_secretary_message(new_message):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE secretary_message SET message_text = ? WHERE id = 1', (new_message,))
    if cursor.rowcount == 0:
        cursor.execute(
            'INSERT INTO secretary_message (id, message_text) VALUES (1, ?)', (new_message,))
    conn.commit()
    conn.close()


def get_about_message():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT message_text FROM about_message WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else (
        "🎯 اهداف انجمن\n"
        "به منظور گسترش و ارتقای علمی و پژوهشی در حوزه انرژی، این انجمن با اهداف زیر تشکیل شده است:\n"
        " • ایجاد همکاری علمی بین دانشجویان رشته‌های مختلف در حوزه انرژی\n"
        " • ارتقاء آگاهی تخصصی در زمینه انرژی‌های تجدیدپذیر و غیرتجدیدپذیر\n"
        " • برگزاری دوره‌ها، سخنرانی‌ها و کارگاه‌های تخصصی\n"
        " • انجام پروژه‌های پژوهشی مشترک\n"
        " • بازدیدهای علمی\n"
        " • حمایت از استارتاپ‌ها و ایده‌های نوآورانه دانشجویی\n"
        " • ترویج فرهنگ انرژی پایدار و مصرف بهینه\n"
        " • ارتباط با نهادهای علمی داخلی و بین المللی\n"
        " • انتشار محتوای علمی"
    )


def update_about_message(new_message):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE about_message SET message_text = ? WHERE id = 1', (new_message,))
    if cursor.rowcount == 0:
        cursor.execute(
            'INSERT INTO about_message (id, message_text) VALUES (1, ?)', (new_message,))
    conn.commit()
    conn.close()


def get_council_item(slot: int) -> dict:
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT message_text, photo_url FROM council_messages WHERE slot=?', (slot,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"text": f"شورا {slot}: تنظیم نشده است.", "photo": None}
    return {"text": row[0] or "", "photo": row[1]}

def set_council_item(slot: int, text: str, photo_url: str | None):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE council_messages SET message_text=?, photo_url=? WHERE slot=?',
                   (text, photo_url, slot))
    conn.commit()
    conn.close()


def _normalize_digits(s: str) -> str:
    # تبدیل اعداد فارسی/عربی به لاتین برای پردازش عدد اسلات
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return s.translate(trans)


def get_all_council_items() -> list[tuple[int, str, str | None]]:
    """برمی‌گرداند [(slot, text, photo_url), ...]"""
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT slot, message_text, photo_url FROM council_messages ORDER BY slot')
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_member_by_telegram_id(telegram_id):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT membership_code, fullname_fa, student_id, national_id, phone FROM members WHERE telegram_id=?', (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result


def get_all_members():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, fullname_fa, fullname_e, student_id, phone, membership_code FROM members ORDER BY id DESC')
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_members_full():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, fullname_fa, fullname_e, student_id, national_id, phone, major, membership_code
        FROM members
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_member_by_id(member_id: int):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM members WHERE id=?', (member_id,))
    conn.commit()
    conn.close()


def save_member_to_db(data):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO members (fullname_fa, fullname_e, student_id, national_id, phone, major, telegram_id, membership_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['fullname_fa'], data['fullname_e'], data['student_id'], data['national_id'],
            data['phone'], data['major'], data['telegram_id'], data['membership_code']
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True


def generate_membership_code(user_id):
    if user_id == ADMIN_ID:
        return "mabsa-10000"
    else:
        number = random.randint(10000, 99999)
        return f"mabsa-{number}"


def save_course_to_db(data):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO courses (name, capacity, photo_url, caption, card_number, course_code, price_member, price_non_member)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['name'], data['capacity'], data['photo_url'], data['caption'],
            data['card_number'], data['course_code'], data['price_member'], data['price_non_member']
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True


def delete_course_by_id(course_id: int):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM courses WHERE id=?', (course_id,))
    cursor.execute(
        'DELETE FROM course_registrations WHERE course_id=?', (course_id,))
    conn.commit()
    conn.close()


def get_course_by_name(name):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, capacity, registered_count, photo_url, caption, card_number, course_code, price_member, price_non_member FROM courses WHERE name=?', (name,))
    result = cursor.fetchone()
    conn.close()
    return result


def get_course_by_id(course_id):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, capacity, registered_count, photo_url, caption, card_number, course_code, price_member, price_non_member FROM courses WHERE id=?', (course_id,))
    result = cursor.fetchone()
    conn.close()
    return result


def get_course_registrations(course_id):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, fullname_fa, student_id, phone, registration_code FROM course_registrations WHERE course_id=?', (course_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_registration_code_for_user(telegram_id: int, course_id: int) -> str | None:
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT registration_code FROM course_registrations WHERE telegram_id=? AND course_id=?', (telegram_id, course_id))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def check_course_registration(telegram_id, course_id):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id FROM course_registrations WHERE telegram_id=? AND course_id=?', (telegram_id, course_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def save_course_registration(data):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO course_registrations (course_id, telegram_id, fullname_fa, student_id, national_id, phone, payment_proof, registration_code, is_member)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['course_id'], data['telegram_id'], data['fullname_fa'], data['student_id'],
            data['national_id'], data['phone'], data['payment_proof'], data['registration_code'], data['is_member']
        ))
        cursor.execute(
            'UPDATE courses SET registered_count = registered_count + 1 WHERE id=?', (data['course_id'],))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True


def generate_course_code(course_id):
    return f"course_CODE_{course_id:04d}"


def generate_registration_code():
    return f"course_{random.randint(1000, 9999)}"

# --- هندلرهای جدید برای انتخابات ---


def get_all_candidates():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, name FROM candidates')
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_candidate_by_id(cand_id):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, name, field, desc, photo FROM candidates WHERE id=?', (cand_id,))
    result = cursor.fetchone()
    conn.close()
    return result


def save_candidate_to_db(data):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO candidates (name, field, desc, photo)
        VALUES (?, ?, ?, ?)
    ''', (data['name'], data['field'], data['desc'], data['photo']))
    conn.commit()
    conn.close()


def delete_candidate_by_id(cand_id):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM candidates WHERE id=?', (cand_id,))
    conn.commit()
    conn.close()


def has_voted(telegram_id):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM votes WHERE telegram_id=?', (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def save_vote(telegram_id, voted_list):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    voted_str = json.dumps(voted_list)
    cursor.execute('''
        INSERT INTO votes (telegram_id, voted_candidates)
        VALUES (?, ?)
    ''', (telegram_id, voted_str))
    conn.commit()
    conn.close()


def get_all_votes():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT telegram_id, voted_candidates FROM votes')
    rows = cursor.fetchall()
    conn.close()
    return [(tid, json.loads(voted)) for tid, voted in rows]


def clear_votes():
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM votes')
    conn.commit()
    conn.close()


def get_candidate_name(cand_id):
    candidate = get_candidate_by_id(cand_id)
    return candidate[1] if candidate else "نامشخص"

# --- هندلرهای منوی اصلی ---


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "🤝 عضویت در انجمن":
        return await membership_handler(update, context)
    elif text == "🗂️ درباره انجمن":
        await update.message.reply_text(
            "لطفا یکی از گزینه‌ها را انتخاب کنید.",
            reply_markup=about_keyboard()
        )
        return ABOUT_MENU
    elif text == "📚 ثبت‌نام دوره‌ها":
        keyboard = get_user_courses_keyboard()
        if not keyboard:
            await update.message.reply_text(
                "📚 هیچ دوره‌ای در حال حاضر موجود نیست یا ظرفیت همه دوره‌ها تکمیل شده است.",
                reply_markup=get_main_keyboard(user_id)
            )
            return MAIN_MENU
        await update.message.reply_text(
            "📚 لطفا یکی از دوره‌ها را انتخاب کنید:",
            reply_markup=keyboard
        )
        return USER_COURSE_MENU
    elif text == "💬 ارتباط با دبیر":
        await update.message.reply_text(
            get_secretary_message(),
            reply_markup=get_main_keyboard(user_id)
        )
        return MAIN_MENU
    elif text == "🗳️ انتخابات":
        return await election_handler(update, context)
    elif text == "🛠 پنل ادمین" and user_id == ADMIN_ID:
        return await admin_panel(update, context)
    else:
        await update.message.reply_text(
            "لطفا یکی از گزینه‌های منو را انتخاب کنید.",
            reply_markup=get_main_keyboard(user_id)
        )
        return MAIN_MENU

# --- هندلر انتخابات کاربر ---


async def election_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not get_member_by_telegram_id(user_id):
        await update.message.reply_text(
            "⚠️ شما عضو انجمن نیستید و نمی‌توانید رای دهید.",
            reply_markup=get_main_keyboard(user_id)
        )
        return MAIN_MENU
    if not election_active:
        await update.message.reply_text(
            "⚠️ انتخابات در حال حاضر فعال نیست.",
            reply_markup=get_main_keyboard(user_id)
        )
        return MAIN_MENU
    if has_voted(user_id):
        await update.message.reply_text(
            "⚠️ شما قبلاً رای داده‌اید.",
            reply_markup=get_main_keyboard(user_id)
        )
        return MAIN_MENU
    candidates = get_all_candidates()
    if not candidates:
        await update.message.reply_text(
            "⚠️ هیچ کاندیدایی ثبت نشده است.",
            reply_markup=get_main_keyboard(user_id)
        )
        return MAIN_MENU
    text = "🗳️ کاندیداهای تایید شده:\n"
    for cand_id, name in candidates:
        cand = get_candidate_by_id(cand_id)
        text += f"\n{name} - {cand[2]}\n{cand[3]}\n"
        if cand[4]:
            await update.message.reply_photo(photo=cand[4], caption=f"{name}")
    await update.message.reply_text(
        text,
        reply_markup=get_candidates_keyboard(for_voting=True)
    )
    context.user_data['selected_votes'] = []
    return USER_ELECTION_MENU


async def process_user_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if data == "vote_done":
        selected = context.user_data.get('selected_votes', [])
        if len(selected) > 5:
            await query.edit_message_text("⚠️ حداکثر ۵ رای مجاز است!")
            return USER_ELECTION_MENU
        if not selected:
            await query.edit_message_text("⚠️ حداقل یک کاندیدا انتخاب کنید.")
            return USER_ELECTION_MENU
        save_vote(user_id, selected)
        names = [get_candidate_name(c) for c in selected]
        await query.edit_message_text(f"✅ رای شما ثبت شد: {', '.join(names)}")
        # ارسال به گروه نتایج
        result_msg = f"رای دهنده: https://t.me/@id{update.effective_user.id}\nرای به: {', '.join(names)}"
        await context.bot.send_message(chat_id=ELECTION_RESULTS_GROUP_ID, text=result_msg)
        await query.message.reply_text("بازگشت به منوی اصلی.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    cand_id = int(data.split("_")[1])
    selected = context.user_data.get('selected_votes', [])
    if cand_id in selected:
        selected.remove(cand_id)
    else:
        if len(selected) < 5:
            selected.append(cand_id)
        else:
            await query.answer("حداکثر ۵ رای!")
            return USER_ELECTION_MENU
    context.user_data['selected_votes'] = selected
    await query.edit_message_reply_markup(reply_markup=get_candidates_keyboard(for_voting=True, selected=selected))
    return USER_ELECTION_MENU

# --- هندلرهای ثبت‌نام عضویت ---


async def membership_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not membership_active:
        await update.message.reply_text(
            "⚠️ این بخش توسط ادمین غیرفعال گردیده.",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return MAIN_MENU
    telegram_id = update.message.from_user.id
    member = get_member_by_telegram_id(telegram_id)
    if member:
        membership_code = member[0]
        await update.message.reply_text(
            f"شما قبلاً عضو شده‌اید.\nکد عضویت شما: {membership_code}",
            reply_markup=get_main_keyboard(telegram_id)
        )
        return MAIN_MENU
    else:
        await update.message.reply_text(
            "لطفا نام و نام خانوادگی فارسی خود را وارد کنید.",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ ابطال عضویت"]], resize_keyboard=True)
        )
        return ASK_FULLNAME_FA


async def ask_fullname_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if not re.fullmatch(r"[آ-ی ]+", text):
        await update.message.reply_text("لطفا فقط از حروف فارسی استفاده کنید و دوباره تلاش کنید.")
        return ASK_FULLNAME_FA
    formatted = " ".join(word.capitalize() for word in text.split())
    context.user_data['fullname_fa'] = formatted
    await update.message.reply_text(
        f"آیا نام شما {formatted} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_FULLNAME_FA


async def confirm_fullname_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا نام و نام خانوادگی انگلیسی خود را وارد کنید.\n\nمثال: Ali Daei",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ ابطال عضویت"]], resize_keyboard=True)
        )
        return ASK_FULLNAME_EN
    elif text == "رد ❌":
        await update.message.reply_text("لطفا نام و نام خانوادگی فارسی خود را دوباره وارد کنید.")
        return ASK_FULLNAME_FA
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_FULLNAME_FA


async def ask_fullname_e(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if not re.fullmatch(r"[A-Za-z ]+", text):
        await update.message.reply_text("لطفا فقط از حروف انگلیسی استفاده کنید و دوباره تلاش کنید.")
        return ASK_FULLNAME_EN
    formatted = " ".join(word.capitalize() for word in text.split())
    context.user_data['fullname_e'] = formatted
    await update.message.reply_text(
        f"آیا نام شما {formatted} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_FULLNAME_EN


async def confirm_fullname_e(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا شماره دانشجویی ۹ رقمی خود را وارد کنید.\n\nمثال: 123456789",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ ابطال عضویت"]], resize_keyboard=True)
        )
        return ASK_STUDENT_ID
    elif text == "رد ❌":
        await update.message.reply_text("لطفا نام و نام خانوادگی انگلیسی خود را دوباره وارد کنید.")
        return ASK_FULLNAME_EN
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_FULLNAME_EN


async def ask_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if not re.fullmatch(r"\d{9}", text):
        await update.message.reply_text("لطفا شماره دانشجویی ۹ رقمی را فقط با اعداد انگلیسی وارد کنید.")
        return ASK_STUDENT_ID
    context.user_data['student_id'] = text
    await update.message.reply_text(
        f"آیا شماره دانشجویی شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_STUDENT_ID


async def confirm_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا کد ملی ۱۰ رقمی خود را وارد کنید.\n\nمثال: 1234567890",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ ابطال عضویت"]], resize_keyboard=True)
        )
        return ASK_NATIONAL_ID
    elif text == "رد ❌":
        await update.message.reply_text("لطفا شماره دانشجویی خود را دوباره وارد کنید.")
        return ASK_STUDENT_ID
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_STUDENT_ID


async def ask_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if not re.fullmatch(r"\d{10}", text):
        await update.message.reply_text("لطفا کد ملی ۱۰ رقمی را فقط با اعداد انگلیسی وارد کنید.")
        return ASK_NATIONAL_ID
    context.user_data['national_id'] = text
    await update.message.reply_text(
        f"آیا کد ملی شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_NATIONAL_ID


async def confirm_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا شماره تماس ۱۱ رقمی خود را وارد کنید.\n\nمثال: 09123456789",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ ابطال عضویت"]], resize_keyboard=True)
        )
        return ASK_PHONE
    elif text == "رد ❌":
        await update.message.reply_text("لطفا کد ملی خود را دوباره وارد کنید.")
        return ASK_NATIONAL_ID
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_NATIONAL_ID


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if not re.fullmatch(r"09\d{9}", text):
        await update.message.reply_text("لطفا شماره تماس ۱۱ رقمی را با شروع 09 و فقط با اعداد انگلیسی وارد کنید.")
        return ASK_PHONE
    context.user_data['phone'] = text
    await update.message.reply_text(
        f"آیا شماره تماس شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_PHONE


async def confirm_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا رشته تحصیلی خود را انتخاب کنید.",
            reply_markup=get_majors_keyboard()
        )
        return ASK_MAJOR
    elif text == "رد ❌":
        await update.message.reply_text("لطفا شماره تماس خود را دوباره وارد کنید.")
        return ASK_PHONE
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_PHONE


async def ask_major(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال عضویت":
        await update.message.reply_text("عضویت لغو شد.", reply_markup=get_main_keyboard(user_id))
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
        "🖥️ علوم کامپیوتر",
        "🌀 سایر رشته ها "
    ]
    if text not in majors:
        await update.message.reply_text("لطفا یکی از رشته‌های موجود در کیبورد را انتخاب کنید.")
        return ASK_MAJOR
    context.user_data['major'] = text
    await update.message.reply_text(
        f"آیا رشته تحصیلی شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_MAJOR


async def confirm_major(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        return await finalize_registration(update, context)
    elif text == "رد ❌":
        await update.message.reply_text("لطفا رشته تحصیلی خود را دوباره انتخاب کنید.", reply_markup=get_majors_keyboard())
        return ASK_MAJOR
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_MAJOR


async def finalize_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    membership_code = generate_membership_code(update.effective_user.id)
    user_data['membership_code'] = membership_code
    user_id = update.message.from_user.id
    data_to_save = {
        'fullname_fa': user_data['fullname_fa'],
        'fullname_e': user_data['fullname_e'],
        'student_id': user_data['student_id'],
        'national_id': user_data['national_id'],
        'phone': user_data['phone'],
        'major': user_data['major'],
        'telegram_id': user_id,
        'membership_code': membership_code
    }
    saved = save_member_to_db(data_to_save)
    if not saved:
        await update.message.reply_text("شما قبلا ثبت‌نام کرده‌اید و اطلاعات تکراری است.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    await update.message.reply_text(
        f"🎉 عضویت شما با موفقیت ثبت شد!\n"
        f"کد عضویت شما: {membership_code}\n"
        f"به انجمن علمی دانشجویی مبسا خوش آمدید!",
        reply_markup=get_main_keyboard(user_id)
    )

    # پیام دوم با لینک گروه
    # لینک گروه مجمع عمومی رو اینجا بذار
    group_link = "https://t.me/+JXHmjI36Qvc3OGJk"
    await update.message.reply_text(
        f"📢 عضویت در گروه مجمع عمومی الزامی است.\n"
        f"برای ورود کلیک کنید: {group_link}"
    )

    info_msg = (
        f"عضو جدید ثبت شد:\n"
        f"نام فارسی: {user_data['fullname_fa']}\n"
        f"نام انگلیسی: {user_data['fullname_e']}\n"
        f"شماره دانشجویی: {user_data['student_id']}\n"
        f"کد ملی: {user_data['national_id']}\n"
        f"شماره تماس: {user_data['phone']}\n"
        f"رشته تحصیلی: {user_data['major']}\n"
        f"آیدی عددی: https://t.me/@id{update.effective_user.id}\n"
        f"کد عضویت: {membership_code}"
    )
    await context.bot.send_message(chat_id=GROUP_ID, text=info_msg)
    return MAIN_MENU

# --- هندلرهای پنل ادمین ---


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    text = update.message.text
    if text == "🛠 پنل ادمین":
        await update.message.reply_text(
            "پنل ادمین:\nلطفا یک گزینه را انتخاب کنید.",
            reply_markup=get_admin_keyboard()
        )
        return ADMIN_PANEL
    else:
        await update.message.reply_text(
            "لطفا یک گزینه را از کیبورد انتخاب کنید.",
            reply_markup=get_admin_keyboard()
        )
        return ADMIN_PANEL


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global membership_active
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU

    # === Members List: Issuance / View with inline delete ===
    if text == "لیست اعضا":
        await update.message.reply_text(
            "یکی از گزینه‌های مربوط به اعضا را انتخاب کنید:",
            reply_markup=get_members_list_keyboard()
        )
        return ADMIN_PANEL

    elif text == "📤 صدور":
        members = get_all_members_full()
        if not members:
            await update.message.reply_text("هیچ عضوی ثبت نشده.", reply_markup=get_members_list_keyboard())
            return ADMIN_PANEL
        blocks = []
        for idx, (mid, fa, en, sid, nid, phone, major, mcode) in enumerate(members, start=1):
            block = (
                f"{idx}. نام فارسی: {fa or '—'}\n"
                f"کدملی: {nid or '—'}\n"
                f"شماره دانشجویی: {sid or '—'}\n"
                f"رشته تحصیلی: {major or '—'}\n"
                f"شماره تماس: {phone or '—'}\n"
                f"کد عضویت: {mcode or '—'}"
            )
            blocks.append(block)
        for batch in chunk_list(blocks, size=15):
            await update.message.reply_text("\n\n".join(batch))
        await update.message.reply_text("پایان صدور ✅", reply_markup=get_members_list_keyboard())
        return ADMIN_PANEL

    elif text == "📖 مشاهده":
        members = get_all_members_full()
        if not members:
            await update.message.reply_text("هیچ عضوی ثبت نشده.", reply_markup=get_members_list_keyboard())
            return ADMIN_PANEL
        for mid, fa, en, sid, nid, phone, major, mcode in members:
            caption = (
                f"👤 {fa or '—'}\n"
                f"نام انگلیسی: {en or '—'}\n"
                f"شماره دانشجویی: {sid or '—'}\n"
                f"کدملی: {nid or '—'}\n"
                f"شماره تماس: {phone or '—'}\n"
                f"رشته تحصیلی: {major or '—'}\n"
                f"کد عضویت: {mcode or '—'}"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ حذف کاربر", callback_data=f"del_member_{mid}")]])
            await update.message.reply_text(caption, reply_markup=kb)
        await update.message.reply_text("نمایش تمام اعضا پایان یافت ✅", reply_markup=get_members_list_keyboard())
        return ADMIN_PANEL
    if text == "لیست اعضا":
        return await show_members_list(update, context)
    elif text == "فعال/غیرفعالسازی عضویت":
        membership_active = not membership_active
        status = "فعال" if membership_active else "غیرفعال"
        await update.message.reply_text(
            f"✅ عضویت اکنون {status} است.",
            reply_markup=get_admin_keyboard()
        )
        return ADMIN_PANEL
    elif text == "دبیر":
        await update.message.reply_text(
            "لطفا متن جدید برای ارتباط با دبیر را وارد کنید یا 'لغو' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_SECRETARY_MESSAGE
    elif text == "اهداف":
        await update.message.reply_text(
            "لطفا متن جدید برای اهداف انجمن را وارد کنید یا 'لغو' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_ABOUT_MESSAGE
    elif text == "شورا":
        await update.message.reply_text(
            "کدام شورا را می‌خواهید تغییر دهید؟",
            reply_markup=council_slots_keyboard()
        )
        return ASK_COUNCIL_SLOT

    elif text == "دوره‌ها":
        await update.message.reply_text(
            "لطفا یکی از دوره‌ها را انتخاب کنید یا برای افزودن دوره جدید، 'افزودن دوره' را انتخاب کنید.",
            reply_markup=get_courses_keyboard()
        )
        return ADMIN_COURSE_MENU
    elif text == "انتخابات":
        await update.message.reply_text(
            "پنل مدیریت انتخابات:",
            reply_markup=get_admin_election_keyboard()
        )
        return ADMIN_ELECTION_MENU
    elif text == "بازگشت":
        await update.message.reply_text("بازگشت به منوی اصلی.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    else:
        await update.message.reply_text(
            "لطفا یک گزینه را از کیبورد انتخاب کنید.",
            reply_markup=get_admin_keyboard()
        )
        return ADMIN_PANEL

async def admin_council_pick_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU

    if text == "بازگشت":
        await update.message.reply_text("بازگشت به پنل ادمین.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL

    if not re.fullmatch(r"شورا([1-6]|[۱-۶])", text):
        await update.message.reply_text("لطفاً یکی از گزینه‌های شورا ۱ تا ۶ را انتخاب کنید.", reply_markup=council_slots_keyboard())
        return ASK_COUNCIL_SLOT

    slot = int(_normalize_digits(text.replace("شورا", "")))
    context.user_data['council_slot'] = slot

    current = get_council_item(slot)
    preview = f"🔹 وضعیت فعلی شورا {slot}:\n\n{current['text'] or '—'}"
    await update.message.reply_text(preview)

    await update.message.reply_text(
        f"متن جدید برای شورا {slot} را وارد کنید:",
        reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
    )
    return ASK_COUNCIL_TEXT


async def admin_council_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "لغو":
        await update.message.reply_text("ویرایش شورا لغو شد.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL

    context.user_data['council_text'] = text.strip()
    await update.message.reply_text(
        f"آیا متن زیر تأیید می‌شود؟\n\n{text}",
        reply_markup=ReplyKeyboardMarkup([["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COUNCIL_TEXT


async def admin_council_text_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "عکس وارد کنید — یا «بدون عکس» را بزنید.",
            reply_markup=ReplyKeyboardMarkup([["بدون عکس"], ["لغو"]], resize_keyboard=True)
        )
        return ASK_COUNCIL_PHOTO2
    elif text == "رد ❌":
        await update.message.reply_text(
            "متن جدید شورا را دوباره وارد کنید:",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COUNCIL_TEXT
    else:
        await update.message.reply_text("لطفاً از دکمه‌های تعیین‌شده استفاده کنید.", reply_markup=ReplyKeyboardMarkup([["✅ تأیید", "رد ❌"]], resize_keyboard=True))
        return CONFIRM_COUNCIL_TEXT


async def admin_council_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # می‌تواند عکس آپلود کند یا «بدون عکس» را بزند
    if update.message.text == "لغو":
        await update.message.reply_text("ویرایش شورا لغو شد.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL

    if update.message.text == "بدون عکس":
        photo = None
    elif update.message.photo:
        # آخرین سایز بهترین کیفیت است
        photo = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("لطفاً عکس آپلود کنید یا «بدون عکس» را انتخاب کنید.")
        return ASK_COUNCIL_PHOTO2

    context.user_data['council_photo'] = photo

    preview = f"🧾 خلاصه تغییرات:\nشورا {context.user_data['council_slot']}\n\nمتن:\n{context.user_data['council_text']}\n"
    preview += "عکس: " + ("✅ دارد" if photo else "⛔ ندارد")
    await update.message.reply_text(
        preview,
        reply_markup=ReplyKeyboardMarkup([["✅ ثبت نهایی", "لغو"]], resize_keyboard=True)
    )
    return CONFIRM_COUNCIL_SAVE


async def admin_council_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "لغو":
        await update.message.reply_text("ویرایش شورا لغو شد.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL

    if text != "✅ ثبت نهایی":
        await update.message.reply_text("لطفاً از دکمه‌های تعیین‌شده استفاده کنید.", reply_markup=ReplyKeyboardMarkup([["✅ ثبت نهایی", "لغو"]], resize_keyboard=True))
        return CONFIRM_COUNCIL_SAVE

    slot = context.user_data.get('council_slot')
    msg = context.user_data.get('council_text', '')
    photo = context.user_data.get('council_photo')

    set_council_item(slot, msg, photo)

    await update.message.reply_text("✅ با موفقیت تغییر یافت.", reply_markup=get_admin_keyboard())
    return ADMIN_PANEL

async def admin_election_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global election_active  # اعلان global در ابتدای تابع

    text = update.message.text
    user_id = update.message.from_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU

    if text == "➕ افزودن کاندیدا":
        await update.message.reply_text(
            "لطفا نام کاندیدا را وارد کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_CANDIDATE_NAME

    elif text == "فعال/غیرفعال انتخابات":
        election_active = not election_active
        status = "فعال" if election_active else "غیرفعال"
        await update.message.reply_text(
            f"✅ انتخابات اکنون {status} است.",
            reply_markup=get_admin_election_keyboard()
        )
        return ADMIN_ELECTION_MENU

    elif text == "📋 مشاهده آرا":
        votes = get_all_votes()
        if not votes:
            await update.message.reply_text("📭 هیچ رایی ثبت نشده است.", reply_markup=get_admin_election_keyboard())
            return ADMIN_ELECTION_MENU
        message = "📋 آرا:\n"
        for tid, voted in votes:
            membership_code = get_membership_code_by_telegram_id(
                tid) or "نامشخص"
            names = [get_candidate_name(c) for c in voted]
            message += f"کد عضویت: {membership_code} - رای به: {', '.join(names)}\n"
        await update.message.reply_text(message, reply_markup=get_admin_election_keyboard())
        return ADMIN_ELECTION_MENU

    elif text == "🏁 پایان انتخابات":
        votes = get_all_votes()
        if not votes:
            await update.message.reply_text("📭 هیچ رایی ثبت نشده است.", reply_markup=get_admin_election_keyboard())
            return ADMIN_ELECTION_MENU
        total_votes = len(votes)
        vote_count = {}
        for _, voted in votes:
            for c in voted:
                vote_count[c] = vote_count.get(c, 0) + 1
        message = "📊 نتایج کلی انتخابات:\n"
        for cand_id, count in sorted(vote_count.items(), key=lambda x: x[1], reverse=True):
            name = get_candidate_name(cand_id)
            percent = (count / total_votes) * 100 if total_votes > 0 else 0
            message += f"{name}: {count} رای ({percent:.2f}%)\n"
        await context.bot.send_message(chat_id=ELECTION_RESULTS_GROUP_ID, text=message)
        clear_votes()
        election_active = False
        await update.message.reply_text("✅ انتخابات پایان یافت و نتایج ارسال شد.", reply_markup=get_admin_election_keyboard())
        return ADMIN_ELECTION_MENU

    elif text == "بازگشت":
        await update.message.reply_text("بازگشت به پنل ادمین.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL
    elif text == "📄 مشاهده کاندیداها":
        candidates = get_all_candidates()
        if not candidates:
            await update.message.reply_text("⚠️ هیچ کاندیدایی ثبت نشده است.", reply_markup=get_admin_election_keyboard())
            return ADMIN_ELECTION_MENU

        # نمایش مرتب با عکس/بدون عکس (مشابه بخش else فعلی، اما صریح زیر این دکمه)
        for cand_id, name in candidates:
            # (id, name, field, desc, photo)
            cand = get_candidate_by_id(cand_id)
            caption = f"{name} - {cand[2]}\n{cand[3]}"
            if cand[4]:
                await update.message.reply_photo(photo=cand[4], caption=caption, reply_markup=get_candidate_management_keyboard(cand_id))
            else:
                await update.message.reply_text(caption, reply_markup=get_candidate_management_keyboard(cand_id))
        return ADMIN_ELECTION_MENU

    elif text == "🗑️ حذف کاندیدا":
        kb = build_delete_candidates_keyboard()
        if not kb:
            await update.message.reply_text("⚠️ هیچ کاندیدایی برای حذف وجود ندارد.", reply_markup=get_admin_election_keyboard())
            return ADMIN_ELECTION_MENU
        await update.message.reply_text("یک کاندیدا را برای حذف انتخاب کنید:", reply_markup=kb)
        return ADMIN_ELECTION_MENU

    else:
        candidates = get_all_candidates()
        if not candidates:
            await update.message.reply_text("⚠️ هیچ کاندیدایی یافت نشد.", reply_markup=get_admin_election_keyboard())
            return ADMIN_ELECTION_MENU
        for cand_id, name in candidates:
            cand = get_candidate_by_id(cand_id)
            text = f"{name} - {cand[2]}\n{cand[3]}"
            if cand[4]:
                await update.message.reply_photo(photo=cand[4], caption=text, reply_markup=get_candidate_management_keyboard(cand_id))
            else:
                await update.message.reply_text(text, reply_markup=get_candidate_management_keyboard(cand_id))
        return ADMIN_ELECTION_MENU


async def ask_candidate_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "لغو":
        await update.message.reply_text("افزودن کاندیدا لغو شد.", reply_markup=get_admin_election_keyboard())
        return ADMIN_ELECTION_MENU
    context.user_data['candidate_name'] = text
    await update.message.reply_text(
        f"آیا نام کاندیدا '{text}' تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_CANDIDATE_NAME


async def confirm_candidate_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفاً رشتهٔ کاندیدا را از کیبورد انتخاب کنید:",
            reply_markup=get_majors_keyboard_election()
        )
        return ASK_CANDIDATE_FIELD
    elif text == "رد ❌":
        await update.message.reply_text("لطفاً نام کاندیدا را دوباره وارد کنید.")
        return ASK_CANDIDATE_NAME
    else:
        await update.message.reply_text("لطفاً فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_CANDIDATE_NAME


async def ask_candidate_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "لغو":
        await update.message.reply_text("افزودن کاندیدا لغو شد.", reply_markup=get_admin_election_keyboard())
        return ADMIN_ELECTION_MENU

    valid_majors = [
        "⚡️ مهندسی انرژی",
        "💡 مهندسی برق",
        "💻 مهندسی کامپیوتر",
        "🧪 مهندسی شیمی",
        "🏗️ مهندسی عمران",
        "🏭 مهندسی صنایع",
        "🛢️ مهندسی نفت",
        "🔢 ریاضیات و کاربردها",
        "🖥️ علوم کامپیوتر",
        "🌀 سایر رشته ها "
    ]
    if text not in valid_majors:
        await update.message.reply_text(
            "لطفاً رشته را از دکمه‌های کیبورد انتخاب کنید.",
            reply_markup=get_majors_keyboard_election()
        )
        return ASK_CANDIDATE_FIELD

    context.user_data['candidate_field'] = text
    await update.message.reply_text(
        f"آیا رشتهٔ «{text}» تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup([["✅ تأیید", "رد ❌"]], resize_keyboard=True),
    )
    return CONFIRM_CANDIDATE_FIELD
    context.user_data['candidate_field'] = text
    await update.message.reply_text(
        f"آیا رشته '{text}' تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_CANDIDATE_FIELD


async def confirm_candidate_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفاً مشخصات (توضیحات) کاندیدا را وارد کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True),
        )
        return ASK_CANDIDATE_DESC
    elif text == "رد ❌":
        await update.message.reply_text(
            "لطفاً رشتهٔ کاندیدا را از کیبورد انتخاب کنید:",
            reply_markup=get_majors_keyboard_election()
        )
        return ASK_CANDIDATE_FIELD
    else:
        await update.message.reply_text("لطفاً فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_CANDIDATE_FIELD


async def ask_candidate_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "لغو":
        await update.message.reply_text("افزودن کاندیدا لغو شد.", reply_markup=get_admin_election_keyboard())
        return ADMIN_ELECTION_MENU
    context.user_data['candidate_desc'] = text
    await update.message.reply_text(
        f"آیا توضیحات '{text}' تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_CANDIDATE_DESC


async def confirm_candidate_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا عکس کاندیدا را آپلود کنید یا 'بدون عکس' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup(
                [["بدون عکس"], ["لغو"]], resize_keyboard=True)
        )
        return ASK_CANDIDATE_PHOTO
    elif text == "رد ❌":
        await update.message.reply_text("لطفا مشخصات کاندیدا را دوباره وارد کنید.")
        return ASK_CANDIDATE_DESC
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_CANDIDATE_DESC


async def ask_candidate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text if update.message.text else None
    if text == "لغو":
        await update.message.reply_text("افزودن کاندیدا لغو شد.", reply_markup=get_admin_election_keyboard())
        return ADMIN_ELECTION_MENU
    elif text == "بدون عکس":
        photo = None
    elif update.message.photo:
        photo = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("لطفا عکس آپلود کنید یا 'بدون عکس' انتخاب کنید.")
        return ASK_CANDIDATE_PHOTO
    data = {
        'name': context.user_data['candidate_name'],
        'field': context.user_data['candidate_field'],
        'desc': context.user_data['candidate_desc'],
        'photo': photo
    }
    save_candidate_to_db(data)
    await update.message.reply_text("✅ کاندیدا اضافه شد.", reply_markup=get_admin_election_keyboard())
    return ADMIN_ELECTION_MENU


async def admin_delete_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ شما دسترسی ادمین ندارید.")
        return
    try:
        cand_id = int(query.data.split("_")[2])
    except Exception:
        await query.edit_message_text("داده نامعتبر است.")
        return
    delete_candidate_by_id(cand_id)
    await query.edit_message_text("✅ کاندیدا حذف شد.")

# --- هندلرهای مدیریت دوره‌ها در پنل ادمین ---



# --- هندلرهای مدیریت دوره‌ها در پنل ادمین ---
async def course_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # === PATCH: Ensure export/view is handled before course-name lookup ===
    try:
        user_id = update.message.from_user.id if update.message else (update.callback_query.from_user.id if update.callback_query else None)
    except Exception:
        user_id = None
    try:
        text = (update.message.text if update.message else (update.callback_query.data if update.callback_query else "")) or ""
    except Exception:
        text = ""
    text = text.strip()

    # If an admin already selected a course (stored earlier) and now taps "📤 صدور" or "📖 مشاهده",
    # handle it here and return early. This prevents interpreting these labels as a course name.
    if context.user_data.get("list_course_id") and (("صدور" in text) or ("مشاهده" in text)):
        course_id = context.user_data["list_course_id"]
        try:
            regs = get_course_registrations_full(course_id) or []
        except Exception:
            regs = []

        # "📤 صدور"
        if "صدور" in text:
            if not regs:
                try:
                    await update.message.reply_text("📭 هیچ ثبت‌نامی برای این دوره وجود ندارد.", reply_markup=get_course_regs_keyboard())
                except Exception:
                    if update.callback_query:
                        await update.callback_query.message.reply_text("📭 هیچ ثبت‌نامی برای این دوره وجود ندارد.", reply_markup=get_course_regs_keyboard())
                return ADMIN_COURSE_MENU
            try:
                await _send_course_regs_export(update, context, course_id, regs)
            except Exception as e:
                # Best-effort message; avoids crashing the handler
                try:
                    await update.message.reply_text(f"خطا در صدور لیست: {e}", reply_markup=get_course_regs_keyboard())
                except Exception:
                    if update.callback_query:
                        await update.callback_query.message.reply_text(f"خطا در صدور لیست: {e}", reply_markup=get_course_regs_keyboard())
                return ADMIN_COURSE_MENU
            try:
                await update.message.reply_text("پایان صدور ✅", reply_markup=get_course_regs_keyboard())
            except Exception:
                if update.callback_query:
                    await update.callback_query.message.reply_text("پایان صدور ✅", reply_markup=get_course_regs_keyboard())
            return ADMIN_COURSE_MENU

        # "📖 مشاهده"
        else:
            if not regs:
                try:
                    await update.message.reply_text("📭 هیچ ثبت‌نامی برای این دوره وجود ندارد.", reply_markup=get_course_regs_keyboard())
                except Exception:
                    if update.callback_query:
                        await update.callback_query.message.reply_text("📭 هیچ ثبت‌نامی برای این دوره وجود ندارد.", reply_markup=get_course_regs_keyboard())
                return ADMIN_COURSE_MENU
            try:
                await _send_course_regs_view_per_person(update, context, regs)
            except Exception as e:
                try:
                    await update.message.reply_text(f"خطا در نمایش لیست: {e}", reply_markup=get_course_regs_keyboard())
                except Exception:
                    if update.callback_query:
                        await update.callback_query.message.reply_text(f"خطا در نمایش لیست: {e}", reply_markup=get_course_regs_keyboard())
                return ADMIN_COURSE_MENU
            try:
                await update.message.reply_text("نمایش تمام ثبت‌نام‌ها پایان یافت ✅", reply_markup=get_course_regs_keyboard())
            except Exception:
                if update.callback_query:
                    await update.callback_query.message.reply_text("نمایش تمام ثبت‌نام‌ها پایان یافت ✅", reply_markup=get_course_regs_keyboard())
            return ADMIN_COURSE_MENU
    # === END PATCH ===

    user_id = update.message.from_user.id if update.message else (update.callback_query.from_user.id if update.callback_query else None)
    text = (update.message.text if update.message else (update.callback_query.data if update.callback_query else "")) or ""
    text = text.strip()

    # 1) بازگشت به پنل ادمین
    if text == "بازگشت":
        await update.message.reply_text("بازگشت به پنل ادمین.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL

    # 2) رفتن به فلو افزودن دوره
    if text == "➕ افزودن دوره":
        await update.message.reply_text(
            "نام دوره را وارد کنید:",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_NAME

        # 3) صدور/مشاهده لیست ثبت‌نام‌کنندگان برای course_id انتخاب‌شده
        if context.user_data.get("list_course_id") and (("صدور" in text) or ("مشاهده" in text)):
            course_id = context.user_data["list_course_id"]
            regs = get_course_registrations_full(course_id) or []
            if text == "📤 صدور":
                if not regs:
                    await update.message.reply_text("📭 هیچ ثبت‌نامی برای این دوره وجود ندارد.", reply_markup=get_course_regs_keyboard())
                    return ADMIN_COURSE_MENU
                await _send_course_regs_export(update, context, course_id, regs)
                await update.message.reply_text("پایان صدور ✅", reply_markup=get_course_regs_keyboard())
                return ADMIN_COURSE_MENU
            else:  # 📖 مشاهده
                if not regs:
                    await update.message.reply_text("📭 هیچ ثبت‌نامی برای این دوره وجود ندارد.", reply_markup=get_course_regs_keyboard())
                    return ADMIN_COURSE_MENU
                await _send_course_regs_view_per_person(update, context, regs)
                await update.message.reply_text("نمایش تمام ثبت‌نام‌ها پایان یافت ✅", reply_markup=get_course_regs_keyboard())
                return ADMIN_COURSE_MENU

# 4) در غیر این صورت، متن را «نام دوره» در نظر بگیریم
    course = get_course_by_name(text)
    if not course:
        # نام دوره معتبر نیست
        await update.message.reply_text("❗️ دوره‌ای با این نام یافت نشد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU

    # course tuple: (id, name, capacity, registered_count, photo_url, caption, card_number, course_code, price_member, price_non_member)
    # نگه‌داری آیدی دوره برای صدور/مشاهده در مراحل بعدی
    context.user_data["list_course_id"] = course[0]
    course_id = course[0]
    name = course[1]
    capacity = course[2]
    registered = course[3]
    photo_url = course[4]
    caption = course[5]

    # ذخیره‌ی course_id برای استفاده‌ی بعدی در لیست/صدور
    context.user_data["list_course_id"] = course_id

    # پیش‌نمایش دوره برای ادمین
    header = f"📚 {name}\nظرفیت: {registered}/{capacity}"
    try:
        if photo_url:
            await update.message.reply_photo(photo=photo_url, caption=(caption or header))
        else:
            await update.message.reply_text(header + (f"\n\n{caption}" if caption else ""))
    except Exception:
        # اگر ارسال عکس خطا داد، متن بفرست
        await update.message.reply_text(header + (f"\n\n{caption}" if caption else ""))

    # دکمه‌های مدیریت (حذف/لیست ثبت‌نام‌کنندگان)
    await update.message.reply_text(
        "گزینه‌های مدیریت دوره:",
        reply_markup=get_course_management_keyboard(course_id)
    )
    # ماندن در همین منو
    return ADMIN_COURSE_MENU
    if text == "📖 مشاهده":
        # Send one message per registration with the exact emoji format and a delete button.
        for (reg_id, tg_id, fullname_fa, student_id, national_id, phone, reg_code, is_member) in regs:
            fullname_e, major, membership_code = get_member_profile_by_telegram(tg_id)
            membership_text = membership_code if membership_code else "غیر عضو"
            major_text = major if major else "—"
            caption = (
                f"👤 {fullname_fa or '—'}\n"
                f"نام انگلیسی: {fullname_e or '—'}\n"
                f"شماره دانشجویی: {student_id or '—'}\n"
                f"کدملی: {national_id or '—'}\n"
                f"شماره تماس: {phone or '—'}\n"
                f"رشته تحصیلی: {major_text}\n"
                f"کد عضویت: {membership_text}"
            )
            try:
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("❌ حذف", callback_data=f"del_reg_{reg_id}")]])
            except Exception:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("❌ حذف", callback_data=f"del_reg_{reg_id}")]])
            await update.message.reply_text(caption, reply_markup=btn)

        try:
            kb = get_course_regs_keyboard()
        except Exception:
            kb = None
        await update.message.reply_text("نمایش پایان یافت ✅", reply_markup=kb)
        return ADMIN_COURSE_MENU

    # Export: numbered text blocks + CSV file
    # Build numbered blocks
    blocks = []
    for idx, (reg_id, tg_id, fullname_fa, student_id, national_id, phone, reg_code, is_member) in enumerate(regs, start=1):
        _, major, membership_code = get_member_profile_by_telegram(tg_id)
        membership_text = membership_code if membership_code else "غیر عضو"
        major_text = major if major else "—"
        block = (
            f"{idx}. نام فارسی: {fullname_fa or '—'}\n"
            f"کدملی: {national_id or '—'}\n"
            f"شماره دانشجویی: {student_id or '—'}\n"
            f"رشته تحصیلی: {major_text}\n"
            f"شماره تماس: {phone or '—'}\n"
            f"کد عضویت: {membership_text}"
        )
        blocks.append(block)

    # Chunked sending to avoid Telegram limits (~4096)
    current = []
    total = 0
    for b in blocks:
        if total + len(b) + 2 > 3500:
            await update.message.reply_text("\\n\\n".join(current))
            current = [b]
            total = len(b) + 2
        else:
            current.append(b)
            total += len(b) + 2
    if current:
        await update.message.reply_text("\\n\\n".join(current))

    # CSV export
    import io, csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row", "reg_id", "course_id", "telegram_id", "fullname_fa", "student_id", "national_id", "phone", "registration_code", "is_member", "fullname_e", "major", "membership_code"])
    for i, (reg_id, tg_id, fullname_fa, student_id, national_id, phone, reg_code, is_member) in enumerate(regs, start=1):
        fullname_e, major, membership_code = get_member_profile_by_telegram(tg_id)
        writer.writerow([i, reg_id, course_id, tg_id, fullname_fa or "", student_id or "", national_id or "", phone or "", reg_code or "", int(bool(is_member)), fullname_e or "", major or "", membership_code or ""])

    csv_bytes = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    csv_bytes.name = f"course_{course_id}_registrations.csv"
    await update.message.reply_document(csv_bytes, caption="🧾 خروجی CSV ثبت‌نام‌کنندگان")

    try:
        kb = get_course_regs_keyboard()
    except Exception:
        kb = None
    await update.message.reply_text("صدور انجام شد ✅", reply_markup=kb)
    return ADMIN_COURSE_MENU


async def ask_course_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text("افزودن دوره لغو شد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU
    context.user_data['course_name'] = text
    await update.message.reply_text(
        f"آیا نام دوره '{text}' تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_NAME


async def confirm_course_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا ظرفیت دوره را وارد کنید (فقط عدد، مثال: 50).",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_CAPACITY
    elif text == "رد ❌":
        await update.message.reply_text("لطفا نام دوره را دوباره وارد کنید.")
        return ASK_COURSE_NAME
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_NAME


async def ask_course_capacity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text("افزودن دوره لغو شد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU
    if not re.fullmatch(r"\d+", text):
        await update.message.reply_text("لطفا فقط عدد وارد کنید (مثال: 50).")
        return ASK_COURSE_CAPACITY
    context.user_data['course_capacity'] = int(text)
    await update.message.reply_text(
        f"آیا ظرفیت دوره {text} نفر تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_CAPACITY


async def confirm_course_capacity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا تصویر دوره را آپلود کنید یا 'بدون تصویر' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup(
                [["بدون تصویر"], ["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_PHOTO
    elif text == "رد ❌":
        await update.message.reply_text("لطفا ظرفیت دوره را دوباره وارد کنید.")
        return ASK_COURSE_CAPACITY
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_CAPACITY


async def ask_course_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text("افزودن دوره لغو شد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU
    elif text == "بدون تصویر":
        context.user_data['course_photo_url'] = None
        await update.message.reply_text(
            "لطفا توضیحات (کپشن) دوره را وارد کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_CAPTION
    elif update.message.photo:
        context.user_data['course_photo_url'] = update.message.photo[-1].file_id
        await update.message.reply_text(
            "لطفا توضیحات (کپشن) دوره را وارد کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_CAPTION
    else:
        await update.message.reply_text(
            "لطفا یک تصویر آپلود کنید یا 'بدون تصویر' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup(
                [["بدون تصویر"], ["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_PHOTO


async def ask_course_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text("افزودن دوره لغو شد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU
    context.user_data['course_caption'] = text
    await update.message.reply_text(
        f"آیا توضیحات زیر برای دوره تأیید می‌شود؟\n\n{text}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_CAPTION


async def confirm_course_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا شماره کارت ادمین را وارد کنید (مثال: 1234-5678-9012-3456).",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_CARD
    elif text == "رد ❌":
        await update.message.reply_text("لطفا توضیحات دوره را دوباره وارد کنید.")
        return ASK_COURSE_CAPTION
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_CAPTION


async def ask_course_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text("افزودن دوره لغو شد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU
    context.user_data['course_card_number'] = text
    await update.message.reply_text(
        f"آیا شماره کارت {text} تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_CARD


async def confirm_course_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا قیمت برای اعضای انجمن را وارد کنید (مثال: 50000).",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_PRICE_MEMBER
    elif text == "رد ❌":
        await update.message.reply_text("لطفا شماره کارت را دوباره وارد کنید.")
        return ASK_COURSE_CARD
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_CARD


async def ask_course_price_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text("افزودن دوره لغو شد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU
    if not re.fullmatch(r"\d+", text):
        await update.message.reply_text("لطفا فقط عدد وارد کنید (مثال: 50000).")
        return ASK_COURSE_PRICE_MEMBER
    context.user_data['course_price_member'] = int(text)
    await update.message.reply_text(
        f"آیا قیمت برای اعضای انجمن {text} تومان تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_PRICE_MEMBER


async def confirm_course_price_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا قیمت برای غیراعضای انجمن را وارد کنید (مثال: 100000).",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COURSE_PRICE_NON_MEMBER
    elif text == "رد ❌":
        await update.message.reply_text("لطفا قیمت برای اعضای انجمن را دوباره وارد کنید.")
        return ASK_COURSE_PRICE_MEMBER
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_PRICE_MEMBER


async def ask_course_price_non_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text("افزودن دوره لغو شد.", reply_markup=get_courses_keyboard())
        return ADMIN_COURSE_MENU
    if not re.fullmatch(r"\d+", text):
        await update.message.reply_text("لطفا فقط عدد وارد کنید (مثال: 100000).")
        return ASK_COURSE_PRICE_NON_MEMBER
    context.user_data['course_price_non_member'] = int(text)
    await update.message.reply_text(
        f"آیا قیمت برای غیراعضای انجمن {text} تومان تأیید می‌شود؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_PRICE_NON_MEMBER


async def confirm_course_price_non_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "✅ تأیید":
        conn = sqlite3.connect('mabsa.db')
        cursor = conn.cursor()
        cursor.execute('SELECT MAX(id) FROM courses')
        last_id = cursor.fetchone()[0] or 0
        course_code = generate_course_code(last_id + 1)
        data = {
            'name': context.user_data['course_name'],
            'capacity': context.user_data['course_capacity'],
            'photo_url': context.user_data.get('course_photo_url'),
            'caption': context.user_data['course_caption'],
            'card_number': context.user_data['course_card_number'],
            'course_code': course_code,
           'price_member': context.user_data['course_price_member'],
           'price_non_member': context.user_data['course_price_non_member']
        }
        saved = save_course_to_db(data)
        if not saved:
            await update.message.reply_text(
                "خطا: دوره با این نام قبلاً وجود دارد.",
                reply_markup=get_courses_keyboard()
            )
            conn.close()
            return ADMIN_COURSE_MENU
        conn.close()
        await update.message.reply_text(
            f"✅ دوره '{data['name']}' با کد {course_code} با موفقیت اضافه شد.",
            reply_markup=get_courses_keyboard()
        )
        return ADMIN_COURSE_MENU
    elif text == "رد ❌":
        await update.message.reply_text("لطفا قیمت برای غیراعضای انجمن را دوباره وارد کنید.")
        return ASK_COURSE_PRICE_NON_MEMBER
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_PRICE_NON_MEMBER


async def admin_delete_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ شما دسترسی ادمین ندارید.")
        return
    try:
        course_id = int(query.data.split("_")[2])
    except Exception:
        await query.edit_message_text("داده نامعتبر است.")
        return
    delete_course_by_id(course_id)
    await query.edit_message_text("✅ دوره با موفقیت حذف شد.")


async def show_course_registrations(update, context):
    # نمایش منوی "📤 صدور / 📖 مشاهده" برای ثبت‌نام‌های یک دوره
    query = update.callback_query
    await query.answer()
    try:
        admin_id = ADMIN_ID  # موجود در فایل
    except NameError:
        admin_id = None
    if admin_id and query.from_user.id != admin_id:
        await query.edit_message_text("⛔ شما دسترسی ادمین ندارید.")
        return

    try:
        # الگوی data: list_registrations_<course_id>
        course_id = int(query.data.split("_")[2])
    except Exception:
        await query.edit_message_text("داده نامعتبر است.")
        return

    # نگه‌داری آیدی دوره برای مراحل «صدور»/«مشاهده»
    context.user_data['list_course_id'] = course_id

    regs = get_course_registrations_full(course_id)
    if not regs:
        await query.edit_message_text("📭 هیچ ثبت‌نامی برای این دوره وجود ندارد.")
        return

    # نام دوره (تابع باید موجود باشد)
    course = None
    try:
        course = get_course_by_id(course_id)
    except Exception:
        course = None
    course_name = course[1] if (course and len(course) > 1) else "نامشخص"

    # کیبورد مشترک «📤 صدور / 📖 مشاهده / بازگشت» (مثل لیست اعضا)
    kb = None
    try:
        kb = get_members_list_keyboard()
    except Exception:
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 صدور", callback_data="noop_issue"),
             InlineKeyboardButton("📖 مشاهده", callback_data="noop_view")],
        ])

    await query.message.reply_text(
        f"📋 لیست ثبت‌نام‌کنندگان «{course_name}»\nیکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=kb
    )

async def course_menu_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "🔙 بازگشت به منوی اصلی":
        await update.message.reply_text("بازگشت به منوی اصلی.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    course = get_course_by_name(text)
    if not course:
        await update.message.reply_text(
            "دوره انتخاب‌شده یافت نشد.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    course_id, name, capacity, registered_count, photo_url, caption, card_number, course_code, price_member, price_non_member = course
    if check_course_registration(user_id, course_id):
        reg_code = get_registration_code_for_user(user_id, course_id) or "نامشخص"
        await update.message.reply_text(
            f"⚠️ شما قبلاً در این دوره ثبت‌نام کرده‌اید.\nکد ثبت‌نام شما: {reg_code}",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    is_member = get_member_by_telegram_id(user_id) is not None
    price = price_member if is_member else price_non_member
    context.user_data['selected_course'] = course
    context.user_data['is_member'] = is_member
    message = f"دوره: {name}\nکپشن: {caption}\nظرفیت باقی‌مانده: {capacity - registered_count}/{capacity}\nقیمت: {price} تومان"
    if photo_url:
        await update.message.reply_photo(
            photo=photo_url,
            caption=message,
            reply_markup=ReplyKeyboardMarkup(
                [["✅ مطمئنم", "لغو"]], resize_keyboard=True)
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=ReplyKeyboardMarkup(
                [["✅ مطمئنم", "لغو"]], resize_keyboard=True)
        )
    return CONFIRM_COURSE_SELECTION


async def confirm_course_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "لغو":
        await update.message.reply_text(
            "ثبت‌نام دوره لغو شد.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    elif text == "✅ مطمئنم":
        course = context.user_data['selected_course']
        if course[3] >= course[2]:
            await update.message.reply_text(
                "⚠️ ظرفیت این دوره تکمیل شده است.",
                reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
            )
            return USER_COURSE_MENU
        if check_course_registration(user_id, course[0]):
            await update.message.reply_text(
                "⚠️ شما قبلاً برای این دوره ثبت‌نام کرده‌اید.",
                reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
            )
            return USER_COURSE_MENU
        is_member = context.user_data['is_member']
        price = course[8] if is_member else course[9]
        member = get_member_by_telegram_id(user_id)
        if is_member:
            await update.message.reply_text(
                f"لطفا مبلغ {price} تومان به شماره کارت {course[6]} واریز کنید و دکمه 'واریز کردم' را بزنید.",
                reply_markup=get_payment_confirmation_keyboard()
            )
            return PAYMENT_CONFIRMATION
        else:
            await update.message.reply_text(
                "شما عضو انجمن نیستید. لطفا اطلاعات زیر را برای ثبت‌نام وارد کنید.\nنام و نام خانوادگی فارسی:",
                reply_markup=ReplyKeyboardMarkup(
                    [["❌ ابطال ثبت‌نام"]], resize_keyboard=True)
            )
            return ASK_COURSE_FULLNAME_FA
    else:
        await update.message.reply_text("لطفا یکی از گزینه‌های 'مطمئنم' یا 'لغو' را انتخاب کنید.")
        return CONFIRM_COURSE_SELECTION


async def ask_course_fullname_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال ثبت‌نام":
        await update.message.reply_text(
            "ثبت‌نام دوره لغو شد.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    if not re.fullmatch(r"[آ-ی ]+", text):
        await update.message.reply_text("لطفا فقط از حروف فارسی استفاده کنید و دوباره تلاش کنید.")
        return ASK_COURSE_FULLNAME_FA
    formatted = " ".join(word.capitalize() for word in text.split())
    context.user_data['course_fullname_fa'] = formatted
    await update.message.reply_text(
        f"آیا نام شما {formatted} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_FULLNAME_FA


async def confirm_course_fullname_fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
    "لطفاً شماره دانشجویی ۹ رقمی خود را وارد کنید.\n\n"
    "اگر دانشجوی دانشگاه علم و فناوری مازندران نیستید، عدد 123456789 را وارد کنید.\n\n"
    "اعداد حتماً به انگلیسی وارد شوند.",
    reply_markup=ReplyKeyboardMarkup(
        [["❌ ابطال ثبت‌نام"]], resize_keyboard=True)
    )

        return ASK_COURSE_STUDENT_ID
    elif text == "رد ❌":
        await update.message.reply_text("لطفا نام و نام خانوادگی فارسی خود را دوباره وارد کنید.")
        return ASK_COURSE_FULLNAME_FA
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_FULLNAME_FA


async def ask_course_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال ثبت‌نام":
        await update.message.reply_text(
            "ثبت‌نام دوره لغو شد.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    if not re.fullmatch(r"\d{9}", text):
        await update.message.reply_text("لطفا شماره دانشجویی ۹ رقمی را فقط با اعداد انگلیسی وارد کنید.")
        return ASK_COURSE_STUDENT_ID
    context.user_data['course_student_id'] = text
    await update.message.reply_text(
        f"آیا شماره دانشجویی شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_STUDENT_ID


async def confirm_course_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا کد ملی ۱۰ رقمی خود را وارد کنید.\n\nمثال: 1234567890",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ ابطال ثبت‌نام"]], resize_keyboard=True)
        )
        return ASK_COURSE_NATIONAL_ID
    elif text == "رد ❌":
        await update.message.reply_text("لطفا شماره دانشجویی خود را دوباره وارد کنید.")
        return ASK_COURSE_STUDENT_ID
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_STUDENT_ID


async def ask_course_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال ثبت‌نام":
        await update.message.reply_text(
            "ثبت‌نام دوره لغو شد.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    if not re.fullmatch(r"\d{10}", text):
        await update.message.reply_text("لطفا کد ملی ۱۰ رقمی را فقط با اعداد انگلیسی وارد کنید.")
        return ASK_COURSE_NATIONAL_ID
    context.user_data['course_national_id'] = text
    await update.message.reply_text(
        f"آیا کد ملی شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_NATIONAL_ID


async def confirm_course_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا شماره تماس ۱۱ رقمی خود را وارد کنید.\n\nمثال: 09123456789",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ ابطال ثبت‌نام"]], resize_keyboard=True)
        )
        return ASK_COURSE_PHONE
    elif text == "رد ❌":
        await update.message.reply_text("لطفا کد ملی خود را دوباره وارد کنید.")
        return ASK_COURSE_NATIONAL_ID
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_NATIONAL_ID


async def ask_course_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "❌ ابطال ثبت‌نام":
        await update.message.reply_text(
            "ثبت‌نام دوره لغو شد.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    if not re.fullmatch(r"09\d{9}", text):
        await update.message.reply_text("لطفا شماره تماس ۱۱ رقمی را با شروع 09 و فقط با اعداد انگلیسی وارد کنید.")
        return ASK_COURSE_PHONE
    context.user_data['course_phone'] = text
    await update.message.reply_text(
        f"آیا شماره تماس شما {text} است؟",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COURSE_PHONE


async def confirm_course_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    course = context.user_data['selected_course']
    is_member = context.user_data['is_member']
    price = course[8] if is_member else course[9]
    if text == "✅ تأیید":
        await update.message.reply_text(
            f"لطفا مبلغ {price} تومان به شماره کارت {course[6]} واریز کنید و دکمه 'واریز کردم' را بزنید.",
            reply_markup=get_payment_confirmation_keyboard()
        )
        return PAYMENT_CONFIRMATION
    elif text == "رد ❌":
        await update.message.reply_text("لطفا شماره تماس خود را دوباره وارد کنید.")
        return ASK_COURSE_PHONE
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COURSE_PHONE


async def payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "واریز کردم":
        await update.message.reply_text(
            "لطفا تصویر فیش واریزی را آپلود کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return UPLOAD_PAYMENT_PROOF
    else:
        await update.message.reply_text(
            "لطفا دکمه 'واریز کردم' را انتخاب کنید.",
            reply_markup=get_payment_confirmation_keyboard()
        )
        return PAYMENT_CONFIRMATION


async def upload_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    course = context.user_data['selected_course']
    is_member = context.user_data['is_member']
    if update.message.text == "لغو":
        await update.message.reply_text(
            "ثبت‌نام دوره لغو شد.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    if not update.message.photo:
        await update.message.reply_text("لطفا تصویر فیش واریزی را آپلود کنید یا 'لغو' را انتخاب کنید.")
        return UPLOAD_PAYMENT_PROOF
    payment_proof = update.message.photo[-1].file_id
    registration_code = generate_registration_code()
    data = {
        'course_id': course[0],
        'telegram_id': user_id,
        'fullname_fa': context.user_data.get('course_fullname_fa', get_member_by_telegram_id(user_id)[1] if is_member else None),
        'student_id': context.user_data.get('course_student_id', get_member_by_telegram_id(user_id)[2] if is_member else None),
        'national_id': context.user_data.get('course_national_id', get_member_by_telegram_id(user_id)[3] if is_member else None),
        'phone': context.user_data.get('course_phone', get_member_by_telegram_id(user_id)[4] if is_member else None),
        'payment_proof': payment_proof,
        'registration_code': registration_code,
        'is_member': is_member
    }
    saved = save_course_registration(data)
    if not saved:
        await update.message.reply_text(
            "خطا: ثبت‌نام ناموفق بود. لطفا دوباره تلاش کنید.",
            reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
        )
        return USER_COURSE_MENU
    await update.message.reply_text(
        f"✅ ثبت‌نام شما برای دوره '{course[1]}' با موفقیت انجام شد.\nکد ثبت‌نام: {registration_code}",
        reply_markup=get_user_courses_keyboard() or get_main_keyboard(user_id)
    )
    # ارسال اطلاعات به گروه دوره‌ها
    info_msg = (
        f"ثبت‌نام جدید برای دوره {course[1]}:\n"
        f"نام: {data['fullname_fa']}\n"
        f"شماره دانشجویی: {data['student_id']}\n"
        f"کد ملی: {data['national_id']}\n"
        f"شماره تماس: {data['phone']}\n"
        f"کد ثبت‌نام: {registration_code}\n"
        f"وضعیت عضویت: {'عضو' if is_member else 'غیرعضو'}\n"
        f"آیدی عددی: https://t.me/@id{update.effective_user.id}"

    )
    await context.bot.send_photo(
        chat_id=COURSE_GROUP_ID,
        photo=payment_proof,
        caption=info_msg
    )
    return USER_COURSE_MENU

# --- هندلرهای بخش درباره انجمن ---


async def about_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    if text == "📝 معرفی انجمن":
        await update.message.reply_text(get_about_message(), reply_markup=about_keyboard())
        return ABOUT_MENU

    elif text == "👥 شورای مرکزی":
        items = get_all_council_items()
        if not items:
            await update.message.reply_text("⚠️ هیچ موردی برای شورای مرکزی تنظیم نشده است.", reply_markup=about_keyboard())
            return ABOUT_MENU
        # برای هر اسلات، اگر عکس دارد با عکس، وگرنه متن
        for slot, msg, photo in items:
            caption = f"شورا {slot}\n\n{msg or ''}".strip()
            if photo:
                await update.message.reply_photo(photo=photo, caption=caption)
            else:
                await update.message.reply_text(caption)
        # بازگشت به منوی درباره
        return ABOUT_MENU

    elif text == "🔙 بازگشت به منوی اصلی":
        await update.message.reply_text("بازگشت به منوی اصلی.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU

    else:
        await update.message.reply_text("لطفاً یکی از گزینه‌ها را انتخاب کنید.", reply_markup=about_keyboard())
        return ABOUT_MENU


# --- هندلرهای پیام‌های ادمین ---


async def ask_secretary_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if text == "لغو":
        await update.message.reply_text("تغییر پیام لغو شد.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL
    context.user_data['secretary_message'] = text
    await update.message.reply_text(
        f"آیا پیام زیر تأیید می‌شود؟\n\n{text}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_SECRETARY_MESSAGE


async def confirm_secretary_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if text == "✅ تأیید":
        update_secretary_message(context.user_data['secretary_message'])
        await update.message.reply_text(
            "✅ پیام ارتباط با دبیر به‌روزرسانی شد.",
            reply_markup=get_admin_keyboard()
        )
        return ADMIN_PANEL
    elif text == "رد ❌":
        await update.message.reply_text(
            "لطفا متن جدید برای ارتباط با دبیر را وارد کنید یا 'لغو' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_SECRETARY_MESSAGE
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_SECRETARY_MESSAGE


async def ask_about_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if text == "لغو":
        await update.message.reply_text("تغییر پیام لغو شد.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL
    context.user_data['about_message'] = text
    await update.message.reply_text(
        f"آیا پیام زیر تأیید می‌شود؟\n\n{text}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_ABOUT_MESSAGE


async def confirm_about_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if text == "✅ تأیید":
        update_about_message(context.user_data['about_message'])
        await update.message.reply_text(
            "✅ پیام اهداف انجمن به‌روزرسانی شد.",
            reply_markup=get_admin_keyboard()
        )
        return ADMIN_PANEL
    elif text == "رد ❌":
        await update.message.reply_text(
            "لطفا متن جدید برای اهداف انجمن را وارد کنید یا 'لغو' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_ABOUT_MESSAGE
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_ABOUT_MESSAGE


async def ask_council_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if text == "لغو":
        await update.message.reply_text("تغییر پیام لغو شد.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL
    context.user_data['council_message'] = text
    await update.message.reply_text(
        f"آیا پیام زیر تأیید می‌شود؟\n\n{text}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ تأیید", "رد ❌"]], resize_keyboard=True)
    )
    return CONFIRM_COUNCIL_MESSAGE


async def confirm_council_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    if text == "✅ تأیید":
        await update.message.reply_text(
            "لطفا تصویر شورای مرکزی را آپلود کنید یا 'بدون تصویر' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup(
                [["بدون تصویر"], ["لغو"]], resize_keyboard=True)
        )
        return ASK_COUNCIL_PHOTO
    elif text == "رد ❌":
        await update.message.reply_text(
            "لطفا متن جدید برای شورای مرکزی را وارد کنید یا 'لغو' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True)
        )
        return ASK_COUNCIL_MESSAGE
    else:
        await update.message.reply_text("لطفا فقط از دکمه‌های ✅ تأیید یا رد ❌ استفاده کنید.")
        return CONFIRM_COUNCIL_MESSAGE


async def ask_council_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    text = update.message.text if update.message.text else None
    if text == "لغو":
        await update.message.reply_text("تغییر پیام لغو شد.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL
    elif text == "بدون تصویر":
        photo = None
    elif update.message.photo:
        photo = update.message.photo[-1].file_id
    else:
        await update.message.reply_text(
            "لطفا یک تصویر آپلود کنید یا 'بدون تصویر' را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup(
                [["بدون تصویر"], ["لغو"]], resize_keyboard=True)
        )
        return ASK_COUNCIL_PHOTO
    set_council_item(context.user_data['council_message'], photo)
    await update.message.reply_text(
        "✅ پیام و تصویر شورای مرکزی به‌روزرسانی شد.",
        reply_markup=get_admin_keyboard()
    )
    return ADMIN_PANEL

# --- هندلر نمایش لیست اعضا ---


async def admin_delete_member_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        try:
            await query.edit_message_text("⛔ شما دسترسی ادمین ندارید.")
        except Exception:
            await query.message.reply_text("⛔ شما دسترسی ادمین ندارید.")
        return
    data = (query.data or "")
    try:
        member_id = int(data.split("_")[2])
    except Exception:
        try:
            await query.edit_message_text("داده نامعتبر است.")
        except Exception:
            await query.message.reply_text("داده نامعتبر است.")
        return
    delete_member_by_id(member_id)
    try:
        await query.edit_message_text("✅ کاربر حذف شد.")
    except Exception:
        await query.message.reply_text("✅ کاربر حذف شد.")

async def show_members_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.", reply_markup=get_main_keyboard(user_id))
        return MAIN_MENU
    members = get_all_members()
    if not members:
        await update.message.reply_text("📭 هیچ عضوی ثبت نشده است.", reply_markup=get_admin_keyboard())
        return ADMIN_PANEL
    message = "📋 لیست اعضا:\n\n"
    for member in members:
        member_id, fullname_fa, fullname_e, student_id, phone, membership_code = member
        message += (
            f"🆔 {member_id}\n"
            f"👤 {fullname_fa} ({fullname_e})\n"
            f"🎓 شماره دانشجویی: {student_id}\n"
            f"📞 {phone}\n"
            f"💳 کد عضویت: {membership_code}\n"
            f"------------------------\n"
        )
    await update.message.reply_text(message, reply_markup=get_admin_keyboard())
    return ADMIN_PANEL

# --- هندلر دستور شروع ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        "👋 به ربات انجمن علمی مبسا خوش آمدید!\nلطفا یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=get_main_keyboard(user_id)
    )
    return MAIN_MENU

# --- هندلر لغو ---


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        "عملیات لغو شد. بازگشت به منوی اصلی.",
        reply_markup=get_main_keyboard(user_id)
    )
    context.user_data.clear()
    return MAIN_MENU

# --- هندلر خطا ---


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")
    user_id = update.message.from_user.id if update.message else update.callback_query.from_user.id
    await context.bot.send_message(
        chat_id=user_id,
        text="⚠️ خطایی رخ داد. لطفا دوباره تلاش کنید یا با ادمین تماس بگیرید.",
        reply_markup=get_main_keyboard(user_id)
    )
    return MAIN_MENU

# --- تابع اصلی ---


def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    # === Auto-merged handler registrations (moved into main) ===
    app.add_handler(CallbackQueryHandler(show_course_registrations, pattern=r"^list_registrations_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_registration, pattern=r"^del_reg_\d+$"))
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            ABOUT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, about_menu_handler)],
            ADMIN_PANEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu_handler)],
            ADMIN_COURSE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_menu_handler)],
            USER_COURSE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_menu_user)],
            ASK_FULLNAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_fullname_fa)],
            CONFIRM_FULLNAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_fullname_fa)],
            ASK_FULLNAME_EN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_fullname_e)],
            CONFIRM_FULLNAME_EN: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_fullname_e)],
            ASK_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_student_id)],
            CONFIRM_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_student_id)],
            ASK_NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_national_id)],
            CONFIRM_NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_national_id)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            CONFIRM_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_phone)],
            ASK_MAJOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_major)],
            CONFIRM_MAJOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_major)],
            ASK_SECRETARY_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_secretary_message)],
            CONFIRM_SECRETARY_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_secretary_message)],
            ASK_ABOUT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_about_message)],
            CONFIRM_ABOUT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_about_message)],
            ASK_COUNCIL_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_council_message)],
            CONFIRM_COUNCIL_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_council_message)],
            ASK_COUNCIL_PHOTO: [MessageHandler(filters.TEXT | filters.PHOTO, ask_council_photo)],
            ASK_COURSE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_name)],
            CONFIRM_COURSE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_name)],
            ASK_COURSE_CAPACITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_capacity)],
            CONFIRM_COURSE_CAPACITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_capacity)],
            ASK_COURSE_PHOTO: [MessageHandler(filters.TEXT | filters.PHOTO, ask_course_photo)],
            ASK_COURSE_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_caption)],
            CONFIRM_COURSE_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_caption)],
            ASK_COURSE_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_card)],
            CONFIRM_COURSE_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_card)],
            ASK_COURSE_PRICE_MEMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_price_member)],
            CONFIRM_COURSE_PRICE_MEMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_price_member)],
            ASK_COURSE_PRICE_NON_MEMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_price_non_member)],
            CONFIRM_COURSE_PRICE_NON_MEMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_price_non_member)],
            CONFIRM_COURSE_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_selection)],
            ASK_COURSE_FULLNAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_fullname_fa)],
            CONFIRM_COURSE_FULLNAME_FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_fullname_fa)],
            ASK_COURSE_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_student_id)],
            CONFIRM_COURSE_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_student_id)],
            ASK_COURSE_NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_national_id)],
            CONFIRM_COURSE_NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_national_id)],
            ASK_COURSE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_course_phone)],
            CONFIRM_COURSE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_course_phone)],
            PAYMENT_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_confirmation)],
            UPLOAD_PAYMENT_PROOF: [MessageHandler(filters.TEXT | filters.PHOTO, upload_payment_proof)],
            ADMIN_ELECTION_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_election_menu_handler)],
            ASK_CANDIDATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_candidate_name)],
            CONFIRM_CANDIDATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_candidate_name)],
            ASK_CANDIDATE_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_candidate_field)],
            CONFIRM_CANDIDATE_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_candidate_field)],
            ASK_CANDIDATE_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_candidate_desc)],
            CONFIRM_CANDIDATE_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_candidate_desc)],
            ASK_CANDIDATE_PHOTO: [MessageHandler(filters.TEXT | filters.PHOTO, ask_candidate_photo)],
            USER_ELECTION_MENU: [CallbackQueryHandler(process_user_vote)],
            ASK_COUNCIL_SLOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_council_pick_slot)],
            ASK_COUNCIL_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_council_text)],
            CONFIRM_COUNCIL_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_council_text_confirm)],
            ASK_COUNCIL_PHOTO2: [
            MessageHandler(filters.Regex("^بدون عکس$"), admin_council_photo),
            MessageHandler(filters.PHOTO, admin_council_photo),
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_council_photo),
        ],
        CONFIRM_COUNCIL_SAVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_council_save)],

        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(
        admin_delete_course, pattern=r'^delete_course_\d+$'))
    app.add_handler(CallbackQueryHandler(
        show_course_registrations, pattern=r'^list_registrations_\d+$'))
    app.add_handler(CallbackQueryHandler(
        admin_delete_candidate, pattern=r'^delete_cand_\d+$'))
    app.add_error_handler(error_handler)
    app.add_handler(CallbackQueryHandler(admin_delete_member_callback, pattern=r"^del_member_\d+$"))


    app.add_handler(CallbackQueryHandler(admin_open_course_regs, pattern=r"^list_registrations_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_registration, pattern=r"^del_reg_\d+$"))
    app.run_polling()


# === DB helpers for course registrations (auto-merged) ===

def get_course_registrations_full(course_id: int):
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, telegram_id, fullname_fa, student_id, national_id, phone, registration_code, is_member
        FROM course_registrations
        WHERE course_id=?
        ORDER BY id DESC
    """, (course_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_member_profile_by_telegram(telegram_id: int):
    """Return (fullname_e, major, membership_code) from members by telegram_id, or (None, None, None)."""
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT fullname_e, major, membership_code
            FROM members
            WHERE telegram_id=?
        """, (telegram_id,))
        row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        return None, None, None
    return row[0], row[1], row[2]
def delete_registration_by_id(reg_id: int):
    """حذف یک ثبت‌نام و به‌روزرسانی شمارنده ظرفیت دوره."""
    conn = sqlite3.connect('mabsa.db')
    cursor = conn.cursor()
    cursor.execute('SELECT course_id FROM course_registrations WHERE id=?', (reg_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    course_id = row[0]
    cursor.execute('DELETE FROM course_registrations WHERE id=?', (reg_id,))
    cursor.execute('UPDATE courses SET registered_count = MAX(registered_count - 1, 0) WHERE id=?', (course_id,))
    conn.commit()
    conn.close()
    return True


# === admin_delete_registration (auto-merged) ===

async def admin_delete_registration(update, context):
    query = update.callback_query
    await query.answer()
    try:
        admin_id = ADMIN_ID
    except NameError:
        admin_id = None
    if admin_id and query.from_user.id != admin_id:
        await query.edit_message_text("⛔ شما دسترسی ادمین ندارید.")
        return
    try:
        reg_id = int(query.data.split("_")[2])
    except Exception:
        await query.edit_message_text("داده نامعتبر است.")
        return
    ok = delete_registration_by_id(reg_id)
    if ok:
        await query.edit_message_text("✅ ثبت‌نام حذف شد.")
    else:
        await query.edit_message_text("⚠️ موردی برای حذف یافت نشد.")


# === Safe helpers (auto-added) ===

def _safe_get(seq, idx, default=None):
    try:
        return seq[idx]
    except Exception:
        return default

def _format_course_admin_safe(course):
    """Build a safe admin message for a course tuple with variable schema."""
    # Expected order (best guess): id, name, capacity, registered_count, photo_url, caption, description,
    # start_date, end_date, instructor, bank_card_number, course_code, price_member, price_non_member
    name = _safe_get(course, 1, "نامشخص")
    capacity = _safe_get(course, 2, None)
    registered = _safe_get(course, 3, None)
    price_member = _safe_get(course, 12, None)
    price_non_member = _safe_get(course, 13, None)
    lines = [f"دوره: {name}"]
    if registered is not None or capacity is not None:
        lines.append(f"ظرفیت: {registered if registered is not None else '?'} / {capacity if capacity is not None else '?'}")
    if price_member is not None:
        lines.append(f"قیمت اعضا: {price_member} تومان")
    if price_non_member is not None:
        lines.append(f"قیمت غیراعضا: {price_non_member} تومان")
    return "\n".join(lines)

def _extract_course_media(course):
    """Return (photo_url, caption_or_none)."""
    photo_url = _safe_get(course, 4, None)
    caption = _safe_get(course, 5, None)
    return photo_url, caption


if __name__ == '__main__':
    main()
