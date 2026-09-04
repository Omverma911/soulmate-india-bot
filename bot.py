import os
import sys
import re
import math
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8925689319"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
PORT = int(os.environ.get("PORT", "10000"))
DAILY_SWIPE_LIMIT = int(os.environ.get("DAILY_SWIPE_LIMIT", "50"))

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable is not set!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

db_pool = None
sqlite_db_path = "dating_bot.db"
is_postgres = False

# ---------------------------------------------------------
# Geodesic Math Utility (Haversine Formula)
# ---------------------------------------------------------
def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculates distance between two GPS coordinates in Kilometers."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)

# ---------------------------------------------------------
# Database Layer (Neon PostgreSQL & SQLite Fallback)
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
            logger.info("✅ SUCCESS: Connected to Neon PostgreSQL!")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Neon PostgreSQL: {e}")
            logger.warning("Falling back to local SQLite storage...")
            is_postgres = False
    else:
        is_postgres = False

    schema = """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            age INT,
            gender TEXT,
            target_gender TEXT,
            country TEXT,
            state TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            bio TEXT,
            photo_id TEXT,
            gesture_photo_id TEXT,
            karma_score INT DEFAULT 100,
            total_chats INT DEFAULT 0,
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
        CREATE TABLE IF NOT EXISTS active_chats (
            user_id BIGINT PRIMARY KEY,
            partner_id BIGINT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS roulette_queue (
            user_id BIGINT PRIMARY KEY,
            gender TEXT,
            target_gender TEXT,
            country TEXT,
            state TEXT,
            mode TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        CREATE TABLE IF NOT EXISTS chat_ratings (
            id SERIAL PRIMARY KEY,
            rater_id BIGINT,
            rated_id BIGINT,
            rating INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """

    if is_postgres:
        async with db_pool.acquire() as conn:
            await conn.execute(schema)
            # Safe column check without syntax errors
            for col in ["country", "state"]:
                try:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} TEXT;")
                except Exception:
                    pass
                try:
                    await conn.execute(f"ALTER TABLE roulette_queue ADD COLUMN IF NOT EXISTS {col} TEXT;")
                except Exception:
                    pass
    else:
        sqlite_schema = (schema
                         .replace("BIGINT", "INTEGER")
                         .replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                         .replace("DOUBLE PRECISION", "REAL"))
        async with aiosqlite.connect(sqlite_db_path) as db:
            await db.executescript(sqlite_schema)
            await db.commit()

async def db_execute(query: str, *args):
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
    mandatory_gps = State()
    country = State()
    state_province = State()
    bio = State()
    photo = State()
    gesture_selfie = State()

class RetakeSelfie(StatesGroup):
    waiting_for_photo = State()

class FeedbackStates(StatesGroup):
    waiting_for_feedback = State()

class AdminReplyState(StatesGroup):
    waiting_for_reply = State()

class EditProfileState(StatesGroup):
    editing_photo = State()
    editing_bio = State()

# ---------------------------------------------------------
# Helpers & Validation
# ---------------------------------------------------------
def is_valid_name(name: str) -> bool:
    name = name.strip()
    return 2 <= len(name) <= 32 and bool(re.match(r"^[A-Za-z\s.'-]+$", name)) and bool(re.findall(r"[aeiouAEIOU]", name))

def is_valid_text(val: str) -> bool:
    val = val.strip()
    return 2 <= len(val) <= 40 and bool(re.match(r"^[A-Za-z\s.-]+$", val))

def safe_user_mention(user_id: int, full_name: str, username: str = None) -> str:
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={user_id}">{full_name}</a>'

def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Discover (Proximity)"), KeyboardButton(text="⚡ Random Chat Roulette")],
            [KeyboardButton(text="👤 My Profile"), KeyboardButton(text="💌 Matches")],
            [KeyboardButton(text="💬 Feedback")]
        ],
        resize_keyboard=True
    )

def anon_chat_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏹️ End Chat"), KeyboardButton(text="📍 Share Proximity")],
            [KeyboardButton(text="🚨 Report Stranger"), KeyboardButton(text="⏭️ Next Person")]
        ],
        resize_keyboard=True
    )

# ---------------------------------------------------------
# Lifecycle Management
# ---------------------------------------------------------
@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=KICKED))
async def handle_user_blocked(event: types.ChatMemberUpdated):
    user_id = event.from_user.id
    logger.info(f"🚫 User {user_id} blocked bot. Soft-hiding profile.")
    await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", user_id)
    await db_execute("DELETE FROM roulette_queue WHERE user_id = ?", user_id)
    await end_anonymous_session(user_id, send_notice=False)

@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=MEMBER))
async def handle_user_unblocked(event: types.ChatMemberUpdated):
    user_id = event.from_user.id
    logger.info(f"✨ User {user_id} unblocked bot.")
    await db_execute("UPDATE users SET is_approved = 1 WHERE telegram_id = ? AND is_verified = 1 AND is_banned = 0", user_id)

# ---------------------------------------------------------
# Admin Control Suite (Placed First to Guarantee Precedence)
# ---------------------------------------------------------
@dp.message(Command("admin", "admin_help"))
async def cmd_admin_help(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    admin_text = (
        "🛠️ <b>Soulmate Global & India Admin Control Center</b>\n\n"
        "📊 <b>Diagnostics & Monitoring:</b>\n"
        "• <code>/admin_stats</code> — DB engine, active users, matches, swipes, reports, drop-offs.\n"
        "• <code>/user &lt;id&gt;</code> — Detailed dossier (photos, swipe counts, matches, ban toggles).\n\n"
        "📢 <b>Broadcasts:</b>\n"
        "• <code>/broadcast &lt;msg&gt;</code> — Send announcement to all active users.\n"
        "• <code>/broadcast_country &lt;Country&gt; &lt;msg&gt;</code> — Target single country.\n"
        "• <code>/broadcast_gender &lt;Male|Female&gt; &lt;msg&gt;</code> — Target specific gender.\n\n"
        "💬 <b>Official Messaging:</b>\n"
        "• <code>/notice &lt;id&gt; &lt;msg&gt;</code> — Send official notice banner.\n"
        "• <code>/reply &lt;id&gt; &lt;msg&gt;</code> — Send anonymous support reply.\n\n"
        "🛡️ <b>Moderation & Access:</b>\n"
        "• <code>/ban &lt;id&gt;</code> — Soft-hide and suspend a user from discovery.\n"
        "• <code>/unban &lt;id&gt;</code> — Restore an account to active discovery.\n\n"
        "⏰ <b>Retention Nudges:</b>\n"
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
    active_roulette = (await db_query("SELECT COUNT(*) as c FROM active_chats"))[0]['c']
    waiting_roulette = (await db_query("SELECT COUNT(*) as c FROM roulette_queue"))[0]['c']
    feedback_cnt = (await db_query("SELECT COUNT(*) as c FROM feedback"))[0]['c']
    reports_cnt = (await db_query("SELECT COUNT(*) as c FROM reports"))[0]['c']

    engine_label = "Neon PostgreSQL (Cloud ☁️)" if is_postgres else "SQLite (Local File 📁)"

    stats_msg = (
        f"📊 <b>Soulmate Global Administration Dashboard</b>\n\n"
        f"💾 <b>Database Engine:</b> {engine_label}\n"
        f"👥 <b>Total Registered:</b> {users_cnt}\n"
        f"🛡️ <b>Verified Profiles:</b> {verified_cnt}\n"
        f"🟢 <b>Active in Discovery:</b> {approved_cnt}\n"
        f"⏳ <b>Awaiting Verification:</b> {pending_verif}\n"
        f"🚪 <b>Drop-offs:</b> {dropoffs}\n"
        f"❤️ <b>Total Swipes:</b> {swipes_cnt}\n"
        f"💍 <b>Total Matches:</b> {matches_cnt}\n"
        f"🎭 <b>Roulette Rooms Active:</b> {active_roulette // 2}\n"
        f"⏳ <b>Roulette Queue:</b> {waiting_roulette} waiting\n"
        f"💬 <b>Feedback Submissions:</b> {feedback_cnt}\n"
        f"🚨 <b>Total Reports Logged:</b> {reports_cnt}"
    )
    await message.answer(stats_msg, parse_mode="HTML")

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
    loc_str = f"{u.get('state', '')}, {u.get('country', '')}".strip(", ") or "GPS Stored"
    details = (
        f"🔍 <b>User Dossier:</b> {user_link}\n\n"
        f"• <b>Telegram ID:</b> <code>{u['telegram_id']}</code>\n"
        f"• <b>Age / Gender:</b> {u['age']} | {u['gender']} (Seeking: {u['target_gender']})\n"
        f"• <b>Location:</b> {loc_str}\n"
        f"• <b>Karma:</b> {u['karma_score']} pts | Chats: {u['total_chats']}\n"
        f"• <b>Verified:</b> {'Yes 🛡️' if u['is_verified'] else 'No ❌'}\n"
        f"• <b>Approved/Active:</b> {'Yes 🟢' if u['is_approved'] else 'Paused ⚪'}\n"
        f"• <b>Status:</b> {'🚫 BANNED' if u['is_banned'] else 'Normal'}\n"
        f"• <b>Activity:</b> Given: {likes_given} ❤️ | Received: {likes_received} 💌\n"
        f"• <b>Matches:</b> {matches_cnt} | <b>Reports:</b> {reports_cnt} 🚨\n\n"
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
    await message.answer(f"🚫 User <code>{user_id}</code> is now banned and soft-hidden.", parse_mode="HTML")
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
            f"💌 <b>Message from Soulmate Support:</b>\n\n{text}",
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
        await bot.send_message(target_id, f"📢 <b>Official Notice from Administration</b>\n\n{notice_text}", parse_mode="HTML")
        await message.answer(f"✅ Notice delivered to <code>{target_id}</code>!", parse_mode="HTML")
    except TelegramForbiddenError:
        await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", target_id)
        await message.answer(f"❌ User <code>{target_id}</code> blocked the bot or account deactivated.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Failed to deliver: {e}")

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

@dp.message(Command("broadcast_country"))
async def cmd_broadcast_country(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: <code>/broadcast_country &lt;Country&gt; &lt;message&gt;</code>", parse_mode="HTML")
        return
    country, text = parts[1].strip().title(), parts[2].strip()
    users = await db_query("SELECT telegram_id FROM users WHERE LOWER(country) = LOWER(?) AND is_banned = 0", country)
    await run_broadcast(users, text, message, target_desc=f"Country: {country}")

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
                "⏳ <b>Your Soulmate Profile is Under Review</b>\n\n"
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
                "You started setting up your profile on <b>Soulmate Global</b> but didn't finish.\n"
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
# User Registration FSM Handlers
# ---------------------------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    users = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)

    if users:
        u = users[0]
        if u["is_banned"]:
            await message.answer("🚫 Your account has been suspended by administration.")
            return
        if not u["is_approved"] and u["is_verified"]:
            await db_execute("UPDATE users SET is_approved = 1 WHERE telegram_id = ?", user_id)

        loc_label = f"{u.get('state', '')}, {u.get('country', '')}".strip(", ") or "GPS Verified"
        await message.answer(
            f"✨ <b>Welcome back, {u['full_name']}!</b>\n"
            f"📍 Location: <b>{loc_label}</b> | ⭐ Karma: <b>{u['karma_score']} pts</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )
        return

    await db_execute("INSERT INTO pending_registrations (telegram_id) VALUES (?) ON CONFLICT DO NOTHING", user_id)
    await state.set_state(Registration.name)
    await message.answer(
        "🌐 <b>Welcome to Soulmate Global & India 💌</b>\n\n"
        "Let's create your dating profile in a few quick steps.\n"
        "What is your authentic <b>First & Last Name</b>?",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Registration.name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not is_valid_name(name):
        await message.answer("⚠️ <b>Invalid name.</b> Please enter your real name using letters only (2–32 characters).", parse_mode="HTML")
        return
    await state.update_data(full_name=name)
    await state.set_state(Registration.age)
    await message.answer("Great! How old are you? (Enter your real age between 18 and 75)")

@dp.message(Registration.age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (18 <= int(message.text) <= 75):
        await message.answer("⚠️ Please enter a valid age between <b>18 and 75</b>.", parse_mode="HTML")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(Registration.gender)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Male"), KeyboardButton(text="Female"), KeyboardButton(text="Other")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("What is your gender?", reply_markup=kb)

@dp.message(Registration.gender)
async def process_gender(message: types.Message, state: FSMContext):
    if message.text not in ["Male", "Female", "Other"]:
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
    if message.text not in ["Female", "Male", "Everyone"]:
        await message.answer("Please select an option using the keyboard.")
        return
    await state.update_data(target_gender=message.text)
    await state.set_state(Registration.mandatory_gps)

    gps_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛰️ Share Live Location (Mandatory)", request_location=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "📍 <b>GPS Verification (Mandatory):</b>\n\n"
        "To prevent fake location spoofing and show accurate distance in kilometers, "
        "please tap the button below to share your live GPS location.",
        parse_mode="HTML",
        reply_markup=gps_kb
    )

@dp.message(Registration.mandatory_gps, F.location)
async def process_mandatory_gps(message: types.Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    await state.update_data(latitude=lat, longitude=lon)
    await state.set_state(Registration.country)
    await message.answer(
        "🛰️ <b>GPS Coordinates Verified!</b>\n\n"
        "What is your <b>Nationality / Country</b>? (e.g. India, United States, UAE, United Kingdom):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Registration.mandatory_gps)
async def process_mandatory_gps_invalid(message: types.Message):
    gps_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛰️ Share Live Location (Mandatory)", request_location=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("⚠️ You must tap <b>🛰️ Share Live Location</b> to continue.", parse_mode="HTML", reply_markup=gps_kb)

@dp.message(Registration.country)
async def process_country(message: types.Message, state: FSMContext):
    country = message.text.strip().title()
    if not is_valid_text(country):
        await message.answer("⚠️ Please enter a valid country name (letters only).")
        return
    await state.update_data(country=country)
    await state.set_state(Registration.state_province)
    await message.answer(f"Got it, {country}! Now enter your <b>State / Province</b> (e.g. Jharkhand, Maharashtra, California):", parse_mode="HTML")

@dp.message(Registration.state_province)
async def process_state(message: types.Message, state: FSMContext):
    state_prov = message.text.strip().title()
    if not is_valid_text(state_prov):
        await message.answer("⚠️ Please enter a valid state/province name (letters only).")
        return
    await state.update_data(state=state_prov)
    await state.set_state(Registration.bio)
    await message.answer("Write a short bio about yourself (passions, lifestyle, hobbies):")

@dp.message(Registration.bio)
async def process_bio(message: types.Message, state: FSMContext):
    bio_text = message.text.strip()
    if len(bio_text) < 5 or len(bio_text) > 400:
        await message.answer("⚠️ Bio must be between 5 and 400 characters.")
        return
    await state.update_data(bio=bio_text)
    await state.set_state(Registration.photo)
    await message.answer("📸 Please upload your primary profile picture:")

@dp.message(Registration.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(Registration.gesture_selfie)
    await message.answer(
        "✌️ <b>Anti-Fake Verification Step</b>\n\n"
        "To earn the <b>Blue Shield Badge 🛡️</b> and prevent catfishing, upload a selfie holding up a <b>Peace Sign (✌️)</b>.\n\n"
        "<i>Send as photo or uncompressed image. This photo is strictly confidential and is never shown publicly on your profile.</i>",
        parse_mode="HTML"
    )

@dp.message(Registration.photo)
async def process_photo_invalid(message: types.Message):
    await message.answer("⚠️ Please upload an image photo for your profile.")

@dp.message(Registration.gesture_selfie, F.photo | F.document)
async def process_gesture_selfie(message: types.Message, state: FSMContext):
    gesture_photo_id = None
    if message.photo:
        gesture_photo_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        gesture_photo_id = message.document.file_id

    if not gesture_photo_id:
        await message.answer("⚠️ Please send an actual image holding up a Peace Sign (✌️).")
        return

    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username or ""

    await db_execute("""
        INSERT INTO users (
            telegram_id, full_name, username, age, gender, target_gender,
            country, state, latitude, longitude, bio, photo_id, gesture_photo_id,
            karma_score, is_verified, is_approved, is_banned
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 100, 0, 0, 0)
        ON CONFLICT (telegram_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            username = EXCLUDED.username,
            age = EXCLUDED.age,
            gender = EXCLUDED.gender,
            target_gender = EXCLUDED.target_gender,
            country = EXCLUDED.country,
            state = EXCLUDED.state,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            bio = EXCLUDED.bio,
            photo_id = EXCLUDED.photo_id,
            gesture_photo_id = EXCLUDED.gesture_photo_id,
            is_verified = 0,
            is_approved = 0
    """, user_id, data['full_name'], username, data['age'], data['gender'],
       data['target_gender'], data['country'], data['state'], data['latitude'], data['longitude'],
       data['bio'], data['photo_id'], gesture_photo_id)

    await db_execute("DELETE FROM pending_registrations WHERE telegram_id = ?", user_id)
    await state.clear()

    await message.answer(
        "🎉 <b>Profile & Gesture Selfie Received!</b>\n\n"
        "Our moderators are reviewing your peace sign gesture selfie. You'll receive a notification here once approved!",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"verify_ok_{user_id}"),
            InlineKeyboardButton(text="⚠️ Retake Selfie", callback_data=f"verify_retry_{user_id}")
        ],
        [InlineKeyboardButton(text="🚫 Ban", callback_data=f"admin_ban_{user_id}")]
    ])
    user_link = safe_user_mention(user_id, data['full_name'], username)
    caption = (
        f"🚨 <b>New Profile Verification Request</b>\n\n"
        f"👤 <b>User:</b> {user_link} (<code>{user_id}</code>)\n"
        f"🎂 <b>Age/Gender:</b> {data['age']} | {data['gender']} (Seeking: {data['target_gender']})\n"
        f"📍 <b>Location:</b> {data['state']}, {data['country']}\n"
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

@dp.message(Registration.gesture_selfie)
async def fallback_gesture_selfie(message: types.Message):
    await message.answer("⚠️ Please upload a <b>photo</b> of you holding up a Peace Sign (✌️).", parse_mode="HTML")

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
            "You've received your Blue Verified Badge 🛡️. Tap <b>🔍 Discover (Proximity)</b> to meet singles nearby!",
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
            "⚠️ <b>Verification Incomplete</b>\n\n"
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

@dp.message(RetakeSelfie.waiting_for_photo, F.photo | F.document)
async def process_retake_photo(message: types.Message, state: FSMContext):
    gesture_photo_id = None
    if message.photo:
        gesture_photo_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        gesture_photo_id = message.document.file_id

    if not gesture_photo_id:
        await message.answer("⚠️ Please send an image photo.")
        return

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
# Profile Management & Full Profile Editing Suite
# ---------------------------------------------------------
@dp.message(F.text.in_(["👤 My Profile", "/profile"]))
async def cmd_my_profile(message: types.Message):
    user_id = message.from_user.id
    rows = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)
    if not rows:
        await message.answer("Profile not found. Send /start to register!")
        return
    u = rows[0]
    badge = "🛡️ Verified" if u["is_verified"] else "⏳ Under Review"
    status = "Visible 🟢" if u["is_approved"] else "Hidden / Paused ⚪"
    loc_label = f"{u.get('state', '')}, {u.get('country', '')}".strip(", ") or "GPS Stored"
    
    caption = (
        f"👤 <b>{u['full_name']}</b>, {u['age']}\n"
        f"📍 <b>Location:</b> {loc_label}\n"
        f"🎯 <b>Looking For:</b> {u['target_gender']}\n"
        f"⭐ <b>Karma Score:</b> {u['karma_score']} pts\n"
        f"🛡️ <b>Badge:</b> {badge}\n"
        f"👁️ <b>Discovery:</b> {status}\n\n"
        f"📝 <i>{u['bio']}</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📸 Change Photo", callback_data="edit_prof_photo"),
            InlineKeyboardButton(text="📝 Edit Bio", callback_data="edit_prof_bio")
        ],
        [
            InlineKeyboardButton(text="🎯 Preferences", callback_data="edit_prof_pref"),
            InlineKeyboardButton(text="🗑️ Deactivate Profile", callback_data="confirm_soft_delete")
        ]
    ])
    await message.answer_photo(u["photo_id"], caption=caption, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "edit_prof_photo")
async def cb_edit_photo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditProfileState.editing_photo)
    await callback.message.reply("📸 Send your new portrait profile photo:")
    await callback.answer()

@dp.message(EditProfileState.editing_photo, F.photo)
async def process_edit_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await db_execute("UPDATE users SET photo_id = ? WHERE telegram_id = ?", photo_id, message.from_user.id)
    await state.clear()
    await message.answer("✅ Profile photo updated successfully!", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "edit_prof_bio")
async def cb_edit_bio(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditProfileState.editing_bio)
    await callback.message.reply("📝 Type your new profile bio below:")
    await callback.answer()

@dp.message(EditProfileState.editing_bio)
async def process_edit_bio(message: types.Message, state: FSMContext):
    bio_text = message.text.strip()
    if len(bio_text) < 5 or len(bio_text) > 400:
        await message.answer("⚠️ Please write a bio between 5 and 400 characters.")
        return
    await db_execute("UPDATE users SET bio = ? WHERE telegram_id = ?", bio_text, message.from_user.id)
    await state.clear()
    await message.answer("✅ Bio updated successfully!", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "edit_prof_pref")
async def cb_edit_pref(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Women", callback_data="set_pref_Female"),
            InlineKeyboardButton(text="Men", callback_data="set_pref_Male"),
            InlineKeyboardButton(text="Everyone", callback_data="set_pref_Everyone")
        ]
    ])
    await callback.message.reply("🎯 Who would you like to see in Discovery?", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_pref_"))
async def cb_set_pref(callback: types.CallbackQuery):
    pref = callback.data.split("_")[2]
    await db_execute("UPDATE users SET target_gender = ? WHERE telegram_id = ?", pref, callback.from_user.id)
    await callback.message.edit_text(f"✅ Preference updated! Looking for: <b>{pref}</b>", parse_mode="HTML")
    await callback.answer()

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
        "All your photos, matches, and chat history remain safely stored. You can return anytime by typing /start.",
        parse_mode="HTML"
    )
    await callback.answer()

# ---------------------------------------------------------
# Interactive Matches Tab
# ---------------------------------------------------------
@dp.message(F.text == "💌 Matches")
async def cmd_matches(message: types.Message):
    user_id = message.from_user.id
    matches = await db_query("""
        SELECT CASE WHEN user1_id = ? THEN user2_id ELSE user1_id END as matched_user_id, matched_at
        FROM matches WHERE user1_id = ? OR user2_id = ? ORDER BY matched_at DESC LIMIT 10
    """, user_id, user_id, user_id)

    if not matches:
        await message.answer("💌 <b>No matches yet!</b>\n\nSwipe in <b>🔍 Discover</b> or meet people in <b>⚡ Roulette</b>!", parse_mode="HTML")
        return

    await message.answer(f"💌 <b>Your Matches ({len(matches)}):</b>")
    for m in matches:
        uid = m['matched_user_id']
        u_rows = await db_query("SELECT * FROM users WHERE telegram_id = ?", uid)
        if not u_rows:
            continue
        u = u_rows[0]
        chat_url = f"https://t.me/{u['username']}" if u['username'] else f"tg://user?id={uid}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Open Private Chat", url=chat_url)]])
        loc_str = f"{u.get('state', '')}, {u.get('country', '')}".strip(", ")
        await message.answer_photo(
            u['photo_id'],
            caption=f"✨ <b>{u['full_name']}</b>, {u['age']} ({loc_str})\n📝 <i>{u['bio']}</i>",
            parse_mode="HTML",
            reply_markup=kb
        )

# ---------------------------------------------------------
# Filtered Proximity Discovery & Daily Swipe Limit
# ---------------------------------------------------------
async def check_daily_swipe_limit(user_id: int) -> bool:
    if is_postgres:
        count_row = await db_query("""
            SELECT COUNT(*) as c FROM swipes 
            WHERE swiper_id = ? AND created_at > (CURRENT_TIMESTAMP - INTERVAL '24 HOURS')
        """, user_id)
    else:
        count_row = await db_query("""
            SELECT COUNT(*) as c FROM swipes 
            WHERE swiper_id = ? AND created_at > datetime('now', '-24 hours')
        """, user_id)
    return count_row[0]['c'] >= DAILY_SWIPE_LIMIT

@dp.message(F.text.in_(["🔍 Discover (Proximity)", "🔍 Discover Matches"]))
async def cmd_discover(message: types.Message):
    user_id = message.from_user.id
    current_users = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)
    if not current_users or not current_users[0]["is_approved"]:
        await message.answer("⚠️ You must have an approved profile to discover matches. If awaiting verification, hang tight!")
        return
    
    if await check_daily_swipe_limit(user_id):
        await message.answer(
            f"⏳ <b>Daily swipe limit reached ({DAILY_SWIPE_LIMIT}/{DAILY_SWIPE_LIMIT})!</b>\n\n"
            "Take a break and check back in a few hours. Try <b>⚡ Random Chat Roulette</b> in the meantime!",
            parse_mode="HTML"
        )
        return

    me = current_users[0]
    my_gender = me['gender']
    my_target = me['target_gender']

    query = """
        SELECT * FROM users 
        WHERE is_approved = 1 
          AND is_banned = 0 
          AND telegram_id != ?
          AND telegram_id NOT IN (SELECT swiped_id FROM swipes WHERE swiper_id = ?)
    """
    params = [user_id, user_id]

    if my_target in ["Male", "Female"]:
        query += " AND gender = ?"
        params.append(my_target)
    
    query += " AND (target_gender = ? OR target_gender = 'Everyone') LIMIT 30"
    params.append(my_gender)

    deck = await db_query(query, *params)

    if not deck:
        await message.answer("🎉 You're all caught up! Check back soon or chat in <b>⚡ Random Chat Roulette</b>!", parse_mode="HTML")
        return

    def sort_distance(cand):
        dist = calculate_distance(me['latitude'], me['longitude'], cand['latitude'], cand['longitude'])
        return dist if dist is not None else 999999

    deck.sort(key=sort_distance)
    candidate = deck[0]
    cand_id = candidate["telegram_id"]

    dist_km = calculate_distance(me['latitude'], me['longitude'], candidate['latitude'], candidate['longitude'])
    dist_str = f"📍 <b>{dist_km} km away</b>" if dist_km is not None else f"📍 <b>{candidate.get('state', '')}, {candidate.get('country', '')}</b>"

    badge = "🛡️ Verified" if candidate["is_verified"] else ""
    caption = (
        f"✨ <b>{candidate['full_name']}</b>, {candidate['age']} {badge}\n"
        f"{dist_str} | ⭐ Karma: {candidate['karma_score']}\n\n"
        f"📝 <i>{candidate['bio']}</i>"
    )
    swipe_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Pass", callback_data=f"swipe_pass_{cand_id}"),
            InlineKeyboardButton(text="❤️ Like", callback_data=f"swipe_like_{cand_id}")
        ],
        [InlineKeyboardButton(text="🚨 Report Profile", callback_data=f"report_card_{cand_id}")]
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

            await callback.message.answer(f"🎉 <b>It's a Match!</b>\nYou and {cand_mention} liked each other! Head to <b>💌 Matches</b> to chat!", parse_mode="HTML")
            try:
                await bot.send_message(candidate_id, f"🎉 <b>It's a Match!</b>\nYou and {swiper_mention} liked each other! Check your <b>💌 Matches</b> tab!", parse_mode="HTML")
            except TelegramForbiddenError:
                await db_execute("UPDATE users SET is_approved = 0 WHERE telegram_id = ?", candidate_id)
            except Exception:
                pass
        else:
            try:
                await bot.send_message(
                    candidate_id,
                    "👀 <b>Someone nearby just liked your profile!</b>\n"
                    "Open <b>🔍 Discover (Proximity)</b> to find out who!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await cmd_discover(callback.message)
    await callback.answer()

# ---------------------------------------------------------
# Anonymous Chat Roulette Engine
# ---------------------------------------------------------
@dp.message(F.text.in_(["⚡ Random Chat Roulette", "/roulette"]))
async def cmd_chat_roulette_menu(message: types.Message):
    user_id = message.from_user.id
    active = await db_query("SELECT * FROM active_chats WHERE user_id = ?", user_id)
    if active:
        await message.answer("⚠️ You are already in an active anonymous chat! Type /end or tap ⏹️ End Chat to leave.", reply_markup=anon_chat_keyboard())
        return

    roulette_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌐 Global Anyone (Fastest)", callback_data="join_queue_anyone"),
            InlineKeyboardButton(text="📍 Same State/Region", callback_data="join_queue_state")
        ],
        [
            InlineKeyboardButton(text="👩 Chat with Female", callback_data="join_queue_Female"),
            InlineKeyboardButton(text="👨 Chat with Male", callback_data="join_queue_Male")
        ]
    ])
    await message.answer(
        "🎭 <b>Anonymous Chat Roulette</b>\n\n"
        "• All messages, photos & audio are relayed with zero identity leaks.\n"
        "• Keep it friendly! Karma points (+5 / -10) follow each chat.\n"
        "• Select your preferred stream below:",
        parse_mode="HTML",
        reply_markup=roulette_kb
    )

@dp.callback_query(F.data.startswith("join_queue_"))
async def cb_join_queue(callback: types.CallbackQuery):
    mode = callback.data.replace("join_queue_", "")
    user_id = callback.from_user.id
    u_rows = await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id)
    if not u_rows or not u_rows[0]['is_approved']:
        await callback.answer("Your profile must be approved to join anonymous chats.", show_alert=True)
        return

    me = u_rows[0]
    my_gender = me['gender']
    my_state = me.get('state', '')
    my_country = me.get('country', '')

    await db_execute("DELETE FROM roulette_queue WHERE user_id = ?", user_id)

    partner = None
    if mode == "anyone":
        candidates = await db_query("""
            SELECT * FROM roulette_queue 
            WHERE user_id != ? 
              AND (mode = 'anyone' OR mode = ?)
            ORDER BY joined_at ASC LIMIT 1
        """, user_id, my_gender)
        if candidates:
            partner = candidates[0]
    elif mode == "state":
        candidates = await db_query("""
            SELECT * FROM roulette_queue 
            WHERE user_id != ? 
              AND LOWER(state) = LOWER(?)
              AND (mode = 'state' OR mode = 'anyone')
            ORDER BY joined_at ASC LIMIT 1
        """, user_id, my_state)
        if candidates:
            partner = candidates[0]
    else:  # Female or Male
        candidates = await db_query("""
            SELECT * FROM roulette_queue 
            WHERE user_id != ? 
              AND gender = ?
              AND (mode = 'anyone' OR mode = ?)
            ORDER BY joined_at ASC LIMIT 1
        """, user_id, mode, my_gender)
        if candidates:
            partner = candidates[0]

    if partner:
        partner_id = partner['user_id']
        await db_execute("DELETE FROM roulette_queue WHERE user_id IN (?, ?)", user_id, partner_id)

        await db_execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", user_id, partner_id)
        await db_execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", partner_id, user_id)
        await db_execute("UPDATE users SET total_chats = total_chats + 1 WHERE telegram_id IN (?, ?)", user_id, partner_id)

        msg = (
            "✨ <b>Connected with a partner!</b>\n\n"
            "• Messages, voice notes, photos & stickers are relayed anonymously.\n"
            "• Tap <b>📍 Share Proximity</b> to show distance in km without giving away your exact location.\n"
            "• Tap <b>⏹️ End Chat</b> or type /end when finished."
        )
        await bot.send_message(user_id, msg, parse_mode="HTML", reply_markup=anon_chat_keyboard())
        await bot.send_message(partner_id, msg, parse_mode="HTML", reply_markup=anon_chat_keyboard())
        await callback.answer()
        return

    await db_execute("""
        INSERT INTO roulette_queue (user_id, gender, target_gender, country, state, mode) 
        VALUES (?, ?, ?, ?, ?, ?)
    """, user_id, my_gender, me['target_gender'], my_country, my_state, mode)

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel Search", callback_data="leave_anon_queue")]
    ])
    await callback.message.edit_text(
        f"🔍 <b>Searching for a partner ({mode.title()})...</b>\n"
        "You'll be connected automatically as soon as someone matches your stream.",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await callback.answer()

@dp.callback_query(F.data == "leave_anon_queue")
async def cb_leave_queue(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await db_execute("DELETE FROM roulette_queue WHERE user_id = ?", user_id)
    await callback.message.edit_text("Search cancelled.", reply_markup=None)
    await callback.message.answer("Returned to lobby.", reply_markup=main_menu_keyboard())
    await callback.answer()

async def end_anonymous_session(user_id: int, send_notice: bool = True):
    active = await db_query("SELECT partner_id FROM active_chats WHERE user_id = ?", user_id)
    if not active:
        return None
    partner_id = active[0]['partner_id']
    await db_execute("DELETE FROM active_chats WHERE user_id IN (?, ?)", user_id, partner_id)

    rating_kb = lambda pid: InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍 Good Vibes (+5 Karma)", callback_data=f"rate_{pid}_up"),
            InlineKeyboardButton(text="👎 Inappropriate (-10 Karma)", callback_data=f"rate_{pid}_down")
        ],
        [InlineKeyboardButton(text="🚨 Report Stranger", callback_data=f"report_card_{pid}")]
    ])

    if send_notice:
        try:
            await bot.send_message(user_id, "⏹️ <b>Chat ended.</b> Please rate your conversation:", parse_mode="HTML", reply_markup=rating_kb(partner_id))
            await bot.send_message(user_id, "Returned to main menu.", reply_markup=main_menu_keyboard())
        except Exception:
            pass
        try:
            await bot.send_message(partner_id, "⏹️ <b>Your partner left the chat.</b> Please rate your conversation:", parse_mode="HTML", reply_markup=rating_kb(user_id))
            await bot.send_message(partner_id, "Returned to main menu.", reply_markup=main_menu_keyboard())
        except Exception:
            pass
    return partner_id

@dp.message(F.text.in_(["⏹️ End Chat", "/end", "/stop"]))
async def cmd_end_chat(message: types.Message):
    ended = await end_anonymous_session(message.from_user.id)
    if not ended:
        await message.answer("You are not currently in an active anonymous chat.", reply_markup=main_menu_keyboard())

@dp.message(F.text.in_(["⏭️ Next Person", "/next"]))
async def cmd_next_person(message: types.Message):
    await end_anonymous_session(message.from_user.id)
    u_rows = await db_query("SELECT * FROM users WHERE telegram_id = ?", message.from_user.id)
    if u_rows:
        me = u_rows[0]
        await db_execute("DELETE FROM roulette_queue WHERE user_id = ?", message.from_user.id)
        await db_execute("""
            INSERT INTO roulette_queue (user_id, gender, target_gender, country, state, mode) 
            VALUES (?, ?, ?, ?, ?, 'anyone')
        """, message.from_user.id, me['gender'], me['target_gender'], me.get('country', ''), me.get('state', ''))
    await message.answer("🔍 Looking for a new partner...", reply_markup=ReplyKeyboardRemove())

@dp.message(F.text == "📍 Share Proximity")
async def cmd_share_proximity(message: types.Message):
    user_id = message.from_user.id
    active = await db_query("SELECT partner_id FROM active_chats WHERE user_id = ?", user_id)
    if not active:
        await message.answer("You are not in an active anonymous chat.", reply_markup=main_menu_keyboard())
        return

    partner_id = active[0]['partner_id']
    me = (await db_query("SELECT * FROM users WHERE telegram_id = ?", user_id))[0]
    them = (await db_query("SELECT * FROM users WHERE telegram_id = ?", partner_id))[0]

    dist_km = calculate_distance(me['latitude'], me['longitude'], them['latitude'], them['longitude'])
    if dist_km is not None:
        prox_msg = f"📍 <b>Proximity Alert:</b> You and your partner are approximately <b>{dist_km} km</b> apart!"
    else:
        them_loc = f"{them.get('state', '')}, {them.get('country', '')}".strip(", ")
        prox_msg = f"📍 <b>Proximity Alert:</b> Partner is registered in <b>{them_loc}</b>."

    await message.answer(prox_msg, parse_mode="HTML")
    try:
        await bot.send_message(partner_id, prox_msg, parse_mode="HTML")
    except Exception:
        pass

@dp.message(F.text == "🚨 Report Stranger")
async def cmd_report_stranger(message: types.Message):
    user_id = message.from_user.id
    active = await db_query("SELECT partner_id FROM active_chats WHERE user_id = ?", user_id)
    if not active:
        await message.answer("You are not in an active anonymous chat.", reply_markup=main_menu_keyboard())
        return

    partner_id = active[0]['partner_id']
    reasons_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Bot / Catfish", callback_data=f"do_report_{partner_id}_Bot")],
        [InlineKeyboardButton(text="🔞 Abusive / Explicit", callback_data=f"do_report_{partner_id}_Abusive")],
        [InlineKeyboardButton(text="😡 Harassment / Threat", callback_data=f"do_report_{partner_id}_Harassment")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_report")]
    ])
    await message.reply("🚨 <b>Select reason to report this stranger:</b>", parse_mode="HTML", reply_markup=reasons_kb)

@dp.callback_query(F.data.startswith("rate_"))
async def cb_rate_user(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    partner_id = int(parts[1])
    verdict = parts[2]
    rater_id = callback.from_user.id

    delta = 5 if verdict == "up" else -10
    await db_execute("UPDATE users SET karma_score = karma_score + ? WHERE telegram_id = ?", delta, partner_id)
    await db_execute("INSERT INTO chat_ratings (rater_id, rated_id, rating) VALUES (?, ?, ?)", rater_id, partner_id, 1 if verdict == "up" else -1)
    await callback.message.edit_text("⭐ Rating submitted. Thank you for keeping the community safe!")
    await callback.answer()

# ---------------------------------------------------------
# Feedback & Reporting
# ---------------------------------------------------------
@dp.message(F.text.in_(["/feedback", "💬 Feedback"]))
async def cmd_feedback(message: types.Message, state: FSMContext):
    await state.set_state(FeedbackStates.waiting_for_feedback)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_feedback")]
    ])
    await message.answer(
        "📝 <b>We value your feedback!</b>\n\n"
        "Tell us what you love, suggest a feature, or report an issue below:",
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
# Anonymous Chat Relay Handler (STRICTLY CONSTRAINED)
# ---------------------------------------------------------
# Placed at the very bottom: Only triggers if the message is NOT a command,
# the user is NOT in an FSM state, and they have an active row in active_chats!
@dp.message(F.chat.type == "private", ~F.text.startswith("/"))
async def relay_anonymous_chat(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    user_id = message.from_user.id
    active = await db_query("SELECT partner_id FROM active_chats WHERE user_id = ?", user_id)
    if not active:
        return

    partner_id = active[0]['partner_id']
    try:
        if message.text:
            await bot.send_message(partner_id, message.text)
        elif message.photo:
            await bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption or "")
        elif message.voice:
            await bot.send_voice(partner_id, message.voice.file_id)
        elif message.video_note:
            await bot.send_video_note(partner_id, message.video_note.file_id)
        elif message.sticker:
            await bot.send_sticker(partner_id, message.sticker.file_id)
    except TelegramForbiddenError:
        await end_anonymous_session(user_id)

# ---------------------------------------------------------
# Embedded Web Server (Render Port Binding & Health Check)
# ---------------------------------------------------------
async def handle_health(request):
    return web.Response(text="Soulmate Engine is healthy!", status=200)

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

    admin_commands = [
        BotCommand(command="admin", description="🛠️ Admin Control Center & Help"),
        BotCommand(command="admin_stats", description="📊 System & Database Metrics"),
        BotCommand(command="remind_incomplete", description="🚪 Nudge Registration Drop-offs"),
        BotCommand(command="remind_unverified", description="⏳ Nudge Pending Approvals"),
        BotCommand(command="broadcast", description="📢 Global Announcement"),
    ]
    try:
        await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    except Exception as e:
        logger.warning(f"Could not register admin command menu: {e}")

    logger.info("Bot is fully operational with prioritized command routing and isolated relay...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
