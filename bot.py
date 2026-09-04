import os
import sys
import asyncio
import logging
from datetime import datetime, timezone
from aiohttp import web

# Aiogram 3.x imports
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, KICKED, MEMBER
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    BotCommand,
    BotCommandScopeChat
)
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

# Database Drivers
try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

# ---------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Configuration & Environment Variables
# ---------------------------------------------------------
BOT_TOKEN = os.environ.get("8974109640:AAHNuuHALqJQFteuwMlaXiPjzYEjzzUDO8Q", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8925689319"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
PORT = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable is not set!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

db_pool = None
sqlite_db_path = "dating_bot.db"
is_postgres = False

# ---------------------------------------------------------
# Database Layer (Unified for PostgreSQL & SQLite)
# ---------------------------------------------------------
async def init_db():
    global db_pool, is_postgres

    pg_url = DATABASE_URL
    if pg_url.startswith("postgres://"):
        pg_url = pg_url.replace("postgres://", "postgresql://", 1)

    if pg_url and asyncpg:
        logger.info("Connecting to Neon PostgreSQL...")
        try:
            db_pool = await asyncpg.create_pool(
                dsn=pg_url,
                min_size=1,
                max_size=10,
                ssl="require" if "neon.tech" in pg_url else None
            )
            is_postgres = True
            logger.info("✅ SUCCESS: Connected to Neon PostgreSQL and initialized schema!")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neon PostgreSQL: {e}")
            logger.warning("Falling back to local SQLite storage...")
            is_postgres = False
    else:
        if not asyncpg:
            logger.warning("⚠️ asyncpg library is not installed! Falling back to SQLite.")
        logger.info(f"Using local SQLite storage ({sqlite_db_path})...")
        is_postgres = False

    # Create Tables
    if is_postgres:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    age INT,
                    gender TEXT,
                    target_gender TEXT,
                    city TEXT,
                    bio TEXT,
                    photo_id TEXT,
                    gesture_photo_id TEXT,
                    is_verified INT DEFAULT 0,
                    is_approved INT DEFAULT 0,
                    is_banned INT DEFAULT 0,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pending_registrations (
                    telegram_id BIGINT PRIMARY KEY,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS swipes (
                    id SERIAL PRIMARY KEY,
                    swiper_id BIGINT,
                    swiped_id BIGINT,
                    action TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(swiper_id, swiped_id)
                );
                CREATE TABLE IF NOT EXISTS matches (
                    id SERIAL PRIMARY KEY,
                    user1_id BIGINT,
                    user2_id BIGINT,
                    matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user1_id, user2_id)
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    feedback_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    reporter_id BIGINT,
                    reported_id BIGINT,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
    else:
        async with aiosqlite.connect(sqlite_db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    age INTEGER,
                    gender TEXT,
                    target_gender TEXT,
                    city TEXT,
                    bio TEXT,
                    photo_id TEXT,
                    gesture_photo_id TEXT,
                    is_verified INTEGER DEFAULT 0,
                    is_approved INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_registrations (
                    telegram_id INTEGER PRIMARY KEY,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS swipes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    swiper_id INTEGER,
                    swiped_id INTEGER,
                    action TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(swiper_id, swiped_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user1_id INTEGER,
                    user2_id INTEGER,
                    matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user1_id, user2_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    feedback_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_id INTEGER,
                    reported_id INTEGER,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.commit()

async def db_execute(query: str, *args):
    """Executes query using '?' parameter placeholders."""
    if is_postgres:
        parts = query.split("?")
        pg_query = parts[0]
        for i, part in enumerate(parts[1:], 1):
            pg_query += f"${i}{part}"
        async with db_pool.acquire() as conn:
            return await conn.execute(pg_query, *args)
    else:
        async with aiosqlite.connect(sqlite_db_path) as db:
            await db.execute(query, args)
            await db.commit()

async def db_query(query: str, *args):
    """Executes SELECT query and returns rows as dictionaries."""
    if is_postgres:
        parts = query.split("?")
        pg_query = parts[0]
        for i, part in enumerate(parts[1:], 1):
            pg_query += f"${i}{part}"
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(pg_query, *args)
            return [dict(r) for r in rows]
    else:
        async with aiosqlite.connect(sqlite_db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, args)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

# ---------------------------------------------------------
# FSM States
# ---------------------------------------------------------
class Registration(StatesGroup):
    name = State()
    age = State()
    gender = State()
    target_gender = State()
    city = State()
    bio = State()
    photo = State()
    gesture_selfie = State()

class RetakeSelfie(StatesGroup):
    waiting_for_photo = State()

class FeedbackStates(StatesGroup):
    waiting_for_feedback = State()

class AdminReplyState(StatesGroup):
    waiting_for_reply = State()

# ---------------------------------------------------------
# Keyboards & Helpers
# ---------------------------------------------------------
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Discover Matches")],
            [KeyboardButton(text="👤 My Profile"), KeyboardButton(text="💌 Matches")],
            [KeyboardButton(text="💬 Feedback")]
        ],
        resize_keyboard=True
    )

def safe_user_mention(user_id: int, full_name: str, username: str = None) -> str:
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={user_id}">{full_name}</a>'

# ---------------------------------------------------------
# Lifecycle Handlers (Soft Hide On Block / Restore On Return)
# ---------------------------------------------------------
@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=KICKED))
async def handle_user_blocked(event: types.ChatMemberUpdated):
    user_id = event.from_user.id
    logger.info(f"🚫 User {user_id} blocked bot. Soft-hiding profile.")
    await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", user_id)

@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=MEMBER))
async def handle_user_unblocked(event: types.ChatMemberUpdated):
    user_id = event.from_user.id
    logger.info(f"✨ User {user_id} unblocked bot.")
    await db_execute("UPDATE users SET is_approved = 1 WHERE telegram_id = ? AND is_verified = 1 AND is_banned = 0", user_id)

# ---------------------------------------------------------
# User Registration Flow
# ---------------------------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    users = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)

    if users:
        user = users[0]
        if user["is_banned"]:
            await message.answer("🚫 Your account has been suspended by administration.")
            return
        
        if not user["is_approved"] and user["is_verified"]:
            await db_execute("UPDATE users SET is_approved = 1 WHERE telegram_id = ?", user_id)

        await message.answer(
            f"👋 Welcome back, {user['full_name']}!\nReady to meet matches in {user['city']}?",
            reply_markup=main_menu_keyboard()
        )
        return

    await db_execute(
        "INSERT INTO pending_registrations (telegram_id) VALUES (?) ON CONFLICT DO NOTHING",
        user_id
    )

    await state.set_state(Registration.name)
    await message.answer(
        "✨ <b>Welcome to Soulmate India 💌</b>\n\n"
        "Let's create your dating profile in a few simple steps.\n"
        "What is your full name?",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Registration.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await state.set_state(Registration.age)
    await message.answer("Great! How old are you? (Enter a number between 18 and 99)")

@dp.message(Registration.age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (18 <= int(message.text) <= 99):
        await message.answer("⚠️ Please enter a valid age between 18 and 99.")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(Registration.gender)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Male"), KeyboardButton(text="Female")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("What is your gender?", reply_markup=kb)

@dp.message(Registration.gender)
async def process_gender(message: types.Message, state: FSMContext):
    if message.text not in ["Male", "Female"]:
        await message.answer("Please choose an option from the buttons below.")
        return
    await state.update_data(gender=message.text)
    await state.set_state(Registration.target_gender)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Female"), KeyboardButton(text="Male"), KeyboardButton(text="Everyone")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Who are you interested in meeting?", reply_markup=kb)

@dp.message(Registration.target_gender)
async def process_target_gender(message: types.Message, state: FSMContext):
    await state.update_data(target_gender=message.text)
    await state.set_state(Registration.city)
    await message.answer("Which city are you located in?", reply_markup=ReplyKeyboardRemove())

@dp.message(Registration.city)
async def process_city(message: types.Message, state: FSMContext):
    await state.update_data(city=message.text.strip().title())
    await state.set_state(Registration.bio)
    await message.answer("Write a short bio about yourself (interests, hobbies, what you are looking for):")

@dp.message(Registration.bio)
async def process_bio(message: types.Message, state: FSMContext):
    await state.update_data(bio=message.text.strip())
    await state.set_state(Registration.photo)
    await message.answer("📸 Please upload your primary profile picture:")

@dp.message(Registration.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(Registration.gesture_selfie)
    await message.answer(
        "✌️ <b>Anti-Fake Verification Step</b>\n\n"
        "To keep our community safe from catfishes, upload a quick selfie holding up a <b>Peace Sign (✌️)</b>.\n"
        "<i>This photo is reviewed strictly by moderators and will NOT be shown on your profile.</i>",
        parse_mode="HTML"
    )

@dp.message(Registration.gesture_selfie, F.photo)
async def process_gesture_selfie(message: types.Message, state: FSMContext):
    gesture_photo_id = message.photo[-1].file_id
    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username or ""

    await db_execute("""
        INSERT INTO users (
            telegram_id, full_name, username, age, gender, target_gender,
            city, bio, photo_id, gesture_photo_id, is_verified, is_approved, is_banned
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
        ON CONFLICT (telegram_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            username = EXCLUDED.username,
            age = EXCLUDED.age,
            gender = EXCLUDED.gender,
            target_gender = EXCLUDED.target_gender,
            city = EXCLUDED.city,
            bio = EXCLUDED.bio,
            photo_id = EXCLUDED.photo_id,
            gesture_photo_id = EXCLUDED.gesture_photo_id,
            is_verified = 0,
            is_approved = 0
    """, user_id, data['full_name'], username, data['age'], data['gender'],
       data['target_gender'], data['city'], data['bio'], data['photo_id'], gesture_photo_id)

    await db_execute("DELETE FROM pending_registrations WHERE telegram_id = ?", user_id)
    await state.clear()

    await message.answer(
        "🎉 <b>Profile Submitted!</b>\n\n"
        "Our moderators are verifying your gesture selfie. You'll receive a notification here once approved!",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

    # Dispatch to Admin
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"verify_ok_{user_id}"),
            InlineKeyboardButton(text="⚠️ Retake Selfie", callback_data=f"verify_retry_{user_id}")
        ],
        [InlineKeyboardButton(text="🚫 Ban", callback_data=f"admin_ban_{user_id}")]
    ])
    user_link = safe_user_mention(user_id, data['full_name'], username)
    caption = (
        f"🚨 <b>New Verification Request</b>\n\n"
        f"👤 <b>User:</b> {user_link} (<code>{user_id}</code>)\n"
        f"🎂 <b>Age/Gender:</b> {data['age']} | {data['gender']}\n"
        f"📍 <b>City:</b> {data['city']}\n"
        f"📝 <b>Bio:</b> {data['bio']}"
    )

    try:
        await bot.send_photo(ADMIN_ID, data['photo_id'], caption=caption, parse_mode="HTML")
        await bot.send_photo(
            ADMIN_ID, gesture_photo_id,
            caption=f"✌️ <b>Verification Gesture Selfie</b> for <code>{user_id}</code>",
            parse_mode="HTML",
            reply_markup=admin_kb
        )
    except Exception as e:
        logger.error(f"Failed to deliver verification alert to admin: {e}")

# ---------------------------------------------------------
# Verification Callbacks & Selfie Retake Flow
# ---------------------------------------------------------
@dp.callback_query(F.data.startswith("verify_ok_"))
async def callback_verify_ok(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Admin only.", show_alert=True)
        return
    user_id = int(callback.data.split("_")[2])
    await db_execute("UPDATE users SET is_verified = 1, is_approved = 1 WHERE telegram_id = ?", user_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(f"✅ Approved & Verified user <code>{user_id}</code>", parse_mode="HTML")
    try:
        await bot.send_message(
            user_id,
            "🎉 <b>Congratulations! Your profile is verified!</b>\n\n"
            "You've been granted the Blue Verified Badge 🛡️. Tap <b>🔍 Discover Matches</b> to begin!",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("verify_retry_"))
async def callback_verify_retry(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Admin only.", show_alert=True)
        return
    user_id = int(callback.data.split("_")[2])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(f"⚠️ Requested selfie retake for <code>{user_id}</code>", parse_mode="HTML")
    
    retry_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Retake Verification Selfie", callback_data="start_retake_selfie")]
    ])
    try:
        await bot.send_message(
            user_id,
            "⚠️ <b>Verification Gesture Incomplete</b>\n\n"
            "Our moderators were unable to verify your selfie gesture. "
            "Please upload a clear, front-facing photo showing the <b>Peace Sign (✌️)</b>.",
            parse_mode="HTML",
            reply_markup=retry_kb
        )
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "start_retake_selfie")
async def callback_start_retake(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(RetakeSelfie.waiting_for_photo)
    await callback.message.answer("📸 Upload your new verification selfie holding up a <b>Peace Sign (✌️)</b>:", parse_mode="HTML")
    await callback.answer()

@dp.message(RetakeSelfie.waiting_for_photo, F.photo)
async def process_retake_photo(message: types.Message, state: FSMContext):
    gesture_photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    username = message.from_user.username or ""

    await db_execute("UPDATE users SET gesture_photo_id = ? WHERE telegram_id = ?", gesture_photo_id, user_id)
    await state.clear()
    await message.answer("✅ Your updated verification selfie has been submitted for review.")

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"verify_ok_{user_id}"),
            InlineKeyboardButton(text="⚠️ Reject Again", callback_data=f"verify_retry_{user_id}")
        ]
    ])
    user_link = safe_user_mention(user_id, message.from_user.full_name, username)
    await bot.send_photo(
        ADMIN_ID,
        gesture_photo_id,
        caption=f"🔄 <b>Resubmitted Gesture Selfie</b> from {user_link} (<code>{user_id}</code>)",
        parse_mode="HTML",
        reply_markup=admin_kb
    )

# ---------------------------------------------------------
# User Profile & Soft Account Deactivation
# ---------------------------------------------------------
@dp.message(F.text == "👤 My Profile")
async def cmd_my_profile(message: types.Message):
    user_id = message.from_user.id
    rows = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)
    if not rows:
        await message.answer("Profile not found. Send /start to register!")
        return
    u = rows[0]
    badge = "🛡️ Verified" if u["is_verified"] else "⏳ Under Verification"
    status = "Active" if u["is_approved"] else "Paused / Inactive"
    
    caption = (
        f"👤 <b>{u['full_name']}</b>, {u['age']}\n"
        f"📍 {u['city']}\n"
        f"Badge: {badge}\n"
        f"Visibility: {status}\n\n"
        f"📝 <i>{u['bio']}</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ Deactivate Profile", callback_data="confirm_soft_delete")]
    ])
    await message.answer_photo(u["photo_id"], caption=caption, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "confirm_soft_delete")
async def cb_confirm_soft_delete(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, Deactivate", callback_data="do_soft_delete"),
            InlineKeyboardButton(text="Cancel", callback_data="cancel_delete")
        ]
    ])
    await callback.message.reply("Are you sure you want to pause your profile? It will no longer be visible to others in discovery.", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "cancel_delete")
async def cb_cancel_delete(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Cancelled.")

@dp.callback_query(F.data == "do_soft_delete")
async def cb_do_soft_delete(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await db_execute("UPDATE users SET is_approved = 0, is_verified = 0 WHERE telegram_id = ?", user_id)
    await callback.message.edit_text(
        "🗑️ <b>Your profile has been deactivated.</b>\n\n"
        "Your card is hidden from discovery. You can return anytime by sending /start.",
        parse_mode="HTML"
    )
    await callback.answer()

# ---------------------------------------------------------
# User Feedback Engine + Direct Admin Response
# ---------------------------------------------------------
@dp.message(F.text.in_(["/feedback", "💬 Feedback"]))
async def cmd_feedback(message: types.Message, state: FSMContext):
    await state.set_state(FeedbackStates.waiting_for_feedback)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_feedback")]
    ])
    await message.answer(
        "📝 <b>We value your thoughts!</b>\n\n"
        "Share feedback, suggest a feature, or report an issue below:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )

@dp.callback_query(F.data == "cancel_feedback")
async def cb_cancel_feedback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Feedback cancelled.")
    await callback.answer()

@dp.message(FeedbackStates.waiting_for_feedback)
async def process_feedback(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    feedback_text = message.text or message.caption or "[Media / Attachment]"
    full_name = message.from_user.full_name
    username = message.from_user.username

    await db_execute("INSERT INTO feedback (user_id, feedback_text) VALUES (?, ?)", user_id, feedback_text)
    await state.clear()
    await message.answer("💌 <b>Thank you!</b> Your feedback has been sent directly to our moderators.", parse_mode="HTML")

    user_link = safe_user_mention(user_id, full_name, username)
    admin_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Reply to User", callback_data=f"admin_prep_reply_{user_id}")],
        [InlineKeyboardButton(text="🚫 Ban User", callback_data=f"admin_ban_{user_id}")]
    ])
    admin_alert = (
        f"📬 <b>New Feedback Received!</b>\n\n"
        f"👤 <b>From:</b> {user_link} (<code>{user_id}</code>)\n\n"
        f"💬 <b>Feedback:</b>\n{feedback_text}"
    )
    try:
        await bot.send_message(ADMIN_ID, admin_alert, parse_mode="HTML", reply_markup=admin_markup)
    except Exception as e:
        logger.error(f"Failed to alert admin of feedback: {e}")

# ---------------------------------------------------------
# User Reporting System
# ---------------------------------------------------------
@dp.callback_query(F.data.startswith("report_card_"))
async def cb_report_card(callback: types.CallbackQuery):
    reported_id = int(callback.data.split("_")[2])
    reasons_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Fake Profile / Bot", callback_data=f"do_report_{reported_id}_Fake")],
        [InlineKeyboardButton(text="🔞 Inappropriate Bio/Photo", callback_data=f"do_report_{reported_id}_Inappropriate")],
        [InlineKeyboardButton(text="😡 Harassment / Abuse", callback_data=f"do_report_{reported_id}_Harassment")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_report")]
    ])
    await callback.message.reply("🚨 <b>Select a reason for reporting this profile:</b>", parse_mode="HTML", reply_markup=reasons_kb)
    await callback.answer()

@dp.callback_query(F.data == "cancel_report")
async def cb_cancel_report(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Report cancelled.")

@dp.callback_query(F.data.startswith("do_report_"))
async def cb_do_report(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    reported_id = int(parts[2])
    reason = parts[3]
    reporter_id = callback.from_user.id

    await db_execute("INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, ?)", reporter_id, reported_id, reason)
    await callback.message.edit_text("✅ <b>Report submitted.</b> Our moderation team will investigate.", parse_mode="HTML")
    await callback.answer()

    # Alert Admin
    rep_user = (await db_query("SELECT * FROM users WHERE telegram_id = ?", reported_id))
    rep_name = rep_user[0]['full_name'] if rep_user else f"ID: {reported_id}"
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 View Profile", callback_data=f"inspect_user_{reported_id}")],
        [
            InlineKeyboardButton(text="🚫 Ban Target", callback_data=f"admin_ban_{reported_id}"),
            InlineKeyboardButton(text="Dismiss", callback_data="dismiss_report")
        ]
    ])
    alert_text = (
        f"🚨 <b>Profile Reported!</b>\n\n"
        f"• <b>Reported:</b> {rep_name} (<code>{reported_id}</code>)\n"
        f"• <b>Reporter:</b> <code>{reporter_id}</code>\n"
        f"• <b>Reason:</b> {reason}"
    )
    await bot.send_message(ADMIN_ID, alert_text, parse_mode="HTML", reply_markup=admin_kb)

@dp.callback_query(F.data == "dismiss_report")
async def cb_dismiss_report(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Report dismissed.")

# ---------------------------------------------------------
# Discovery & Matching Engine
# ---------------------------------------------------------
@dp.message(F.text == "🔍 Discover Matches")
async def cmd_discover(message: types.Message):
    user_id = message.from_user.id
    current_users = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)
    if not current_users or not current_users[0]["is_approved"]:
        await message.answer("⚠️ You must have an approved profile to discover matches.")
        return
    
    deck = await db_query("""
        SELECT * FROM users 
        WHERE is_approved = 1 
          AND is_banned = 0 
          AND telegram_id != ?
          AND telegram_id NOT IN (SELECT swiped_id FROM swipes WHERE swiper_id = ?)
        LIMIT 1
    """, user_id, user_id)

    if not deck:
        await message.answer("🎉 You have caught up on all profiles! Check back later for new members.")
        return

    candidate = deck[0]
    candidate_id = candidate["telegram_id"]
    badge = "🛡️" if candidate["is_verified"] else ""
    caption = (
        f"✨ <b>{candidate['full_name']}</b>, {candidate['age']} {badge}\n"
        f"📍 {candidate['city']}\n\n"
        f"📝 <i>{candidate['bio']}</i>"
    )
    swipe_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Pass", callback_data=f"swipe_pass_{candidate_id}"),
            InlineKeyboardButton(text="❤️ Like", callback_data=f"swipe_like_{candidate_id}")
        ],
        [InlineKeyboardButton(text="🚨 Report", callback_data=f"report_card_{candidate_id}")]
    ])
    await message.answer_photo(candidate["photo_id"], caption=caption, parse_mode="HTML", reply_markup=swipe_kb)

@dp.callback_query(F.data.startswith("swipe_"))
async def handle_swipe(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    action = parts[1]
    candidate_id = int(parts[2])
    swiper_id = callback.from_user.id

    await db_execute(
        "INSERT INTO swipes (swiper_id, swiped_id, action) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        swiper_id, candidate_id, action
    )
    await callback.message.delete()

    if action == "like":
        mutual = await db_query(
            "SELECT * FROM swipes WHERE swiper_id = ? AND swiped_id = ? AND action = 'like'",
            candidate_id, swiper_id
        )
        if mutual:
            u1, u2 = min(swiper_id, candidate_id), max(swiper_id, candidate_id)
            await db_execute("INSERT INTO matches (user1_id, user2_id) VALUES (?, ?) ON CONFLICT DO NOTHING", u1, u2)
            
            swiper_info = (await db_query("SELECT * FROM users WHERE telegram_id = ?", swiper_id))[0]
            cand_info = (await db_query("SELECT * FROM users WHERE telegram_id = ?", candidate_id))[0]

            cand_mention = safe_user_mention(cand_info['telegram_id'], cand_info['full_name'], cand_info['username'])
            swiper_mention = safe_user_mention(swiper_info['telegram_id'], swiper_info['full_name'], swiper_info['username'])

            await callback.message.answer(f"🎉 <b>It's a Match!</b>\nYou and {cand_mention} liked each other! Start chatting!", parse_mode="HTML")
            try:
                await bot.send_message(candidate_id, f"🎉 <b>It's a Match!</b>\nYou and {swiper_mention} liked each other! Say hello!", parse_mode="HTML")
            except TelegramForbiddenError:
                await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", candidate_id)
            except Exception:
                pass

    await cmd_discover(callback.message)
    await callback.answer()

# ---------------------------------------------------------
# Admin Help Center & Control Panel
# ---------------------------------------------------------
@dp.message(Command("admin", "admin_help"))
async def cmd_admin_help(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    admin_text = (
        "🛠️ <b>Soulmate India Admin Control Center</b>\n\n"
        "Here is the complete reference of all moderation and operational commands:\n\n"
        "📊 <b>Diagnostics & Monitoring:</b>\n"
        "• <code>/admin_stats</code> — Live DB engine, active users, matches, swipes, reports, drop-offs.\n"
        "• <code>/user &lt;id&gt;</code> — Detailed dossier (photos, swipe counts, matches, ban toggles).\n\n"
        "📢 <b>Targeted & Global Broadcasts:</b>\n"
        "• <code>/broadcast &lt;message&gt;</code> — Global announcement to all active users.\n"
        "• <code>/broadcast_city &lt;City&gt; &lt;msg&gt;</code> — Send notice strictly to users in that city.\n"
        "• <code>/broadcast_gender &lt;Male|Female&gt; &lt;msg&gt;</code> — Send targeted update by gender.\n\n"
        "💬 <b>Direct User Messaging:</b>\n"
        "• <code>/notice &lt;id&gt; &lt;message&gt;</code> — Send an official admin notice banner to one user.\n"
        "• <code>/reply &lt;id&gt; &lt;message&gt;</code> — Send an official support reply through the bot.\n\n"
        "🛡️ <b>Moderation & Access:</b>\n"
        "• <code>/ban &lt;id&gt;</code> — Soft-hide and suspend a user from discovery.\n"
        "• <code>/unban &lt;id&gt;</code> — Restore an account to active discovery.\n\n"
        "⏰ <b>Retention & Re-engagement Nudges:</b>\n"
        "• <code>/remind_unverified</code> — Ping users awaiting selfie verification.\n"
        "• <code>/remind_incomplete</code> — Ping dropped-off registrations to finish signup."
    )

    quick_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 View Stats", callback_data="admin_quick_stats"),
            InlineKeyboardButton(text="⏰ Nudge Incomplete", callback_data="admin_quick_nudge_inc")
        ],
        [
            InlineKeyboardButton(text="⏳ Nudge Unverified", callback_data="admin_quick_nudge_unver")
        ]
    ])

    await message.answer(admin_text, parse_mode="HTML", reply_markup=quick_kb)

@dp.callback_query(F.data == "admin_quick_stats")
async def cb_quick_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await cmd_admin_stats(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "admin_quick_nudge_inc")
async def cb_quick_nudge_inc(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await cmd_remind_incomplete(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "admin_quick_nudge_unver")
async def cb_quick_nudge_unver(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await cmd_remind_unverified(callback.message)
    await callback.answer()

# ---------------------------------------------------------
# Admin Suite: Reply System, User Inspector & Stats
# ---------------------------------------------------------
@dp.callback_query(F.data.startswith("admin_prep_reply_"))
async def cb_admin_prep_reply(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split("_")[3])
    await state.update_data(reply_target_id=user_id)
    await state.set_state(AdminReplyState.waiting_for_reply)
    await callback.message.reply(f"✍️ Type your official reply message for user <code>{user_id}</code>:")
    await callback.answer()

@dp.message(AdminReplyState.waiting_for_reply)
async def process_admin_reply(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target_id = data.get("reply_target_id")
    reply_text = message.text
    
    try:
        await bot.send_message(
            target_id,
            f"💌 <b>Message from Soulmate India Support:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Official reply delivered to <code>{target_id}</code>!", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Failed to deliver: {e}")
    finally:
        await state.clear()

@dp.message(Command("reply"))
async def cmd_reply(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: <code>/reply &lt;user_id&gt; &lt;message&gt;</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    text = parts[2]
    try:
        await bot.send_message(
            target_id,
            f"💌 <b>Message from Soulmate India Support:</b>\n\n{text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Reply delivered to <code>{target_id}</code>!", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Failed: {e}")

@dp.message(Command("notice"))
async def cmd_notice(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: <code>/notice &lt;telegram_id&gt; &lt;message&gt;</code>", parse_mode="HTML")
        return
    
    target_id = int(parts[1])
    notice_text = parts[2]
    
    try:
        await bot.send_message(
            target_id,
            f"📢 <b>Official Notice from Administration</b>\n\n{notice_text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Notice delivered to <code>{target_id}</code>!", parse_mode="HTML")
    except TelegramForbiddenError:
        await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", target_id)
        await message.answer(f"❌ User <code>{target_id}</code> blocked the bot or account is deactivated. Soft-hidden.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Failed to deliver: {e}")

@dp.message(Command("user"))
async def cmd_inspect_user(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/user &lt;telegram_id&gt;</code>", parse_mode="HTML")
        return
    user_id = int(parts[1])
    await inspect_user_profile(user_id, message)

@dp.callback_query(F.data.startswith("inspect_user_"))
async def cb_inspect_user(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split("_")[2])
    await inspect_user_profile(user_id, callback.message)
    await callback.answer()

async def inspect_user_profile(user_id: int, message_or_obj):
    rows = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)
    if not rows:
        await message_or_obj.reply(f"❌ User <code>{user_id}</code> not found in database.", parse_mode="HTML")
        return
    u = rows[0]

    likes_given = (await db_query("SELECT COUNT(*) as c FROM swipes WHERE swiper_id = ? AND action = 'like'", user_id))[0]['c']
    likes_received = (await db_query("SELECT COUNT(*) as c FROM swipes WHERE swiped_id = ? AND action = 'like'", user_id))[0]['c']
    matches_cnt = (await db_query("SELECT COUNT(*) as c FROM matches WHERE user1_id = ? OR user2_id = ?", user_id, user_id))[0]['c']
    reports_cnt = (await db_query("SELECT COUNT(*) as c FROM reports WHERE reported_id = ?", user_id))[0]['c']

    user_link = safe_user_mention(u['telegram_id'], u['full_name'], u['username'])
    details = (
        f"🔍 <b>User Dossier:</b> {user_link}\n\n"
        f"• <b>Telegram ID:</b> <code>{u['telegram_id']}</code>\n"
        f"• <b>Age / Gender:</b> {u['age']} | {u['gender']} (Seeking: {u['target_gender']})\n"
        f"• <b>City:</b> {u['city']}\n"
        f"• <b>Verified:</b> {'Yes 🛡️' if u['is_verified'] else 'No ❌'}\n"
        f"• <b>Active/Approved:</b> {'Yes 🟢' if u['is_approved'] else 'Paused ⚪'}\n"
        f"• <b>Status:</b> {'🚫 BANNED' if u['is_banned'] else 'Normal'}\n"
        f"• <b>Activity:</b> Given: {likes_given} ❤️ | Received: {likes_received} 💌\n"
        f"• <b>Matches:</b> {matches_cnt} | <b>Reports Against:</b> {reports_cnt} 🚨\n\n"
        f"📝 <b>Bio:</b> {u['bio']}"
    )

    action_buttons = []
    if u['is_banned']:
        action_buttons.append(InlineKeyboardButton(text="🟢 Unban", callback_data=f"admin_unban_{user_id}"))
    else:
        action_buttons.append(InlineKeyboardButton(text="🚫 Ban", callback_data=f"admin_ban_{user_id}"))
    action_buttons.append(InlineKeyboardButton(text="💬 Message", callback_data=f"admin_prep_reply_{user_id}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[action_buttons])
    await message_or_obj.reply_photo(u['photo_id'], caption=details, parse_mode="HTML", reply_markup=kb)

@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/ban &lt;telegram_id&gt;</code>", parse_mode="HTML")
        return
    user_id = int(parts[1])
    await db_execute("UPDATE users SET is_banned = 1, is_approved = 0 WHERE telegram_id = ?", user_id)
    await message.answer(f"🚫 User <code>{user_id}</code> is now banned and removed from discovery.", parse_mode="HTML")
    try:
        await bot.send_message(user_id, "🚫 Your account has been suspended for violating our terms.")
    except Exception:
        pass

@dp.message(Command("unban"))
async def cmd_unban(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/unban &lt;telegram_id&gt;</code>", parse_mode="HTML")
        return
    user_id = int(parts[1])
    await db_execute("UPDATE users SET is_banned = 0, is_approved = 1 WHERE telegram_id = ? AND is_verified = 1", user_id)
    await message.answer(f"🟢 User <code>{user_id}</code> unbanned and restored to discovery.", parse_mode="HTML")

@dp.callback_query(F.data.startswith("admin_unban_"))
async def cb_admin_unban(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split("_")[2])
    await db_execute("UPDATE users SET is_banned = 0, is_approved = 1 WHERE telegram_id = ? AND is_verified = 1", user_id)
    await callback.message.reply(f"🟢 User <code>{user_id}</code> unbanned.", parse_mode="HTML")
    await callback.answer("Unbanned.")

@dp.callback_query(F.data.startswith("admin_ban_"))
async def cb_admin_ban(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split("_")[2])
    await db_execute("UPDATE users SET is_banned = 1, is_approved = 0 WHERE telegram_id = ?", user_id)
    await callback.message.reply(f"🚫 User <code>{user_id}</code> banned and soft-hidden.", parse_mode="HTML")
    try:
        await bot.send_message(user_id, "🚫 Your account has been suspended.")
    except Exception:
        pass
    await callback.answer("Banned.")

# ---------------------------------------------------------
# Segmented & Global Broadcasts
# ---------------------------------------------------------
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/broadcast", "", 1).strip()
    if not text:
        await message.answer("Usage: <code>/broadcast &lt;message&gt;</code>", parse_mode="HTML")
        return
    users = await db_query("SELECT telegram_id FROM users WHERE is_banned = 0")
    await run_broadcast(users, text, message)

@dp.message(Command("broadcast_city"))
async def cmd_broadcast_city(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: <code>/broadcast_city &lt;City&gt; &lt;message&gt;</code>", parse_mode="HTML")
        return
    city, text = parts[1].strip().title(), parts[2].strip()
    users = await db_query("SELECT telegram_id FROM users WHERE LOWER(city) = LOWER(?) AND is_banned = 0", city)
    await run_broadcast(users, text, message, target_desc=f"City: {city}")

@dp.message(Command("broadcast_gender"))
async def cmd_broadcast_gender(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: <code>/broadcast_gender &lt;Male|Female&gt; &lt;message&gt;</code>", parse_mode="HTML")
        return
    gender, text = parts[1].strip().title(), parts[2].strip()
    users = await db_query("SELECT telegram_id FROM users WHERE gender = ? AND is_banned = 0", gender)
    await run_broadcast(users, text, message, target_desc=f"Gender: {gender}")

async def run_broadcast(users, text, admin_msg, target_desc="All Users"):
    sent, blocked = 0, 0
    for u in users:
        uid = u["telegram_id"]
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            blocked += 1
            await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", uid)
        except Exception:
            blocked += 1

    await admin_msg.answer(
        f"✅ <b>Broadcast Completed! ({target_desc})</b>\n\n• 📬 Delivered: {sent}\n• 🚫 Blocked/Failed: {blocked}",
        parse_mode="HTML"
    )

# ---------------------------------------------------------
# Admin Stats & Reminders
# ---------------------------------------------------------
@dp.message(Command("admin_stats"))
async def cmd_admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    users_cnt = (await db_query("SELECT COUNT(*) as c FROM users"))[0]['c']
    verified_cnt = (await db_query("SELECT COUNT(*) as c FROM users WHERE is_verified = 1"))[0]['c']
    approved_cnt = (await db_query("SELECT COUNT(*) as c FROM users WHERE is_approved = 1"))[0]['c']
    pending_verif = (await db_query("SELECT COUNT(*) as c FROM users WHERE is_verified = 0 AND is_banned = 0"))[0]['c']
    dropoffs = (await db_query("""
        SELECT COUNT(*) as c FROM pending_registrations p 
        LEFT JOIN users u ON p.telegram_id = u.telegram_id 
        WHERE u.telegram_id IS NULL
    """))[0]['c']
    matches_cnt = (await db_query("SELECT COUNT(*) as c FROM matches"))[0]['c']
    swipes_cnt = (await db_query("SELECT COUNT(*) as c FROM swipes"))[0]['c']
    feedback_cnt = (await db_query("SELECT COUNT(*) as c FROM feedback"))[0]['c']
    reports_cnt = (await db_query("SELECT COUNT(*) as c FROM reports"))[0]['c']

    engine_label = "Neon PostgreSQL (Cloud ☁️)" if is_postgres else "SQLite (Local File 📁)"

    stats_msg = (
        f"📊 <b>Soulmate India Administration Dashboard</b>\n\n"
        f"💾 <b>Database Engine:</b> {engine_label}\n"
        f"👥 <b>Total Registered:</b> {users_cnt}\n"
        f"🛡️ <b>Verified Profiles:</b> {verified_cnt}\n"
        f"🟢 <b>Active in Discovery:</b> {approved_cnt}\n"
        f"⏳ <b>Awaiting Verification:</b> {pending_verif}\n"
        f"🚪 <b>Drop-offs:</b> {dropoffs}\n"
        f"❤️ <b>Total Swipes:</b> {swipes_cnt}\n"
        f"💍 <b>Total Matches:</b> {matches_cnt}\n"
        f"💬 <b>Feedback Submissions:</b> {feedback_cnt}\n"
        f"🚨 <b>Total Reports Logged:</b> {reports_cnt}"
    )
    await message.answer(stats_msg, parse_mode="HTML")

@dp.message(Command("remind_unverified"))
async def cmd_remind_unverified(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    rows = await db_query("SELECT telegram_id FROM users WHERE is_verified = 0 AND is_banned = 0")
    if not rows:
        await message.answer("✅ No users currently pending verification.")
        return
    sent, blocked = 0, 0
    for r in rows:
        uid = r["telegram_id"]
        try:
            await bot.send_message(
                uid,
                "⏳ <b>Your Soulmate India Profile is Under Review</b>\n\n"
                "Our team is currently verifying your gesture selfie. You'll be ready to discover matches very soon!",
                parse_mode="HTML"
            )
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            blocked += 1
            await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", uid)
        except Exception:
            blocked += 1
    await message.answer(f"✅ <b>Reminders Complete!</b>\n\n• 📬 Delivered: {sent}\n• 🚫 Blocked: {blocked}", parse_mode="HTML")

@dp.message(Command("remind_incomplete"))
async def cmd_remind_incomplete(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    dropoffs = await db_query("""
        SELECT p.telegram_id FROM pending_registrations p
        LEFT JOIN users u ON p.telegram_id = u.telegram_id
        WHERE u.telegram_id IS NULL
    """)
    if not dropoffs:
        await message.answer("✅ No incomplete signups found.")
        return
    sent, blocked = 0, 0
    for d in dropoffs:
        uid = d["telegram_id"]
        try:
            await bot.send_message(
                uid,
                "✨ <b>You're almost there!</b>\n\n"
                "You started setting up your profile on <b>Soulmate India</b> but didn't finish.\n"
                "Tap /start to complete your profile in 60 seconds and find genuine matches!",
                parse_mode="HTML"
            )
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            blocked += 1
            await db_execute("DELETE FROM pending_registrations WHERE telegram_id = ?", uid)
        except Exception:
            blocked += 1
    await message.answer(f"✅ <b>Drop-off Reminders Complete!</b>\n\n• 📬 Delivered: {sent}\n• 🚫 Blocked: {blocked}", parse_mode="HTML")

# ---------------------------------------------------------
# Embedded Web Server (Port Binding for Render)
# ---------------------------------------------------------
async def handle_health(request):
    return web.Response(text="Soulmate India Bot is healthy!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Render Web Server bound to port {PORT}")

# ---------------------------------------------------------
# Application Entrypoint
# ---------------------------------------------------------
async def main():
    await init_db()
    await start_web_server()

    # Register private admin command menu visible ONLY to your account
    admin_commands = [
        BotCommand(command="admin", description="🛠️ Admin Control Center & Cheat Sheet"),
        BotCommand(command="admin_stats", description="📊 System & Database Metrics"),
        BotCommand(command="remind_incomplete", description="🚪 Nudge Registration Drop-offs"),
        BotCommand(command="remind_unverified", description="⏳ Nudge Pending Approvals"),
        BotCommand(command="broadcast", description="📢 Global Announcement"),
    ]
    try:
        await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    except Exception as e:
        logger.warning(f"Could not register admin command menu: {e}")

    logger.info("Bot is live with Neon PostgreSQL, Anti-Fake Gestures, and Render Web Server...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
