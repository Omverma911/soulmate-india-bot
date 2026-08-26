import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Optional
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# Optional database driver imports
try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8974109640:AAHNuuHALqJQFteuwMlaXiPjzYEjzzUDO8Q")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8925689319"))
DATABASE_URL = os.environ.get("postgresql://neondb_owner:npg_Mu8WwZIelR4G@ep-muddy-sound-ayc0orm3-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require", "")
DAILY_SWIPE_LIMIT = 50

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

pg_pool: Optional[asyncpg.Pool] = None

# --- LOCATIONS DATA ---
INDIA_LOCATIONS = {
    "Delhi NCR": ["New Delhi", "Noida", "Gurugram", "Faridabad", "Ghaziabad", "Other"],
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik", "Thane", "Navi Mumbai", "Other"],
    "Karnataka": ["Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Belagavi", "Other"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Other"],
    "Telangana": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Other"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra", "Prayagraj", "Meerut", "Other"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar", "Other"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur", "Siliguri", "Asansol", "Other"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur", "Kota", "Bikaner", "Other"],
    "Madhya Pradesh": ["Indore", "Bhopal", "Gwalior", "Jabalpur", "Ujjain", "Other"],
    "Bihar": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Darbhanga", "Other"],
    "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar", "Other"],
    "Kerala": ["Kochi", "Thiruvananthapuram", "Kozhikode", "Thrissur", "Other"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Mohali", "Other"],
    "Haryana": ["Gurugram", "Faridabad", "Panipat", "Ambala", "Karnal", "Other"],
    "Chandigarh": ["Chandigarh", "Panchkula", "Mohali", "Other"],
    "Goa": ["Panaji", "Margao", "Vasco da Gama", "Mapusa", "Other"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela", "Puri", "Other"],
    "Assam & NE": ["Guwahati", "Shillong", "Silchar", "Dibrugarh", "Imphal", "Other"],
    "Uttarakhand & HP": ["Dehradun", "Rishikesh", "Shimla", "Dharamshala", "Other"],
    "Jammu & Kashmir": ["Srinagar", "Jammu", "Other"],
    "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur", "Tirupati", "Other"]
}

GOAL_OPTIONS = {
    "💍 Long-Term / True Love": "Long-Term",
    "🥂 Casual Dating / Hookups": "Casual",
    "☕ Dates & Explore": "Open",
    "🤝 New Friends": "Friends"
}

GOAL_LABELS = {
    "Long-Term": "💍 Long-Term / True Love",
    "Casual": "🥂 Casual Dating / Hookups",
    "Open": "☕ Dates & Explore",
    "Friends": "🤝 New Friends"
}

ICEBREAKER_PROMPTS = [
    "My ideal Sunday looks like...",
    "A non-negotiable for me in a partner is...",
    "The quickest way to my heart is...",
    "Two truths and a lie about me..."
]

GESTURES = [
    "✌️ Hold up a PEACE SIGN (2 fingers)",
    "👍 Hold up a THUMBS UP",
    "☝️ Point ONE FINGER upwards",
    "🖐️ Hold up an OPEN PALM (5 fingers)"
]

# --- DATABASE WRAPPER ---
async def db_execute(query: str, *params):
    if pg_pool:
        parts = query.split("?")
        pg_query = parts[0]
        for i in range(1, len(parts)):
            pg_query += f"${i}" + parts[i]
        async with pg_pool.acquire() as conn:
            return await conn.execute(pg_query, *params)
    else:
        async with aiosqlite.connect("dating_bot.db") as db:
            await db.execute(query, params)
            await db.commit()

async def db_fetchrow(query: str, *params):
    if pg_pool:
        parts = query.split("?")
        pg_query = parts[0]
        for i in range(1, len(parts)):
            pg_query += f"${i}" + parts[i]
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(pg_query, *params)
            return dict(row) if row else None
    else:
        async with aiosqlite.connect("dating_bot.db") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return dict(row) if row else None

async def db_fetchall(query: str, *params):
    if pg_pool:
        parts = query.split("?")
        pg_query = parts[0]
        for i in range(1, len(parts)):
            pg_query += f"${i}" + parts[i]
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(pg_query, *params)
            return [dict(r) for r in rows]
    else:
        async with aiosqlite.connect("dating_bot.db") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def db_fetchval(query: str, *params):
    if pg_pool:
        parts = query.split("?")
        pg_query = parts[0]
        for i in range(1, len(parts)):
            pg_query += f"${i}" + parts[i]
        async with pg_pool.acquire() as conn:
            return await conn.fetchval(pg_query, *params)
    else:
        async with aiosqlite.connect("dating_bot.db") as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            return row[0] if row else 0


async def init_db():
    global pg_pool
    if DATABASE_URL and asyncpg:
        clean_url = DATABASE_URL
        if clean_url.startswith("postgres://"):
            clean_url = clean_url.replace("postgres://", "postgresql://", 1)
        
        logging.info("Connecting to Neon PostgreSQL...")
        pg_pool = await asyncpg.create_pool(clean_url, max_size=10, min_size=1)

        async with pg_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    username TEXT DEFAULT '',
                    phone_number TEXT DEFAULT '',
                    name TEXT DEFAULT '',
                    age INTEGER DEFAULT 18,
                    gender TEXT DEFAULT '',
                    target_gender TEXT DEFAULT 'Everyone',
                    dating_goal TEXT DEFAULT 'Long-Term',
                    intent_filter TEXT DEFAULT 'flexible',
                    state TEXT DEFAULT 'India',
                    city TEXT DEFAULT 'Other',
                    photo_file_id TEXT DEFAULT '',
                    selfie_file_id TEXT DEFAULT '',
                    bio TEXT DEFAULT '',
                    icebreaker_question TEXT DEFAULT '',
                    icebreaker_answer TEXT DEFAULT '',
                    reports_count INTEGER DEFAULT 0,
                    superlikes_balance INTEGER DEFAULT 1,
                    boosts_balance INTEGER DEFAULT 1,
                    last_superlike_date TEXT DEFAULT '',
                    daily_swipes_count INTEGER DEFAULT 0,
                    last_swipe_date TEXT DEFAULT '',
                    boost_expires_at TEXT DEFAULT '',
                    referred_by BIGINT DEFAULT 0,
                    search_scope TEXT DEFAULT 'same_city',
                    is_approved INTEGER DEFAULT 0,
                    is_verified INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS swipes (
                    swiper_id BIGINT,
                    target_id BIGINT,
                    action TEXT,
                    PRIMARY KEY (swiper_id, target_id)
                );
                CREATE TABLE IF NOT EXISTS matches (
                    user1_id BIGINT,
                    user2_id BIGINT,
                    user1_shared INTEGER DEFAULT 0,
                    user2_shared INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT '',
                    PRIMARY KEY (user1_id, user2_id)
                );
                UPDATE users SET boosts_balance = 1 WHERE boosts_balance IS NULL OR boosts_balance = 0;
                UPDATE users SET superlikes_balance = 1 WHERE superlikes_balance IS NULL;
                UPDATE users SET boost_expires_at = '' WHERE boost_expires_at IS NULL;
            """)
        logging.info("Connected to Neon PostgreSQL and initialized schema.")
    else:
        logging.info("Using local SQLite storage (dating_bot.db)...")
        async with aiosqlite.connect("dating_bot.db") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    phone_number TEXT DEFAULT '',
                    name TEXT DEFAULT '',
                    age INTEGER DEFAULT 18,
                    gender TEXT DEFAULT '',
                    target_gender TEXT DEFAULT 'Everyone',
                    dating_goal TEXT DEFAULT 'Long-Term',
                    intent_filter TEXT DEFAULT 'flexible',
                    state TEXT DEFAULT 'India',
                    city TEXT DEFAULT 'Other',
                    photo_file_id TEXT DEFAULT '',
                    selfie_file_id TEXT DEFAULT '',
                    bio TEXT DEFAULT '',
                    icebreaker_question TEXT DEFAULT '',
                    icebreaker_answer TEXT DEFAULT '',
                    reports_count INTEGER DEFAULT 0,
                    superlikes_balance INTEGER DEFAULT 1,
                    boosts_balance INTEGER DEFAULT 1,
                    last_superlike_date TEXT DEFAULT '',
                    daily_swipes_count INTEGER DEFAULT 0,
                    last_swipe_date TEXT DEFAULT '',
                    boost_expires_at TEXT DEFAULT '',
                    referred_by INTEGER DEFAULT 0,
                    search_scope TEXT DEFAULT 'same_city',
                    is_approved INTEGER DEFAULT 0,
                    is_verified INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS swipes (
                    swiper_id INTEGER,
                    target_id INTEGER,
                    action TEXT,
                    PRIMARY KEY (swiper_id, target_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    user1_id INTEGER,
                    user2_id INTEGER,
                    user1_shared INTEGER DEFAULT 0,
                    user2_shared INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT '',
                    PRIMARY KEY (user1_id, user2_id)
                )
            """)

            columns_to_add = [
                "phone_number TEXT DEFAULT ''",
                "dating_goal TEXT DEFAULT 'Long-Term'",
                "intent_filter TEXT DEFAULT 'flexible'",
                "search_scope TEXT DEFAULT 'same_city'",
                "state TEXT DEFAULT 'India'",
                "city TEXT DEFAULT 'Other'",
                "reports_count INTEGER DEFAULT 0",
                "superlikes_balance INTEGER DEFAULT 1",
                "boosts_balance INTEGER DEFAULT 1",
                "last_superlike_date TEXT DEFAULT ''",
                "daily_swipes_count INTEGER DEFAULT 0",
                "last_swipe_date TEXT DEFAULT ''",
                "boost_expires_at TEXT DEFAULT ''",
                "referred_by INTEGER DEFAULT 0",
                "is_approved INTEGER DEFAULT 0",
                "is_verified INTEGER DEFAULT 0",
                "is_banned INTEGER DEFAULT 0",
                "selfie_file_id TEXT DEFAULT ''",
                "icebreaker_question TEXT DEFAULT ''",
                "icebreaker_answer TEXT DEFAULT ''"
            ]
            for col in columns_to_add:
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col}")
                except Exception:
                    pass
            
            try:
                await db.execute("UPDATE users SET boosts_balance = 1 WHERE boosts_balance IS NULL OR boosts_balance = 0")
                await db.execute("UPDATE users SET superlikes_balance = 1 WHERE superlikes_balance IS NULL")
                await db.execute("UPDATE users SET boost_expires_at = '' WHERE boost_expires_at IS NULL")
            except Exception:
                pass
                
            await db.commit()


# --- UI HELPERS ---
async def get_main_menu(user_id: int):
    count = await db_fetchval("""
        SELECT COUNT(*) FROM swipes s
        WHERE s.target_id = ? AND s.action = 'like'
          AND s.swiper_id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = ?)
    """, user_id, user_id)

    likes_btn_text = f"💌 Likes Received ({count})" if count > 0 else "💌 Likes Received"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Discover"), KeyboardButton(text=likes_btn_text)],
            [KeyboardButton(text="👥 My Matches"), KeyboardButton(text="👤 My Profile")],
            [KeyboardButton(text="🎁 Invite & Boost"), KeyboardButton(text="📜 My History")],
            [KeyboardButton(text="⚙️ Preferences")]
        ],
        resize_keyboard=True
    )

def get_states_keyboard(prefix="state_"):
    buttons = []
    row = []
    for state in INDIA_LOCATIONS.keys():
        row.append(InlineKeyboardButton(text=state, callback_data=f"{prefix}{state}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cities_keyboard(state_name, prefix="city_"):
    cities = INDIA_LOCATIONS.get(state_name, ["Other"])
    buttons = []
    row = []
    for city in cities:
        row.append(InlineKeyboardButton(text=city, callback_data=f"{prefix}{city}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- FSM STATES ---
class Registration(StatesGroup):
    name = State()
    phone = State()
    age = State()
    gender = State()
    target_gender = State()
    dating_goal = State()
    state_select = State()
    city_select = State()
    photo = State()
    selfie_verification = State()
    icebreaker_choice = State()
    icebreaker_text = State()
    bio = State()

class EditProfile(StatesGroup):
    edit_bio = State()
    edit_photo = State()
    edit_state = State()
    edit_city = State()

class AdminStates(StatesGroup):
    broadcast_message = State()


# --- DISCOVERY LOGIC ---
async def show_next_candidate(chat_id: int, user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()

    current_user = await db_fetchrow("SELECT * FROM users WHERE telegram_id = ?", user_id)

    if not current_user:
        await bot.send_message(chat_id, "Please set up your profile first using /start.")
        return

    if current_user.get("is_banned", 0) == 1:
        await bot.send_message(chat_id, "🚫 <b>Your account has been suspended for violating community guidelines.</b>", parse_mode="HTML")
        return

    if current_user.get("is_approved", 0) == 0:
        await bot.send_message(
            chat_id,
            "⏳ <b>Your profile is pending admin manual verification.</b>\n"
            "You will receive an alert as soon as our moderators review your selfie gesture!",
            parse_mode="HTML"
        )
        return

    last_date = current_user.get("last_swipe_date", "") or ""
    swipes_used = current_user.get("daily_swipes_count", 0) if last_date == today else 0

    if swipes_used >= DAILY_SWIPE_LIMIT and current_user["telegram_id"] != ADMIN_ID:
        limit_msg = (
            f"🛑 <b>Daily Swipe Limit Reached ({DAILY_SWIPE_LIMIT}/{DAILY_SWIPE_LIMIT})</b>\n\n"
            f"Your limit resets at midnight! Want more swipes and free Super Likes?\n"
            f"Tap <b>🎁 Invite & Boost</b> to earn rewards!"
        )
        menu = await get_main_menu(user_id)
        await bot.send_message(chat_id, limit_msg, reply_markup=menu, parse_mode="HTML")
        return

    search_scope = current_user.get("search_scope", "same_city") or "same_city"
    intent_filter = current_user.get("intent_filter", "flexible") or "flexible"
    user_goal = current_user.get("dating_goal", "Long-Term") or "Long-Term"

    query = """
        SELECT *, (CASE WHEN boost_expires_at > ? THEN 1 ELSE 0 END) AS is_boosted
        FROM users 
        WHERE telegram_id != ?
          AND reports_count < 3
          AND is_banned = 0
          AND is_approved = 1
          AND telegram_id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = ?)
    """
    params = [now_iso, user_id, user_id]

    if current_user["target_gender"] != "Everyone":
        query += " AND gender = ?"
        params.append(current_user["target_gender"])

    if intent_filter == "strict":
        if user_goal == "Long-Term":
            query += " AND dating_goal IN ('Long-Term', 'Open')"
        elif user_goal == "Casual":
            query += " AND dating_goal IN ('Casual', 'Open')"
        elif user_goal == "Friends":
            query += " AND dating_goal IN ('Friends', 'Open')"

    if search_scope == "same_city":
        query += " AND city = ? ORDER BY is_boosted DESC, RANDOM() LIMIT 1"
        params.append(current_user["city"])
    else:
        query += " ORDER BY is_boosted DESC, (city = ?) DESC, RANDOM() LIMIT 1"
        params.append(current_user["city"])

    candidate = await db_fetchrow(query, *params)

    if not candidate:
        scope_msg = (
            f"No more matching profiles in <b>{current_user.get('city', 'Other')}</b> right now.\n"
            f"Tip: Try switching to <b>🇮🇳 All India</b> or <b>🌐 All Goals</b> in <b>⚙️ Preferences</b>!"
            if search_scope == "same_city"
            else "You're all caught up for now!\nCheck back soon or explore <b>💌 Likes Received</b>."
        )

        no_profile_text = f"✨ <b>You're all caught up!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{scope_msg}"
        menu = await get_main_menu(user_id)
        await bot.send_message(chat_id, no_profile_text, reply_markup=menu, parse_mode="HTML")
        return

    st_str = candidate.get("state", "India") or "India"
    ct_str = candidate.get("city", "Other") or "Other"
    cand_goal_label = GOAL_LABELS.get(candidate.get("dating_goal", "Open"), "☕ Dates & Explore")
    v_badge = " ✅ [Verified]" if candidate.get("is_verified", 0) == 1 else ""
    boost_badge = " 🚀 [Spotlight #1]" if candidate.get("is_boosted", 0) == 1 else ""

    icebreaker_section = ""
    if candidate.get("icebreaker_question") and candidate.get("icebreaker_answer"):
        icebreaker_section = (
            f"\n💡 <i>{candidate['icebreaker_question']}</i>\n"
            f"👉 <b>{candidate['icebreaker_answer']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )

    card_text = (
        f"👤 <b>{candidate['name'].upper()}</b>{v_badge}{boost_badge}, {candidate['age']}\n"
        f"📍 <i>{ct_str}, {st_str}</i>\n"
        f"🎯 <b>Goal:</b> {cand_goal_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❝ {candidate['bio']} ❞\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
        f"{icebreaker_section}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✕ Pass", callback_data=f"swipe_pass_{candidate['telegram_id']}"),
                InlineKeyboardButton(text="⭐ Super Like", callback_data=f"swipe_super_{candidate['telegram_id']}"),
                InlineKeyboardButton(text="♥ Like", callback_data=f"swipe_like_{candidate['telegram_id']}")
            ],
            [
                InlineKeyboardButton(text="🚩 Report Profile", callback_data=f"report_{candidate['telegram_id']}")
            ]
        ]
    )

    await bot.send_photo(
        chat_id=chat_id,
        photo=candidate["photo_file_id"],
        caption=card_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# --- ONBOARDING FLOW ---
@dp.message(CommandStart(deep_link=True))
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject = None):
    await state.clear()
    uid = message.from_user.id

    referrer_id = 0
    if command and command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args.replace("ref_", ""))
            if referrer_id == uid:
                referrer_id = 0
        except Exception:
            referrer_id = 0

    user = await db_fetchrow("SELECT * FROM users WHERE telegram_id = ?", uid)

    if user:
        if user.get("is_banned", 0) == 1:
            await message.answer("🚫 <b>Your account is suspended.</b>", parse_mode="HTML")
            return
        
        status_note = ""
        if user.get("is_approved", 0) == 0:
            status_note = "\n\n⏳ <i>Your profile is currently waiting for admin approval.</i>"

        welcome_back_text = (
            f"<b>Welcome back, {user['name']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Explore verified matches, review likes, swipe history, or invite friends.{status_note}"
        )
        menu = await get_main_menu(uid)
        await message.answer(welcome_back_text, reply_markup=menu, parse_mode="HTML")
    else:
        await state.update_data(referred_by=referrer_id)
        intro_text = (
            f"✨ <b>Welcome to Soulmate India</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"A curated, private space for authentic connections.\n\n"
            f"<b>What is your first name?</b>"
        )
        await message.answer(intro_text, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
        await state.set_state(Registration.name)


@dp.message(Registration.name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip().title()
    await state.update_data(name=name)

    contact_btn = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Share Mobile Number to Verify", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        f"Pleasure to meet you, <b>{name}</b>.\n\nPlease share your mobile number to verify your profile:",
        reply_markup=contact_btn,
        parse_mode="HTML"
    )
    await state.set_state(Registration.phone)


@dp.message(Registration.phone, F.contact)
async def process_phone(message: types.Message, state: FSMContext):
    phone_number = message.contact.phone_number
    await state.update_data(phone_number=phone_number)
    await message.answer("How old are you? (Must be 18+)", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Registration.age)


@dp.message(Registration.phone)
async def process_phone_invalid(message: types.Message):
    contact_btn = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Share Mobile Number to Verify", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Please tap the button below to share your verified mobile number:", reply_markup=contact_btn)


@dp.message(Registration.age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 18 or int(message.text) > 99:
        await message.answer("⚠️ Please enter a valid numerical age between 18 and 99.")
        return

    await state.update_data(age=int(message.text))
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Man"), KeyboardButton(text="Woman")],
            [KeyboardButton(text="Non-Binary / Other")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("<b>Select your gender:</b>", reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(Registration.gender)


@dp.message(Registration.gender)
async def process_gender(message: types.Message, state: FSMContext):
    gender_map = {"Man": "Male", "Woman": "Female", "Non-Binary / Other": "Other"}
    selected = gender_map.get(message.text, message.text)
    
    if selected not in ["Male", "Female", "Other"]:
        await message.answer("Please select an option using the keyboard.")
        return

    await state.update_data(gender=selected)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Men"), KeyboardButton(text="Women")],
            [KeyboardButton(text="Everyone")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("<b>Who are you interested in meeting?</b>", reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(Registration.target_gender)


@dp.message(Registration.target_gender)
async def process_target_gender(message: types.Message, state: FSMContext):
    target_map = {"Men": "Male", "Women": "Female", "Everyone": "Everyone"}
    selected = target_map.get(message.text, message.text)

    if selected not in ["Male", "Female", "Everyone"]:
        await message.answer("Please select an option using the keyboard.")
        return

    await state.update_data(target_gender=selected)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💍 Long-Term / True Love"), KeyboardButton(text="🥂 Casual Dating / Hookups")],
            [KeyboardButton(text="☕ Dates & Explore"), KeyboardButton(text="🤝 New Friends")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("🎯 <b>What are you looking for on this platform?</b>", reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(Registration.dating_goal)


@dp.message(Registration.dating_goal)
async def process_dating_goal(message: types.Message, state: FSMContext):
    goal_key = GOAL_OPTIONS.get(message.text, "Open")
    await state.update_data(dating_goal=goal_key)

    await message.answer("📍 <b>Select your State / Region:</b>", reply_markup=get_states_keyboard(), parse_mode="HTML")
    await state.set_state(Registration.state_select)


@dp.callback_query(Registration.state_select, F.data.startswith("state_"))
async def process_state_callback(callback: types.CallbackQuery, state: FSMContext):
    selected_state = callback.data.replace("state_", "")
    await state.update_data(state=selected_state)
    
    await callback.message.edit_text(
        f"📍 Region: <b>{selected_state}</b>\n\n<b>Select your city:</b>",
        reply_markup=get_cities_keyboard(selected_state),
        parse_mode="HTML"
    )
    await state.set_state(Registration.city_select)
    try:
        await callback.answer()
    except Exception:
        pass


@dp.callback_query(Registration.city_select, F.data.startswith("city_"))
async def process_city_callback(callback: types.CallbackQuery, state: FSMContext):
    selected_city = callback.data.replace("city_", "")
    await state.update_data(city=selected_city)
    
    await callback.message.edit_text(f"📍 Location set: <b>{selected_city}</b>", parse_mode="HTML")
    await callback.message.answer(
        "📸 <b>Upload your MAIN portrait photo:</b>\n<i>(This will be visible on your public card)</i>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.photo)
    try:
        await callback.answer()
    except Exception:
        pass


@dp.message(Registration.photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_id)

    chosen_gesture = random.choice(GESTURES)
    await state.update_data(required_gesture=chosen_gesture)

    gesture_text = (
        f"🛡️ <b>ANTI-FAKE PROFILE VERIFICATION</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"To verify you are real and keep bots out, take a quick selfie holding this pose:\n\n"
        f"👉 <b>{chosen_gesture}</b>\n\n"
        f"<i>Note: This selfie is strictly for admin moderation and will NEVER be shown publicly.</i>"
    )
    await message.answer(gesture_text, parse_mode="HTML")
    await state.set_state(Registration.selfie_verification)


@dp.message(Registration.selfie_verification, F.photo)
async def process_selfie_verification(message: types.Message, state: FSMContext):
    selfie_id = message.photo[-1].file_id
    await state.update_data(selfie_file_id=selfie_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"💬 {p[:28]}...", callback_data=f"ice_{i}")] for i, p in enumerate(ICEBREAKER_PROMPTS)]
    )
    await message.answer("💡 <b>Choose an Icebreaker Question to add to your profile:</b>", reply_markup=kb, parse_mode="HTML")
    await state.set_state(Registration.icebreaker_choice)


@dp.callback_query(Registration.icebreaker_choice, F.data.startswith("ice_"))
async def process_icebreaker_choice(callback: types.CallbackQuery, state: FSMContext):
    idx = int(callback.data.replace("ice_", ""))
    chosen_prompt = ICEBREAKER_PROMPTS[idx]
    await state.update_data(icebreaker_question=chosen_prompt)

    try:
        await callback.answer()
    except Exception:
        pass

    await callback.message.edit_text(f"💡 Prompt: <b>{chosen_prompt}</b>\n\n✍️ <b>Type your answer:</b>", parse_mode="HTML")
    await state.set_state(Registration.icebreaker_text)


@dp.message(Registration.icebreaker_text)
async def process_icebreaker_text(message: types.Message, state: FSMContext):
    await state.update_data(icebreaker_answer=message.text.strip())
    await message.answer("✍️ <b>Almost done! Introduce yourself with a short bio:</b>", parse_mode="HTML")
    await state.set_state(Registration.bio)


@dp.message(Registration.bio)
async def process_bio(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    bio = message.text.strip()
    username = message.from_user.username or ""
    uid = message.from_user.id
    name = user_data.get("name", "Member")
    age = user_data.get("age", 18)
    gender = user_data.get("gender", "Male")
    tgt_gender = user_data.get("target_gender", "Everyone")
    goal = user_data.get("dating_goal", "Long-Term")
    state_val = user_data.get("state", "India")
    city_val = user_data.get("city", "Other")
    photo_file_id = user_data.get("photo_file_id", "")
    selfie_file_id = user_data.get("selfie_file_id", "")
    phone = user_data.get("phone_number", "")
    gesture = user_data.get("required_gesture", "Gesture Pose")
    ice_q = user_data.get("icebreaker_question", "")
    ice_a = user_data.get("icebreaker_answer", "")
    ref_by = user_data.get("referred_by", 0)

    is_approved_val = 1 if uid == ADMIN_ID else 0
    is_verified_val = 1 if uid == ADMIN_ID else 0

    await db_execute("DELETE FROM users WHERE telegram_id = ?", uid)

    await db_execute("""
        INSERT INTO users 
        (telegram_id, username, phone_number, name, age, gender, target_gender, dating_goal, intent_filter, state, city, photo_file_id, selfie_file_id, bio, icebreaker_question, icebreaker_answer, reports_count, superlikes_balance, boosts_balance, last_superlike_date, daily_swipes_count, last_swipe_date, boost_expires_at, referred_by, search_scope, is_approved, is_verified, is_banned)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'flexible', ?, ?, ?, ?, ?, ?, ?, 0, 1, 1, '', 0, '', '', ?, 'same_city', ?, ?, 0)
    """, uid, username, phone, name, age, gender, tgt_gender, goal, state_val, city_val, photo_file_id, selfie_file_id, bio, ice_q, ice_a, ref_by, is_approved_val, is_verified_val)

    if ref_by and ref_by != uid:
        await db_execute("""
            UPDATE users 
            SET superlikes_balance = COALESCE(superlikes_balance, 0) + 3,
                boosts_balance = COALESCE(boosts_balance, 0) + 1
            WHERE telegram_id = ?
        """, ref_by)

        try:
            await bot.send_message(
                ref_by,
                f"🎁 <b>REFERRAL REWARD UNLOCKED!</b>\n\n"
                f"Your friend <b>{name}</b> just joined using your link!\n"
                f"• ⭐ <b>+3 Super Likes</b> added\n"
                f"• 🚀 <b>+1 Spotlight Boost (1-Hour Duration)</b> added to your inventory!\n\n"
                f"Tap <b>👤 My Profile</b> whenever you want to activate your 1-hour boost!",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await state.clear()
    menu = await get_main_menu(uid)

    if uid == ADMIN_ID:
        await message.answer("🎉 <b>Admin Profile setup complete!</b> (Auto-Verified & Active)", reply_markup=menu, parse_mode="HTML")
    else:
        await message.answer(
            "🎉 <b>Profile & Gesture Selfie submitted!</b>\n\n"
            "⏳ <i>Your profile is now under manual verification by our moderation team. You will be notified immediately once approved!</i>",
            reply_markup=menu,
            parse_mode="HTML"
        )

        if ADMIN_ID:
            admin_card = (
                f"🛡️ <b>NEW VERIFICATION REVIEW REQUEST</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Name:</b> {name}, {age} ({gender})\n"
                f"📞 <b>Phone:</b> <code>{phone}</code>\n"
                f"🆔 <b>Telegram ID:</b> <code>{uid}</code>\n"
                f"🔗 <b>Username:</b> @{username if username else 'None'}\n"
                f"📍 <b>Location:</b> {city_val}, {state_val}\n"
                f"🎯 <b>Goal:</b> {GOAL_LABELS.get(goal, goal)}\n"
                f"👉 <b>Assigned Pose:</b> <b>{gesture}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"❝ {bio} ❞\n"
                f"💡 <i>{ice_q}</i> -> <b>{ice_a}</b>"
            )
            admin_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Approve & Verify Badge", callback_data=f"adm_approve_{uid}"),
                        InlineKeyboardButton(text="🚫 Reject & Ban", callback_data=f"adm_reject_{uid}")
                    ]
                ]
            )
            try:
                await bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=photo_file_id,
                    caption=f"🖼️ <b>[1/2 MAIN PROFILE PHOTO]</b>\n{name}, {age} ({city_val})",
                    parse_mode="HTML"
                )
                await bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=selfie_file_id if selfie_file_id else photo_file_id,
                    caption=f"🤳 <b>[2/2 GESTURE SELFIE REVIEW]</b>\n{admin_card}",
                    reply_markup=admin_kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.warning(f"Failed to alert admin: {e}")


# --- 1-HOUR ON-DEMAND BOOST ACTIVATION ---
@dp.callback_query(F.data == "activate_boost_now")
async def activate_boost_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    now = datetime.now()
    now_iso = now.isoformat()

    user = await db_fetchrow("SELECT boosts_balance, boost_expires_at FROM users WHERE telegram_id = ?", user_id)

    if not user:
        try:
            await callback.answer("Profile not found.")
        except Exception:
            pass
        return

    # Check if already active
    boost_exp = user.get("boost_expires_at") or ""
    if boost_exp and boost_exp > now_iso:
        try:
            exp = datetime.fromisoformat(boost_exp)
            remaining_mins = max(1, int((exp - now).total_seconds() / 60))
            await callback.answer(f"🚀 Your Boost is already active! {remaining_mins} mins remaining.", show_alert=True)
        except Exception:
            await callback.answer("🚀 Your Boost is currently active!", show_alert=True)
        return

    # Check inventory balance safely
    raw_bal = user.get("boosts_balance")
    user_boosts = int(raw_bal) if raw_bal is not None else 0

    if user_boosts <= 0 and user_id != ADMIN_ID:
        try:
            await callback.answer("🚀 You have 0 Boosts in inventory! Tap '🎁 Invite & Boost' to earn more.", show_alert=True)
        except Exception:
            pass
        return

    # Set 1-hour expiration safely
    boost_until = (now + timedelta(hours=1)).isoformat()
    await db_execute("""
        UPDATE users 
        SET boosts_balance = (CASE WHEN COALESCE(boosts_balance, 0) > 0 THEN COALESCE(boosts_balance, 0) - 1 ELSE 0 END),
            boost_expires_at = ?
        WHERE telegram_id = ?
    """, boost_until, user_id)

    try:
        await callback.answer("🚀 1-Hour Spotlight Boost Activated! You are now #1 in your city stack.", show_alert=True)
    except Exception:
        pass

    await callback.message.answer(
        "🚀 <b>BOOST ACTIVATED FOR 1 HOUR!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "Your profile has been pushed to the top of the discovery deck for active members nearby. Good luck!",
        parse_mode="HTML"
    )


# --- VIRAL INVITE & REFERRALS ---
@dp.message(F.text == "🎁 Invite & Boost")
@dp.message(Command("invite"))
async def show_invite_menu(message: types.Message):
    uid = message.from_user.id
    bot_info = await bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"

    ref_count = await db_fetchval("SELECT COUNT(*) FROM users WHERE referred_by = ?", uid)
    u = await db_fetchrow("SELECT superlikes_balance, boosts_balance, boost_expires_at FROM users WHERE telegram_id = ?", uid)

    sl_bal = u.get("superlikes_balance") if (u and u.get("superlikes_balance") is not None) else 1
    boost_bal = u.get("boosts_balance") if (u and u.get("boosts_balance") is not None) else 1
    now_iso = datetime.now().isoformat()
    boost_exp = u.get("boost_expires_at", "") if u else ""
    boost_active = "Active 🚀" if boost_exp and boost_exp > now_iso else "Inactive"

    invite_msg = (
        f"🎁 <b>INVITE FRIENDS & GET REWARDED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Share your referral link with friends on WhatsApp, Instagram, or Telegram.\n\n"
        f"<b>YOUR REWARDS PER FRIEND INVITED:</b>\n"
        f"• ⭐ <b>+3 Free Super Likes</b>\n"
        f"• 🚀 <b>+1 Spotlight Boost (1-Hour Duration)</b>\n\n"
        f"📊 <b>Your Inventory & Stats:</b>\n"
        f"• 👥 Friends Invited: <b>{ref_count}</b>\n"
        f"• ⭐ Super Likes Balance: <b>{sl_bal}</b>\n"
        f"• 🚀 Available 1-Hour Boosts: <b>{boost_bal}</b>\n"
        f"• ⚡ Current Boost Status: <b>{boost_active}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Your Personal Invite Link:</b>\n"
        f"<code>{referral_link}</code>"
    )

    share_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Activate 1-Hour Boost Now", callback_data="activate_boost_now")
            ],
            [
                InlineKeyboardButton(
                    text="📲 Share Link on Telegram",
                    url=f"https://t.me/share/url?url={referral_link}&text=Join%20Soulmate%20India%20to%20find%20authentic%20matches!"
                )
            ]
        ]
    )

    await message.answer(invite_msg, reply_markup=share_kb, parse_mode="HTML")


# --- VIEW & MANAGE PROFILE ---
@dp.message(F.text == "👤 My Profile")
@dp.message(Command("profile"))
async def show_profile(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    now = datetime.now()
    now_iso = now.isoformat()

    user = await db_fetchrow("SELECT * FROM users WHERE telegram_id = ?", user_id)

    if not user:
        await message.answer("You haven't set up a profile yet. Send /start to begin.")
        return

    state_val = user.get("state", "India") or "India"
    city_val = user.get("city", "Other") or "Other"
    my_goal_label = GOAL_LABELS.get(user.get("dating_goal", "Long-Term"), "💍 Long-Term / True Love")

    total_likes = await db_fetchval("SELECT COUNT(*) FROM swipes WHERE target_id = ? AND action = 'like'", user_id)
    total_matches = await db_fetchval("SELECT COUNT(*) FROM matches WHERE user1_id = ? OR user2_id = ?", user_id, user_id)
    total_swiped = await db_fetchval("SELECT COUNT(*) FROM swipes WHERE swiper_id = ?", user_id)
    city_user_count = await db_fetchval("SELECT COUNT(*) FROM users WHERE city = ? AND is_approved = 1", city_val)
    total_user_count = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_approved = 1")

    status_tag = "✅ Approved & Verified" if user.get("is_verified", 0) == 1 else ("⏳ Under Review" if user.get("is_approved", 0) == 0 else "✓ Active")
    v_badge = " ✅ [Verified]" if user.get("is_verified", 0) == 1 else ""

    boost_exp = user.get("boost_expires_at") or ""
    raw_bal = user.get("boosts_balance")
    boost_stock = int(raw_bal) if raw_bal is not None else 0

    if boost_exp and boost_exp > now_iso:
        try:
            exp = datetime.fromisoformat(boost_exp)
            remaining_mins = max(1, int((exp - now).total_seconds() / 60))
            boost_status = f"🚀 ACTIVE ({remaining_mins}m left)"
        except Exception:
            boost_status = "🚀 ACTIVE"
    else:
        boost_status = f"Inactive ({boost_stock} in stock)"

    scope_display = "📍 Same City Only" if user.get("search_scope", "same_city") == "same_city" else "🇮🇳 All India (Nationwide)"
    sl_stock = int(user.get("superlikes_balance")) if user.get("superlikes_balance") is not None else 0

    icebreaker_text = ""
    if user.get("icebreaker_question") and user.get("icebreaker_answer"):
        icebreaker_text = f"\n💡 <i>{user['icebreaker_question']}</i>\n👉 <b>{user['icebreaker_answer']}</b>\n━━━━━━━━━━━━━━━━━━━━━━"

    profile_card = (
        f"👤 <b>{user['name'].upper()}</b>{v_badge}, {user['age']}\n"
        f"📍 <i>{city_val}, {state_val}</i>\n"
        f"🎯 <b>My Goal:</b> {my_goal_label}\n"
        f"🛡️ <b>Status:</b> {status_tag}\n"
        f"🚀 <b>Spotlight Boost:</b> {boost_status}\n"
        f"⭐ <b>Super Likes:</b> {sl_stock}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❝ {user['bio']} ❞\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
        f"{icebreaker_text}\n"
        f"📊 <b>YOUR STATS:</b>\n"
        f"• 💌 <b>Likes Received:</b> {total_likes}\n"
        f"• 👥 <b>Total Matches:</b> {total_matches}\n"
        f"• 🔥 <b>Profiles Explored:</b> {total_swiped}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>COMMUNITY:</b>\n"
        f"• 🏙️ <b>Verified in {city_val}:</b> {city_user_count}\n"
        f"• 🇮🇳 <b>Verified in India:</b> {total_user_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 <b>Location Scope:</b> {scope_display}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Activate 1-Hour Boost", callback_data="activate_boost_now"),
                InlineKeyboardButton(text="🎁 Get More Boosts", callback_data="open_invite_btn")
            ],
            [
                InlineKeyboardButton(text="✍️ Edit Bio", callback_data="edit_bio_btn"),
                InlineKeyboardButton(text="📸 Change Photo", callback_data="edit_photo_btn")
            ],
            [
                InlineKeyboardButton(text="📍 Update City", callback_data="edit_city_btn"),
                InlineKeyboardButton(text="🎯 Change Goal", callback_data="edit_goal_btn")
            ],
            [
                InlineKeyboardButton(text="🗑️ Delete Account", callback_data="confirm_delete_btn")
            ]
        ]
    )

    await message.answer_photo(
        photo=user["photo_file_id"],
        caption=profile_card,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# --- EDIT PROFILE & PREFERENCES ---
@dp.callback_query(F.data == "open_invite_btn")
async def open_invite_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    await show_invite_menu(callback.message)

@dp.callback_query(F.data == "edit_bio_btn")
async def edit_bio_start(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass
    await callback.message.answer("✍️ <b>Enter your new bio:</b>", parse_mode="HTML")
    await state.set_state(EditProfile.edit_bio)

@dp.message(EditProfile.edit_bio)
async def edit_bio_save(message: types.Message, state: FSMContext):
    await db_execute("UPDATE users SET bio = ? WHERE telegram_id = ?", message.text.strip(), message.from_user.id)
    await state.clear()
    menu = await get_main_menu(message.from_user.id)
    await message.answer("✅ <b>Bio updated successfully.</b>", reply_markup=menu, parse_mode="HTML")

@dp.callback_query(F.data == "edit_photo_btn")
async def edit_photo_start(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass
    await callback.message.answer("📸 <b>Send your new portrait photo:</b>", parse_mode="HTML")
    await state.set_state(EditProfile.edit_photo)

@dp.message(EditProfile.edit_photo, F.photo)
async def edit_photo_save(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await db_execute("UPDATE users SET photo_file_id = ? WHERE telegram_id = ?", photo_id, message.from_user.id)
    await state.clear()
    menu = await get_main_menu(message.from_user.id)
    await message.answer("✅ <b>Photo updated successfully.</b>", reply_markup=menu, parse_mode="HTML")

@dp.callback_query(F.data == "edit_goal_btn")
async def edit_goal_menu(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💍 Long-Term / True Love", callback_data="setgoal_Long-Term")],
            [InlineKeyboardButton(text="🥂 Casual Dating / Hookups", callback_data="setgoal_Casual")],
            [InlineKeyboardButton(text="☕ Dates & Explore", callback_data="setgoal_Open")],
            [InlineKeyboardButton(text="🤝 New Friends", callback_data="setgoal_Friends")]
        ]
    )
    try:
        await callback.answer()
    except Exception:
        pass
    await callback.message.answer("🎯 <b>Select your new dating intent / goal:</b>", reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("setgoal_"))
async def save_goal_preference(callback: types.CallbackQuery):
    goal = callback.data.replace("setgoal_", "")
    await db_execute("UPDATE users SET dating_goal = ? WHERE telegram_id = ?", goal, callback.from_user.id)
    try:
        await callback.answer("Goal updated!")
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Your dating goal is now:</b> {GOAL_LABELS.get(goal, goal)}\nSend /profile to view.", parse_mode="HTML")

@dp.message(F.text == "⚙️ Preferences")
async def show_preferences_menu(message: types.Message):
    user_id = message.from_user.id

    user = await db_fetchrow("SELECT target_gender, search_scope, intent_filter, dating_goal FROM users WHERE telegram_id = ?", user_id)

    current_scope = "📍 Same City Only" if user and user.get("search_scope", "same_city") == "same_city" else "🇮🇳 All India (Nationwide)"
    current_tgt = user.get("target_gender", "Everyone") if user else "Everyone"
    current_filter = "🎯 Compatible Goals Only" if user and user.get("intent_filter", "flexible") == "strict" else "🌐 Show All Goals"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📍 My City Only", callback_data="scope_same_city"),
                InlineKeyboardButton(text="🇮🇳 Nationwide", callback_data="scope_all_india")
            ],
            [
                InlineKeyboardButton(text="🎯 Match Same Intent", callback_data="intent_strict"),
                InlineKeyboardButton(text="🌐 Show All Intents", callback_data="intent_flexible")
            ],
            [
                InlineKeyboardButton(text="Men", callback_data="settgt_Male"),
                InlineKeyboardButton(text="Women", callback_data="settgt_Female"),
                InlineKeyboardButton(text="Everyone", callback_data="settgt_Everyone")
            ]
        ]
    )

    text = (
        f"⚙️ <b>DISCOVERY PREFERENCES:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Location Scope:</b> {current_scope}\n"
        f"• <b>Intent Filter:</b> {current_filter}\n"
        f"• <b>Interested In:</b> {current_tgt}\n\n"
        f"Tap an option below to update:"
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data.startswith("intent_"))
async def save_intent_filter(callback: types.CallbackQuery):
    filt = callback.data.replace("intent_", "")
    await db_execute("UPDATE users SET intent_filter = ? WHERE telegram_id = ?", filt, callback.from_user.id)
    
    label = "🎯 Compatible Goals Only (Strict)" if filt == "strict" else "🌐 Show All Goals (Flexible)"
    try:
        await callback.answer("Intent filter updated!")
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Intent filter set to:</b> {label}\nExplore matches in <b>🔍 Discover</b>.", parse_mode="HTML")


@dp.callback_query(F.data.startswith("scope_"))
async def save_scope_preference(callback: types.CallbackQuery):
    scope = callback.data.replace("scope_", "")
    await db_execute("UPDATE users SET search_scope = ? WHERE telegram_id = ?", scope, callback.from_user.id)
    
    label = "📍 Same City Only" if scope == "same_city" else "🇮🇳 All India (Nationwide)"
    try:
        await callback.answer(f"Scope: {label}")
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Location filter updated to:</b> {label}\nTap <b>🔍 Discover</b> to browse.", parse_mode="HTML")


@dp.callback_query(F.data.startswith("settgt_"))
async def edit_target_save(callback: types.CallbackQuery):
    tgt = callback.data.replace("settgt_", "")
    await db_execute("UPDATE users SET target_gender = ? WHERE telegram_id = ?", tgt, callback.from_user.id)
    try:
        await callback.answer("Saved!")
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Matching preference set to:</b> {tgt}", parse_mode="HTML")

@dp.callback_query(F.data == "edit_city_btn")
async def edit_city_start(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception:
        pass
    await callback.message.answer("📍 <b>Select your new State / Region:</b>", reply_markup=get_states_keyboard("editstate_"), parse_mode="HTML")
    await state.set_state(EditProfile.edit_state)

@dp.callback_query(EditProfile.edit_state, F.data.startswith("editstate_"))
async def edit_state_step(callback: types.CallbackQuery, state: FSMContext):
    st_name = callback.data.replace("editstate_", "")
    await state.update_data(state=st_name)
    await callback.message.edit_text(
        f"📍 Region: <b>{st_name}</b>\n\n<b>Select your new City:</b>",
        reply_markup=get_cities_keyboard(st_name, "editcity_"),
        parse_mode="HTML"
    )
    await state.set_state(EditProfile.edit_city)
    try:
        await callback.answer()
    except Exception:
        pass

@dp.callback_query(EditProfile.edit_city, F.data.startswith("editcity_"))
async def edit_city_save(callback: types.CallbackQuery, state: FSMContext):
    city_name = callback.data.replace("editcity_", "")
    data = await state.get_data()
    await db_execute(
        "UPDATE users SET state = ?, city = ? WHERE telegram_id = ?",
        data.get("state", "India"), city_name, callback.from_user.id
    )
    await state.clear()
    try:
        await callback.answer()
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Location updated to:</b> {city_name}, {data.get('state', 'India')}", parse_mode="HTML")


# --- DELETE ACCOUNT ---
@dp.callback_query(F.data == "confirm_delete_btn")
async def ask_delete_confirmation(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.answer()
    except Exception:
        pass
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑️ Permanently Delete", callback_data="do_delete_account"),
                InlineKeyboardButton(text="Cancel", callback_data="cancel_delete")
            ]
        ]
    )
    await callback.message.answer(
        "⚠️ <b>Delete Account Confirmation</b>\n\nThis will permanently remove your profile, swipes, and matches.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete_handler(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    await callback.message.edit_text("<b>Action cancelled.</b> Your profile remains active.", parse_mode="HTML")

@dp.callback_query(F.data == "do_delete_account")
async def perform_delete_account(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.clear()
    await db_execute("DELETE FROM users WHERE telegram_id = ?", user_id)
    await db_execute("DELETE FROM swipes WHERE swiper_id = ? OR target_id = ?", user_id, user_id)
    await db_execute("DELETE FROM matches WHERE user1_id = ? OR user2_id = ?", user_id, user_id)
    try:
        await callback.answer()
    except Exception:
        pass
    await callback.message.edit_text("🗑️ <b>Your account has been deleted.</b> Send /start anytime to return.", parse_mode="HTML")


# --- DISCOVER & SWIPING ---
@dp.message(F.text == "🔍 Discover")
@dp.message(Command("find"))
async def start_discovery(message: types.Message, state: FSMContext):
    await state.clear()
    await show_next_candidate(chat_id=message.chat.id, user_id=message.from_user.id)


@dp.callback_query(F.data.startswith("swipe_"))
async def handle_swipe(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    _, action, target_id_str = callback.data.split("_")
    target_id = int(target_id_str)
    swiper_id = callback.from_user.id
    chat_id = callback.message.chat.id
    today = datetime.now().strftime("%Y-%m-%d")

    swiper_info = await db_fetchrow("SELECT name, city, superlikes_balance, daily_swipes_count, last_swipe_date FROM users WHERE telegram_id = ?", swiper_id)

    swiper_name = swiper_info.get("name", "Someone") if swiper_info else "Someone"
    swiper_city = swiper_info.get("city", "nearby") if swiper_info else "nearby"
    current_swipes = swiper_info.get("daily_swipes_count", 0) if swiper_info and swiper_info.get("last_swipe_date") == today else 0

    await db_execute(
        "UPDATE users SET daily_swipes_count = ?, last_swipe_date = ? WHERE telegram_id = ?",
        current_swipes + 1, today, swiper_id
    )

    if action == "super":
        sl_bal = swiper_info.get("superlikes_balance", 0) if swiper_info else 0
        if sl_bal <= 0 and swiper_id != ADMIN_ID:
            try:
                await callback.answer("⭐ You have 0 Super Likes remaining! Invite friends in '🎁 Invite & Boost' to get more.", show_alert=True)
            except Exception:
                pass
            return
        
        await db_execute("""
            UPDATE users 
            SET superlikes_balance = (CASE WHEN COALESCE(superlikes_balance, 0) > 0 THEN COALESCE(superlikes_balance, 0) - 1 ELSE 0 END) 
            WHERE telegram_id = ?
        """, swiper_id)
        action = "like"

        try:
            target_menu = await get_main_menu(target_id)
            await bot.send_message(
                target_id,
                f"⭐ <b>You received a Super Like!</b>\n"
                f"<b>{swiper_name}</b> from {swiper_city} Super Liked your profile.\n\n"
                f"Tap <b>💌 Likes Received</b> to view their card and match back!",
                reply_markup=target_menu,
                parse_mode="HTML"
            )
        except Exception:
            pass

    await db_execute(
        "INSERT INTO swipes (swiper_id, target_id, action) VALUES (?, ?, ?) ON CONFLICT (swiper_id, target_id) DO UPDATE SET action = EXCLUDED.action",
        swiper_id, target_id, action
    )

    if action == "like":
        mutual = await db_fetchrow("SELECT * FROM swipes WHERE swiper_id = ? AND target_id = ? AND action = 'like'", target_id, swiper_id)

        if mutual:
            u1 = min(swiper_id, target_id)
            u2 = max(swiper_id, target_id)
            await db_execute(
                "INSERT INTO matches (user1_id, user2_id, user1_shared, user2_shared, created_at) VALUES (?, ?, 0, 0, ?) ON CONFLICT DO NOTHING",
                u1, u2, today
            )

            user_obj = await db_fetchrow("SELECT name FROM users WHERE telegram_id = ?", swiper_id)
            target_obj = await db_fetchrow("SELECT name FROM users WHERE telegram_id = ?", target_id)

            kb_to_target = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🤝 Share My Handle", callback_data=f"sharehandle_{swiper_id}")]]
            )
            kb_to_swiper = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🤝 Share My Handle", callback_data=f"sharehandle_{target_id}")]]
            )

            match_text_target = (
                f"🎉 <b>IT'S A MUTUAL MATCH!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"You and <b>{user_obj['name']}</b> liked each other!\n\n"
                f"<i>Handles are kept private until both members tap Share below.</i>"
            )
            match_text_swiper = (
                f"🎉 <b>IT'S A MUTUAL MATCH!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"You and <b>{target_obj['name']}</b> liked each other!\n\n"
                f"<i>Handles are kept private until both members tap Share below.</i>"
            )

            try:
                await bot.send_message(target_id, match_text_target, reply_markup=kb_to_target, parse_mode="HTML")
            except Exception:
                pass

            await bot.send_message(chat_id, match_text_swiper, reply_markup=kb_to_swiper, parse_mode="HTML")

        else:
            try:
                target_menu = await get_main_menu(target_id)
                await bot.send_message(
                    target_id,
                    f"💌 <b>Someone liked your profile!</b>\n"
                    f"A member from <b>{swiper_city}</b> just liked your card.\n\n"
                    f"Tap <b>💌 Likes Received</b> below to review and match back!",
                    reply_markup=target_menu,
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.warning(f"Could not send like notification: {e}")

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        await callback.answer()
    except Exception:
        pass

    await show_next_candidate(chat_id=chat_id, user_id=swiper_id)


# --- LIKES RECEIVED FEED ---
@dp.message(F.text.startswith("💌 Likes Received"))
async def show_likes_received(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    query = """
        SELECT u.* FROM users u
        JOIN swipes s ON u.telegram_id = s.swiper_id
        WHERE s.target_id = ? AND s.action = 'like'
          AND u.is_approved = 1 AND u.is_banned = 0
          AND u.telegram_id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = ?)
        LIMIT 1
    """
    admirer = await db_fetchrow(query, user_id, user_id)

    if not admirer:
        menu = await get_main_menu(user_id)
        await message.answer(
            "💌 <b>No pending likes right now.</b>\nKeep discovering in <b>🔍 Discover</b> to be seen by more members!",
            reply_markup=menu,
            parse_mode="HTML"
        )
        return

    admirer_goal_label = GOAL_LABELS.get(admirer.get("dating_goal", "Open"), "☕ Dates & Explore")
    v_badge = " ✅ [Verified]" if admirer.get("is_verified", 0) == 1 else ""

    icebreaker_section = ""
    if admirer.get("icebreaker_question") and admirer.get("icebreaker_answer"):
        icebreaker_section = f"\n💡 <i>{admirer['icebreaker_question']}</i>\n👉 <b>{admirer['icebreaker_answer']}</b>\n━━━━━━━━━━━━━━━━━━━━━━"

    card_text = (
        f"💌 <b>SOMEONE LIKED YOUR PROFILE!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{admirer['name'].upper()}</b>{v_badge}, {admirer['age']}\n"
        f"📍 <i>{admirer['city']}, {admirer['state']}</i>\n"
        f"🎯 <b>Goal:</b> {admirer_goal_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❝ {admirer['bio']} ❞\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
        f"{icebreaker_section}\n"
        f"<i>Tap ❤️ Like Back to instantly match!</i>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✕ Pass", callback_data=f"likefeed_pass_{admirer['telegram_id']}"),
            InlineKeyboardButton(text="❤️ Like Back", callback_data=f"likefeed_like_{admirer['telegram_id']}")
        ]]
    )

    await message.answer_photo(
        photo=admirer["photo_file_id"],
        caption=card_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("likefeed_"))
async def handle_likefeed_action(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    _, action, target_id_str = callback.data.split("_")
    target_id = int(target_id_str)
    swiper_id = callback.from_user.id
    chat_id = callback.message.chat.id
    today = datetime.now().strftime("%Y-%m-%d")

    await db_execute(
        "INSERT INTO swipes (swiper_id, target_id, action) VALUES (?, ?, ?) ON CONFLICT (swiper_id, target_id) DO UPDATE SET action = EXCLUDED.action",
        swiper_id, target_id, action
    )

    if action == "like":
        u1 = min(swiper_id, target_id)
        u2 = max(swiper_id, target_id)
        await db_execute(
            "INSERT INTO matches (user1_id, user2_id, user1_shared, user2_shared, created_at) VALUES (?, ?, 0, 0, ?) ON CONFLICT DO NOTHING",
            u1, u2, today
        )

        user_obj = await db_fetchrow("SELECT name FROM users WHERE telegram_id = ?", swiper_id)
        target_obj = await db_fetchrow("SELECT name FROM users WHERE telegram_id = ?", target_id)

        kb_to_target = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🤝 Share My Handle", callback_data=f"sharehandle_{swiper_id}")]]
        )
        kb_to_swiper = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🤝 Share My Handle", callback_data=f"sharehandle_{target_id}")]]
        )

        match_text_target = (
            f"🎉 <b>IT'S A MUTUAL MATCH!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"You and <b>{user_obj['name']}</b> liked each other!\n\n"
            f"<i>Handles are kept private until both members tap Share below.</i>"
        )
        match_text_swiper = (
            f"🎉 <b>IT'S A MUTUAL MATCH!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"You and <b>{target_obj['name']}</b> liked each other!\n\n"
            f"<i>Handles are kept private until both members tap Share below.</i>"
        )

        try:
            await bot.send_message(target_id, match_text_target, reply_markup=kb_to_target, parse_mode="HTML")
        except Exception:
            pass

        await bot.send_message(chat_id, match_text_swiper, reply_markup=kb_to_swiper, parse_mode="HTML")

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        await callback.answer()
    except Exception:
        pass

    await show_likes_received(callback.message, state)


# --- CONTACT SHARING EXCHANGE ---
@dp.callback_query(F.data.startswith("sharehandle_"))
async def handle_share_contact(callback: types.CallbackQuery):
    partner_id = int(callback.data.replace("sharehandle_", ""))
    my_id = callback.from_user.id
    u1, u2 = min(my_id, partner_id), max(my_id, partner_id)

    if my_id == u1:
        await db_execute("UPDATE matches SET user1_shared = 1 WHERE user1_id = ? AND user2_id = ?", u1, u2)
    else:
        await db_execute("UPDATE matches SET user2_shared = 1 WHERE user1_id = ? AND user2_id = ?", u1, u2)

    match_row = await db_fetchrow("SELECT * FROM matches WHERE user1_id = ? AND user2_id = ?", u1, u2)
    me = await db_fetchrow("SELECT name, username FROM users WHERE telegram_id = ?", my_id)
    partner = await db_fetchrow("SELECT name, username FROM users WHERE telegram_id = ?", partner_id)

    try:
        await callback.answer("Handle shared!", show_alert=False)
    except Exception:
        pass

    if match_row and match_row.get("user1_shared", 0) == 1 and match_row.get("user2_shared", 0) == 1:
        my_contact = f"@{me['username']}" if me.get('username') else f"<a href='tg://user?id={my_id}'>Direct Telegram Link</a>"
        partner_contact = f"@{partner['username']}" if partner.get('username') else f"<a href='tg://user?id={partner_id}'>Direct Telegram Link</a>"

        await callback.message.answer(
            f"🔓 <b>Mutual Handle Unlocked!</b>\n\n"
            f"<b>{partner['name']}</b> has also shared their handle:\n"
            f"👉 {partner_contact}\n\n"
            f"Tap above to begin chatting directly on Telegram!",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                partner_id,
                f"🔓 <b>Mutual Handle Unlocked!</b>\n\n"
                f"<b>{me['name']}</b> has shared their handle with you:\n"
                f"👉 {my_contact}\n\n"
                f"Tap above to begin chatting directly on Telegram!",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await callback.message.answer(
            f"✓ <b>You shared your handle with {partner['name']}.</b>\n"
            f"As soon as they tap Share back, their contact will unlock here.",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                partner_id,
                f"💌 <b>{me['name']}</b> just opted to share their Telegram handle with you!\n"
                f"Tap <b>👥 My Matches</b> to view their card and share yours back.",
                parse_mode="HTML"
            )
        except Exception:
            pass


# --- MY MATCHES LIST ---
@dp.message(F.text == "👥 My Matches")
async def list_matches(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    query = """
        SELECT u.*, m.user1_shared, m.user2_shared, m.user1_id 
        FROM users u
        JOIN matches m ON (u.telegram_id = m.user1_id OR u.telegram_id = m.user2_id)
        WHERE (m.user1_id = ? OR m.user2_id = ?) AND u.telegram_id != ?
    """
    matches = await db_fetchall(query, user_id, user_id, user_id)

    if not matches:
        await message.answer(
            "👥 <b>You don't have any active matches yet.</b>\nStart swiping in <b>🔍 Discover</b> to match!",
            parse_mode="HTML"
        )
        return

    await message.answer(f"👥 <b>Your Matches ({len(matches)}):</b>", parse_mode="HTML")

    for m in matches:
        is_u1 = (user_id == m["user1_id"])
        my_shared = m.get("user1_shared", 0) if is_u1 else m.get("user2_shared", 0)
        partner_shared = m.get("user2_shared", 0) if is_u1 else m.get("user1_shared", 0)
        m_goal_label = GOAL_LABELS.get(m.get("dating_goal", "Open"), "☕ Dates & Explore")
        v_badge = " ✅ [Verified]" if m.get("is_verified", 0) == 1 else ""

        if my_shared and partner_shared:
            contact = f"@{m['username']}" if m.get('username') else f"<a href='tg://user?id={m['telegram_id']}'>Direct Telegram Profile</a>"
            btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Open Chat on Telegram", url=f"tg://user?id={m['telegram_id']}")]])
            status = f"🔓 <b>Contact Unlocked:</b> {contact}"
        elif my_shared:
            btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Waiting for them to share", callback_data="noop")]])
            status = "⏳ <i>You shared your handle. Waiting for them to share back.</i>"
        else:
            btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤝 Share My Handle", callback_data=f"sharehandle_{m['telegram_id']}")]] )
            status = "🔒 <i>Tap below to share your Telegram handle with them.</i>"

        text = (
            f"👤 <b>{m['name']}</b>{v_badge}, {m['age']} ({m['city']})\n"
            f"🎯 <b>Goal:</b> {m_goal_label}\n"
            f"❝ {m['bio']} ❞\n\n"
            f"{status}"
        )
        await message.answer_photo(photo=m["photo_file_id"], caption=text, reply_markup=btn, parse_mode="HTML")


@dp.callback_query(F.data == "noop")
async def noop_handler(callback: types.CallbackQuery):
    try:
        await callback.answer("Waiting for them to share their handle back.")
    except Exception:
        pass


# --- SWIPE HISTORY SYSTEM ---
@dp.message(F.text == "📜 My History")
@dp.message(Command("history"))
async def show_history_menu(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    liked_count = await db_fetchval("SELECT COUNT(*) FROM swipes WHERE swiper_id = ? AND action = 'like'", user_id)
    passed_count = await db_fetchval("SELECT COUNT(*) FROM swipes WHERE swiper_id = ? AND action = 'pass'", user_id)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"❤️ Liked Profiles ({liked_count})", callback_data="view_history_liked")],
            [InlineKeyboardButton(text=f"❌ Passed Profiles ({passed_count})", callback_data="view_history_passed")]
        ]
    )

    history_menu_text = (
        f"📜 <b>YOUR SWIPE HISTORY:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• ❤️ <b>Profiles You Liked:</b> {liked_count}\n"
        f"• ❌ <b>Profiles You Passed:</b> {passed_count}\n\n"
        f"Select a category below to review their cards:"
    )
    await message.answer(history_menu_text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "view_history_liked")
async def view_history_liked_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    query = """
        SELECT u.*, 
               (SELECT COUNT(*) FROM matches m 
                WHERE (m.user1_id = ? AND m.user2_id = u.telegram_id) 
                   OR (m.user2_id = ? AND m.user1_id = u.telegram_id)) AS is_matched
        FROM users u
        JOIN swipes s ON u.telegram_id = s.target_id
        WHERE s.swiper_id = ? AND s.action = 'like'
        ORDER BY u.name ASC
    """
    liked_users = await db_fetchall(query, user_id, user_id, user_id)

    try:
        await callback.answer()
    except Exception:
        pass

    if not liked_users:
        await callback.message.answer("❤️ <b>You haven't liked any profiles yet.</b>\nExplore in <b>🔍 Discover</b> to find matches!", parse_mode="HTML")
        return

    await callback.message.answer(f"❤️ <b>Profiles You Liked ({len(liked_users)}):</b>", parse_mode="HTML")

    for u in liked_users:
        status = "🎉 <b>Matched!</b>" if u.get("is_matched", 0) > 0 else "⏳ <i>Awaiting their response</i>"
        st_str = u.get("state", "India") or "India"
        ct_str = u.get("city", "Other") or "Other"
        g_label = GOAL_LABELS.get(u.get("dating_goal", "Open"), "☕ Dates & Explore")
        v_badge = " ✅ [Verified]" if u.get("is_verified", 0) == 1 else ""

        card_text = (
            f"👤 <b>{u['name'].upper()}</b>{v_badge}, {u['age']}\n"
            f"📍 <i>{ct_str}, {st_str}</i>\n"
            f"🎯 <b>Goal:</b> {g_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"❝ {u['bio']} ❞\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Status:</b> {status}"
        )
        await callback.message.answer_photo(photo=u["photo_file_id"], caption=card_text, parse_mode="HTML")


@dp.callback_query(F.data == "view_history_passed")
async def view_history_passed_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    query = """
        SELECT u.* FROM users u
        JOIN swipes s ON u.telegram_id = s.target_id
        WHERE s.swiper_id = ? AND s.action = 'pass'
        ORDER BY u.name ASC
    """
    passed_users = await db_fetchall(query, user_id)

    try:
        await callback.answer()
    except Exception:
        pass

    if not passed_users:
        await callback.message.answer("❌ <b>You haven't passed on any profiles.</b>", parse_mode="HTML")
        return

    await callback.message.answer(f"❌ <b>Profiles You Passed ({len(passed_users)}):</b>\n<i>You can tap Rewind to change your mind!</i>", parse_mode="HTML")

    for u in passed_users:
        st_str = u.get("state", "India") or "India"
        ct_str = u.get("city", "Other") or "Other"
        g_label = GOAL_LABELS.get(u.get("dating_goal", "Open"), "☕ Dates & Explore")
        v_badge = " ✅ [Verified]" if u.get("is_verified", 0) == 1 else ""

        rewind_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ Rewind & Like", callback_data=f"rewind_like_{u['telegram_id']}")]]
        )

        card_text = (
            f"👤 <b>{u['name'].upper()}</b>{v_badge}, {u['age']}\n"
            f"📍 <i>{ct_str}, {st_str}</i>\n"
            f"🎯 <b>Goal:</b> {g_label}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"❝ {u['bio']} ❞"
        )
        await callback.message.answer_photo(photo=u["photo_file_id"], caption=card_text, reply_markup=rewind_kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("rewind_like_"))
async def rewind_to_like(callback: types.CallbackQuery):
    target_id = int(callback.data.replace("rewind_like_", ""))
    swiper_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    await db_execute("UPDATE swipes SET action = 'like' WHERE swiper_id = ? AND target_id = ?", swiper_id, target_id)
    mutual = await db_fetchrow("SELECT * FROM swipes WHERE swiper_id = ? AND target_id = ? AND action = 'like'", target_id, swiper_id)

    if mutual:
        u1, u2 = min(swiper_id, target_id), max(swiper_id, target_id)
        await db_execute(
            "INSERT INTO matches (user1_id, user2_id, user1_shared, user2_shared, created_at) VALUES (?, ?, 0, 0, ?) ON CONFLICT DO NOTHING",
            u1, u2, today
        )

        user_obj = await db_fetchrow("SELECT name FROM users WHERE telegram_id = ?", swiper_id)
        target_obj = await db_fetchrow("SELECT name FROM users WHERE telegram_id = ?", target_id)

        kb_to_target = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🤝 Share My Handle", callback_data=f"sharehandle_{swiper_id}")]]
        )
        kb_to_swiper = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🤝 Share My Handle", callback_data=f"sharehandle_{target_id}")]]
        )

        try:
            await bot.send_message(
                target_id,
                f"🎉 <b>IT'S A MUTUAL MATCH!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n<b>{user_obj['name']}</b> liked your profile back!\n\n<i>Tap Share below to exchange handles.</i>",
                reply_markup=kb_to_target,
                parse_mode="HTML"
            )
        except Exception:
            pass

        await callback.message.answer(
            f"🎉 <b>IT'S A MUTUAL MATCH!</b>\n━━━━━━━━━━━━━━━━━━━━━━\nYou and <b>{target_obj['name']}</b> liked each other!\n\n<i>Tap Share below to exchange handles.</i>",
            reply_markup=kb_to_swiper,
            parse_mode="HTML"
        )

    try:
        await callback.answer("Rewound! Profile liked ❤️", show_alert=True)
    except Exception:
        pass


# --- REPORT SYSTEM ---
@dp.callback_query(F.data.startswith("report_"))
async def report_user(callback: types.CallbackQuery, state: FSMContext):
    reported_id = int(callback.data.replace("report_", ""))
    swiper_id = callback.from_user.id

    await db_execute("UPDATE users SET reports_count = reports_count + 1 WHERE telegram_id = ?", reported_id)
    await db_execute(
        "INSERT INTO swipes (swiper_id, target_id, action) VALUES (?, ?, 'pass') ON CONFLICT (swiper_id, target_id) DO UPDATE SET action = 'pass'",
        swiper_id, reported_id
    )

    try:
        await callback.answer("🚩 Profile reported and removed.", show_alert=True)
    except Exception:
        pass

    try:
        await callback.message.delete()
    except Exception:
        pass

    await show_next_candidate(chat_id=callback.message.chat.id, user_id=swiper_id)


# ==========================================
# --- ADMIN CONTROL SUITE & MODERATION ---
# ==========================================

@dp.callback_query(F.data.startswith("adm_approve_"))
async def admin_approve_callback(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.replace("adm_approve_", ""))

    await db_execute("UPDATE users SET is_approved = 1, is_verified = 1, is_banned = 0 WHERE telegram_id = ?", user_id)

    try:
        await callback.answer("User Approved & Verified Badge Granted! ✅")
        await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n✅ <b>STATUS: APPROVED & VERIFIED BY ADMIN</b>", parse_mode="HTML")
    except Exception:
        pass

    try:
        menu = await get_main_menu(user_id)
        await bot.send_message(
            user_id,
            "🎉 <b>Congratulations! Your profile has been manually verified and approved by our moderation team.</b>\n"
            "You now have a <b>✅ Verified Badge</b> attached to your card!\n\n"
            "Tap <b>🔍 Discover</b> to begin exploring real, authentic profiles.",
            reply_markup=menu,
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"Could not notify approved user: {e}")


@dp.callback_query(F.data.startswith("adm_reject_"))
async def admin_reject_callback(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.replace("adm_reject_", ""))

    await db_execute("UPDATE users SET is_approved = 0, is_verified = 0, is_banned = 1 WHERE telegram_id = ?", user_id)

    try:
        await callback.answer("User Rejected & Banned! 🚫")
        await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n🚫 <b>STATUS: REJECTED & BANNED</b>", parse_mode="HTML")
    except Exception:
        pass

    try:
        await bot.send_message(
            user_id,
            "🚫 <b>Your verification submission was reviewed and rejected according to community guidelines.</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass


@dp.message(Command("admin_stats"))
async def admin_stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    total_users = await db_fetchval("SELECT COUNT(*) FROM users")
    approved_users = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_approved = 1 AND is_banned = 0")
    verified_users = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_verified = 1")
    pending_users = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_approved = 0 AND is_banned = 0")
    banned_users = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_banned = 1")

    gender_counts = await db_fetchall("SELECT gender, COUNT(*) AS c FROM users WHERE is_approved = 1 GROUP BY gender")
    gender_text = "\n".join([f"  • {g['gender']}: {g['c']}" for g in gender_counts]) or "  • None"

    goal_counts = await db_fetchall("SELECT dating_goal, COUNT(*) AS c FROM users WHERE is_approved = 1 GROUP BY dating_goal")
    goal_text = "\n".join([f"  • {GOAL_LABELS.get(g['dating_goal'], g['dating_goal'])}: {g['c']}" for g in goal_counts]) or "  • None"

    total_swipes = await db_fetchval("SELECT COUNT(*) FROM swipes")
    total_matches = await db_fetchval("SELECT COUNT(*) FROM matches")

    top_cities = await db_fetchall("SELECT city, COUNT(*) AS c FROM users WHERE is_approved = 1 GROUP BY city ORDER BY COUNT(*) DESC LIMIT 5")
    cities_text = "\n".join([f"  • {city['city']}: {city['c']}" for city in top_cities]) or "  • None"

    db_type = "Neon PostgreSQL (Cloud ☁️)" if pg_pool else "SQLite (Local File 📁)"

    stats_msg = (
        f"📊 <b>SOULMATE BOT ADMIN DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💾 <b>Database Engine:</b> {db_type}\n"
        f"👥 <b>Total Registrations:</b> {total_users}\n"
        f"✅ <b>Approved & Live:</b> {approved_users}\n"
        f"🛡️ <b>Verified Badge Holders:</b> {verified_users}\n"
        f"⏳ <b>Pending Moderation:</b> {pending_users}\n"
        f"🚫 <b>Banned Accounts:</b> {banned_users}\n\n"
        f"🔥 <b>Total Swipes:</b> {total_swipes}\n"
        f"🎉 <b>Total Mutual Matches:</b> {total_matches}\n\n"
        f"🚻 <b>Gender Distribution:</b>\n{gender_text}\n\n"
        f"🎯 <b>Dating Intentions:</b>\n{goal_text}\n\n"
        f"🏙️ <b>Top Active Cities:</b>\n{cities_text}"
    )
    await message.answer(stats_msg, parse_mode="HTML")


@dp.message(Command("ban"))
async def admin_ban_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/ban &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    
    target_id = int(parts[1])
    await db_execute("UPDATE users SET is_banned = 1, is_approved = 0 WHERE telegram_id = ?", target_id)

    await message.answer(f"🚫 User <code>{target_id}</code> has been banned.", parse_mode="HTML")
    try:
        await bot.send_message(target_id, "🚫 <b>Your account has been suspended by the administrator.</b>", parse_mode="HTML")
    except Exception:
        pass


@dp.message(Command("unban"))
async def admin_unban_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/unban &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    
    target_id = int(parts[1])
    await db_execute("UPDATE users SET is_banned = 0, is_approved = 1, is_verified = 1 WHERE telegram_id = ?", target_id)

    await message.answer(f"✅ User <code>{target_id}</code> has been unbanned, approved, and verified.", parse_mode="HTML")


@dp.message(Command("user"))
async def admin_inspect_user(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/user &lt;user_id&gt;</code>", parse_mode="HTML")
        return

    target_id = int(parts[1])
    u = await db_fetchrow("SELECT * FROM users WHERE telegram_id = ?", target_id)

    if not u:
        await message.answer(f"User <code>{target_id}</code> not found.", parse_mode="HTML")
        return

    status = "🚫 BANNED" if u.get("is_banned", 0) == 1 else ("✅ APPROVED & VERIFIED" if u.get("is_verified", 0) == 1 else "⏳ PENDING")
    inspect_text = (
        f"🔍 <b>USER DOSSIER: {u['name'].upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Telegram ID:</b> <code>{u['telegram_id']}</code>\n"
        f"🔗 <b>Username:</b> @{u.get('username') if u.get('username') else 'None'}\n"
        f"📞 <b>Phone:</b> <code>{u.get('phone_number', '')}</code>\n"
        f"🛡️ <b>Status:</b> {status}\n"
        f"🚩 <b>Reports:</b> {u.get('reports_count', 0)}\n"
        f"📍 <b>Location:</b> {u.get('city', 'Other')}, {u.get('state', 'India')}\n"
        f"🚻 <b>Gender:</b> {u.get('gender', '')} | 🎯 <b>Seeking:</b> {u.get('target_gender', 'Everyone')}\n"
        f"🎯 <b>Goal:</b> {GOAL_LABELS.get(u.get('dating_goal', 'Open'), u.get('dating_goal', 'Open'))}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❝ {u.get('bio', '')} ❞"
    )
    if u.get("photo_file_id"):
        await message.answer_photo(photo=u["photo_file_id"], caption=inspect_text, parse_mode="HTML")
    else:
        await message.answer(inspect_text, parse_mode="HTML")


@dp.message(Command("broadcast"))
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "📢 <b>ADMIN BROADCAST MODE</b>\n\n"
        "Send the text or photo message you want to broadcast to all approved users.\n"
        "Send /cancel at any time to abort.",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.broadcast_message)


@dp.message(Command("cancel"), AdminStates.broadcast_message)
async def cancel_broadcast(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Broadcast cancelled.")


@dp.message(AdminStates.broadcast_message)
async def execute_broadcast(message: types.Message, state: FSMContext):
    broadcast_text = message.text or message.caption or ""
    photo_file_id = message.photo[-1].file_id if message.photo else None
    await state.clear()

    rows = await db_fetchall("SELECT telegram_id FROM users WHERE is_approved = 1 AND is_banned = 0")
    user_ids = [r["telegram_id"] for r in rows]

    status_msg = await message.answer(f"⏳ Broadcasting to {len(user_ids)} approved members...")
    sent, blocked = 0, 0

    for uid in user_ids:
        try:
            if photo_file_id:
                await bot.send_photo(uid, photo=photo_file_id, caption=broadcast_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, broadcast_text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            blocked += 1

    await status_msg.edit_text(
        f"✅ <b>Broadcast Completed!</b>\n\n"
        f"• 📬 Successfully Delivered: {sent}\n"
        f"• 🚫 Blocked / Failed: {blocked}",
        parse_mode="HTML"
    )


# --- DUMMY HTTP SERVER FOR RENDER $0 FREE WEB SERVICE ---
async def health_check(request):
    return web.Response(text="Soulmate India Bot is online and running 24/7 on Render & Neon PostgreSQL!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Render Web Server started on port {port}")


# --- STARTUP RUNNER ---
async def main():
    await init_db()
    await start_web_server()
    print("Bot is live with Neon PostgreSQL, Anti-Fake Gestures, Viral 1-Hour Boosts & Render Free Hosting...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
