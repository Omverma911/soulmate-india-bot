import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
import aiosqlite
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

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8974109640:AAHNuuHALqJQFteuwMlaXiPjzYEjzzUDO8Q")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8925689319"))
DB_NAME = "dating_bot.db"
DAILY_SWIPE_LIMIT = 50

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

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

async def get_main_menu(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("""
            SELECT COUNT(*) FROM swipes s
            WHERE s.target_id = ? AND s.action = 'like'
              AND s.swiper_id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = ?)
        """, (user_id, user_id))
        count = (await cur.fetchone())[0]

    likes_btn_text = f"💌 Likes Received ({count})" if count > 0 else "💌 Likes Received"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Discover"), KeyboardButton(text=likes_btn_text)],
            [KeyboardButton(text="👥 My Matches"), KeyboardButton(text="👤 My Profile")],
            [KeyboardButton(text="🎁 Invite Friends"), KeyboardButton(text="📜 My History")],
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


# --- DATABASE INITIALIZATION ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                phone_number TEXT DEFAULT '',
                name TEXT,
                age INTEGER,
                gender TEXT,
                target_gender TEXT,
                dating_goal TEXT DEFAULT 'Long-Term',
                intent_filter TEXT DEFAULT 'flexible',
                state TEXT,
                city TEXT,
                photo_file_id TEXT,
                selfie_file_id TEXT DEFAULT '',
                bio TEXT,
                icebreaker_question TEXT DEFAULT '',
                icebreaker_answer TEXT DEFAULT '',
                reports_count INTEGER DEFAULT 0,
                superlikes_balance INTEGER DEFAULT 1,
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
                created_at TEXT,
                PRIMARY KEY (user1_id, user2_id)
            )
        """)
        
        migrations = [
            "ALTER TABLE users ADD COLUMN phone_number TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN dating_goal TEXT DEFAULT 'Long-Term'",
            "ALTER TABLE users ADD COLUMN intent_filter TEXT DEFAULT 'flexible'",
            "ALTER TABLE users ADD COLUMN search_scope TEXT DEFAULT 'same_city'",
            "ALTER TABLE users ADD COLUMN state TEXT DEFAULT 'India'",
            "ALTER TABLE users ADD COLUMN reports_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN superlikes_balance INTEGER DEFAULT 1",
            "ALTER TABLE users ADD COLUMN last_superlike_date TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN daily_swipes_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN last_swipe_date TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN boost_expires_at TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_approved INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN selfie_file_id TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN icebreaker_question TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN icebreaker_answer TEXT DEFAULT ''",
            "ALTER TABLE matches ADD COLUMN user1_shared INTEGER DEFAULT 0",
            "ALTER TABLE matches ADD COLUMN user2_shared INTEGER DEFAULT 0"
        ]
        for query in migrations:
            try:
                await db.execute(query)
            except Exception:
                pass
        await db.commit()


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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        current_user = await cur.fetchone()

        if not current_user:
            await bot.send_message(chat_id, "Please set up your profile first using /start.")
            return

        if current_user["is_banned"] == 1:
            await bot.send_message(chat_id, "🚫 <b>Your account has been suspended for violating community guidelines.</b>", parse_mode="HTML")
            return

        if current_user["is_approved"] == 0:
            await bot.send_message(
                chat_id,
                "⏳ <b>Your profile is pending admin manual verification.</b>\n"
                "You will receive an alert as soon as our moderators review your selfie gesture!",
                parse_mode="HTML"
            )
            return

        # Daily Swipe Limit check
        last_date = current_user["last_swipe_date"] or ""
        swipes_used = current_user["daily_swipes_count"] if last_date == today else 0

        if swipes_used >= DAILY_SWIPE_LIMIT and current_user["telegram_id"] != ADMIN_ID:
            limit_msg = (
                f"🛑 <b>Daily Swipe Limit Reached ({DAILY_SWIPE_LIMIT}/{DAILY_SWIPE_LIMIT})</b>\n\n"
                f"Your limit resets at midnight! Want more swipes and free Super Likes?\n"
                f"Tap <b>🎁 Invite Friends</b> to get a 24-hour Profile Boost!"
            )
            menu = await get_main_menu(user_id)
            await bot.send_message(chat_id, limit_msg, reply_markup=menu, parse_mode="HTML")
            return

        search_scope = current_user["search_scope"] or "same_city"
        intent_filter = current_user["intent_filter"] or "flexible"
        user_goal = current_user["dating_goal"] or "Long-Term"

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

        cursor = await db.execute(query, tuple(params))
        candidate = await cursor.fetchone()

    if not candidate:
        scope_msg = (
            f"No more matching profiles in <b>{current_user['city']}</b> right now.\n"
            f"Tip: Try switching to <b>🇮🇳 All India</b> or <b>🌐 All Goals</b> in <b>⚙️ Preferences</b>!"
            if search_scope == "same_city"
            else "You're all caught up for now!\nCheck back soon or explore <b>💌 Likes Received</b>."
        )

        no_profile_text = f"✨ <b>You're all caught up!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{scope_msg}"
        menu = await get_main_menu(user_id)
        await bot.send_message(chat_id, no_profile_text, reply_markup=menu, parse_mode="HTML")
        return

    st_str = candidate["state"] or "India"
    ct_str = candidate["city"] or "Other"
    cand_goal_label = GOAL_LABELS.get(candidate["dating_goal"], "☕ Dates & Explore")
    v_badge = " ✅ [Verified]" if candidate["is_verified"] == 1 else ""
    boost_badge = " 🚀 [Spotlight Boost]" if candidate["is_boosted"] == 1 else ""

    icebreaker_section = ""
    if candidate["icebreaker_question"] and candidate["icebreaker_answer"]:
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


# --- ONBOARDING & VIRAL REFERRAL FLOW ---
@dp.message(CommandStart(deep_link=True))
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject = None):
    await state.clear()
    uid = message.from_user.id

    # Check for referral payload
    referrer_id = 0
    if command and command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args.replace("ref_", ""))
            if referrer_id == uid:
                referrer_id = 0
        except Exception:
            referrer_id = 0

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (uid,))
        user = await cursor.fetchone()

    if user:
        if user["is_banned"] == 1:
            await message.answer("🚫 <b>Your account is suspended.</b>", parse_mode="HTML")
            return
        
        status_note = ""
        if user["is_approved"] == 0:
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
    await message.answer("✍️ <b>Introduce yourself with a short bio:</b>", parse_mode="HTML")
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

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users 
            (telegram_id, username, phone_number, name, age, gender, target_gender, dating_goal, intent_filter, state, city, photo_file_id, selfie_file_id, bio, icebreaker_question, icebreaker_answer, reports_count, superlikes_balance, last_superlike_date, daily_swipes_count, last_swipe_date, boost_expires_at, referred_by, search_scope, is_approved, is_verified, is_banned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'flexible', ?, ?, ?, ?, ?, ?, ?, 0, 1, '', 0, '', '', ?, 'same_city', ?, ?, 0)
        """, (
            uid, username, phone, name, age, gender, tgt_gender, goal, state_val, city_val, photo_file_id, selfie_file_id, bio, ice_q, ice_a, ref_by, is_approved_val, is_verified_val
        ))

        # Reward Referrer with +3 Super Likes and 24h Profile Boost
        if ref_by and ref_by != uid:
            boost_time = (datetime.now() + timedelta(hours=24)).isoformat()
            await db.execute("""
                UPDATE users 
                SET superlikes_balance = superlikes_balance + 3,
                    boost_expires_at = ?
                WHERE telegram_id = ?
            """, (boost_time, ref_by))

            try:
                await bot.send_message(
                    ref_by,
                    f"🎁 <b>REFERRAL REWARD UNLOCKED!</b>\n\n"
                    f"Your friend <b>{name}</b> just registered using your link!\n"
                    f"• ⭐ <b>+3 Super Likes</b> added to your account.\n"
                    f"• 🚀 <b>24-Hour Profile Boost</b> activated!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        await db.commit()

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


# --- VIRAL INVITE & REFERRALS ---
@dp.message(F.text == "🎁 Invite Friends")
@dp.message(Command("invite"))
async def show_invite_menu(message: types.Message):
    uid = message.from_user.id
    bot_info = await bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (uid,))
        ref_count = (await cur.fetchone())[0]

        cur_u = await db.execute("SELECT superlikes_balance, boost_expires_at FROM users WHERE telegram_id = ?", (uid,))
        u = await cur_u.fetchone()

    sl_bal = u["superlikes_balance"] if u else 1
    boost_active = "Active 🚀" if u and u["boost_expires_at"] and u["boost_expires_at"] > datetime.now().isoformat() else "Inactive"

    invite_msg = (
        f"🎁 <b>INVITE FRIENDS & GET REWARDED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Share your referral link with friends on WhatsApp, Instagram, or Telegram.\n\n"
        f"<b>YOUR REWARDS PER INVITE:</b>\n"
        f"• ⭐ <b>+3 Free Super Likes</b>\n"
        f"• 🚀 <b>24-Hour Profile Spotlight Boost</b> (Pushes your profile to #1 in your city)\n\n"
        f"📊 <b>Your Referral Stats:</b>\n"
        f"• 👥 Friends Invited: <b>{ref_count}</b>\n"
        f"• ⭐ Super Likes Balance: <b>{sl_bal}</b>\n"
        f"• 🚀 Spotlight Boost Status: <b>{boost_active}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Your Personal Invite Link:</b>\n"
        f"<code>{referral_link}</code>"
    )

    share_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="📲 Share on Telegram",
                url=f"https://t.me/share/url?url={referral_link}&text=Join%20Soulmate%20India%20to%20find%20authentic%20matches!"
            )
        ]]
    )

    await message.answer(invite_msg, reply_markup=share_kb, parse_mode="HTML")


# --- VIEW & MANAGE PROFILE ---
@dp.message(F.text == "👤 My Profile")
@dp.message(Command("profile"))
async def show_profile(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    now_iso = datetime.now().isoformat()

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        user = await cur.fetchone()

        if not user:
            await message.answer("You haven't set up a profile yet. Send /start to begin.")
            return

        state_val = user["state"] or "India"
        city_val = user["city"] or "Other"
        my_goal_label = GOAL_LABELS.get(user["dating_goal"], "💍 Long-Term / True Love")

        cur_likes = await db.execute("SELECT COUNT(*) FROM swipes WHERE target_id = ? AND action = 'like'", (user_id,))
        total_likes = (await cur_likes.fetchone())[0]

        cur_matches = await db.execute("SELECT COUNT(*) FROM matches WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
        total_matches = (await cur_matches.fetchone())[0]

        cur_swiped = await db.execute("SELECT COUNT(*) FROM swipes WHERE swiper_id = ?", (user_id,))
        total_swiped = (await cur_swiped.fetchone())[0]

        cur_city_users = await db.execute("SELECT COUNT(*) FROM users WHERE city = ? AND is_approved = 1", (city_val,))
        city_user_count = (await cur_city_users.fetchone())[0]

        cur_total_users = await db.execute("SELECT COUNT(*) FROM users WHERE is_approved = 1")
        total_user_count = (await cur_total_users.fetchone())[0]

    status_tag = "✅ Approved & Verified" if user["is_verified"] == 1 else ("⏳ Under Review" if user["is_approved"] == 0 else "✓ Active")
    v_badge = " ✅ [Verified]" if user["is_verified"] == 1 else ""
    boost_status = "🚀 ACTIVE (Spotlight #1)" if user["boost_expires_at"] and user["boost_expires_at"] > now_iso else "Inactive"
    scope_display = "📍 Same City Only" if user["search_scope"] == "same_city" else "🇮🇳 All India (Nationwide)"

    icebreaker_text = ""
    if user["icebreaker_question"] and user["icebreaker_answer"]:
        icebreaker_text = f"\n💡 <i>{user['icebreaker_question']}</i>\n👉 <b>{user['icebreaker_answer']}</b>\n━━━━━━━━━━━━━━━━━━━━━━"

    profile_card = (
        f"👤 <b>{user['name'].upper()}</b>{v_badge}, {user['age']}\n"
        f"📍 <i>{city_val}, {state_val}</i>\n"
        f"🎯 <b>My Goal:</b> {my_goal_label}\n"
        f"🛡️ <b>Status:</b> {status_tag}\n"
        f"🚀 <b>Spotlight Boost:</b> {boost_status}\n"
        f"⭐ <b>Super Likes:</b> {user['superlikes_balance']}\n"
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
                InlineKeyboardButton(text="✍️ Edit Bio", callback_data="edit_bio_btn"),
                InlineKeyboardButton(text="📸 Change Photo", callback_data="edit_photo_btn"),
            ],
            [
                InlineKeyboardButton(text="📍 Update City", callback_data="edit_city_btn"),
                InlineKeyboardButton(text="🎯 Change Goal", callback_data="edit_goal_btn"),
            ],
            [
                InlineKeyboardButton(text="🎁 Invite & Boost", callback_data="open_invite_btn"),
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET bio = ? WHERE telegram_id = ?", (message.text.strip(), message.from_user.id))
        await db.commit()
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET photo_file_id = ? WHERE telegram_id = ?", (photo_id, message.from_user.id))
        await db.commit()
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET dating_goal = ? WHERE telegram_id = ?", (goal, callback.from_user.id))
        await db.commit()
    try:
        await callback.answer("Goal updated!")
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Your dating goal is now:</b> {GOAL_LABELS.get(goal, goal)}\nSend /profile to view.", parse_mode="HTML")

@dp.message(F.text == "⚙️ Preferences")
async def show_preferences_menu(message: types.Message):
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT target_gender, search_scope, intent_filter, dating_goal FROM users WHERE telegram_id = ?", (user_id,))
        user = await cur.fetchone()

    current_scope = "📍 Same City Only" if user and user["search_scope"] == "same_city" else "🇮🇳 All India (Nationwide)"
    current_tgt = user["target_gender"] if user else "Everyone"
    current_filter = "🎯 Compatible Goals Only" if user and user["intent_filter"] == "strict" else "🌐 Show All Goals"

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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET intent_filter = ? WHERE telegram_id = ?", (filt, callback.from_user.id))
        await db.commit()
    
    label = "🎯 Compatible Goals Only (Strict)" if filt == "strict" else "🌐 Show All Goals (Flexible)"
    try:
        await callback.answer("Intent filter updated!")
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Intent filter set to:</b> {label}\nExplore matches in <b>🔍 Discover</b>.", parse_mode="HTML")


@dp.callback_query(F.data.startswith("scope_"))
async def save_scope_preference(callback: types.CallbackQuery):
    scope = callback.data.replace("scope_", "")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET search_scope = ? WHERE telegram_id = ?", (scope, callback.from_user.id))
        await db.commit()
    
    label = "📍 Same City Only" if scope == "same_city" else "🇮🇳 All India (Nationwide)"
    try:
        await callback.answer(f"Scope: {label}")
    except Exception:
        pass
    await callback.message.edit_text(f"✅ <b>Location filter updated to:</b> {label}\nTap <b>🔍 Discover</b> to browse.", parse_mode="HTML")


@dp.callback_query(F.data.startswith("settgt_"))
async def edit_target_save(callback: types.CallbackQuery):
    tgt = callback.data.replace("settgt_", "")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET target_gender = ? WHERE telegram_id = ?", (tgt, callback.from_user.id))
        await db.commit()
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET state = ?, city = ? WHERE telegram_id = ?",
            (data.get("state", "India"), city_name, callback.from_user.id)
        )
        await db.commit()
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM users WHERE telegram_id = ?", (user_id,))
        await db.execute("DELETE FROM swipes WHERE swiper_id = ? OR target_id = ?", (user_id, user_id))
        await db.execute("DELETE FROM matches WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
        await db.commit()
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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Update Daily Swipe Count
        cur_swiper = await db.execute("SELECT name, city, superlikes_balance, daily_swipes_count, last_swipe_date FROM users WHERE telegram_id = ?", (swiper_id,))
        swiper_info = await cur_swiper.fetchone()
        
        swiper_name = swiper_info["name"] if swiper_info else "Someone"
        swiper_city = swiper_info["city"] if swiper_info else "nearby"
        current_swipes = swiper_info["daily_swipes_count"] if swiper_info["last_swipe_date"] == today else 0

        # Increment swipe count
        await db.execute(
            "UPDATE users SET daily_swipes_count = ?, last_swipe_date = ? WHERE telegram_id = ?",
            (current_swipes + 1, today, swiper_id)
        )

        if action == "super":
            sl_bal = swiper_info["superlikes_balance"] if swiper_info else 0
            if sl_bal <= 0 and swiper_id != ADMIN_ID:
                try:
                    await callback.answer("⭐ You have 0 Super Likes remaining! Invite friends in '🎁 Invite Friends' to get more.", show_alert=True)
                except Exception:
                    pass
                return
            
            # Deduct 1 Super Like
            await db.execute("UPDATE users SET superlikes_balance = MAX(0, superlikes_balance - 1) WHERE telegram_id = ?", (swiper_id,))
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

        await db.execute(
            "INSERT OR REPLACE INTO swipes (swiper_id, target_id, action) VALUES (?, ?, ?)",
            (swiper_id, target_id, action)
        )
        await db.commit()

        if action == "like":
            cur = await db.execute(
                "SELECT * FROM swipes WHERE swiper_id = ? AND target_id = ? AND action = 'like'",
                (target_id, swiper_id)
            )
            mutual = await cur.fetchone()

            if mutual:
                u1 = min(swiper_id, target_id)
                u2 = max(swiper_id, target_id)
                await db.execute(
                    "INSERT OR IGNORE INTO matches (user1_id, user2_id, user1_shared, user2_shared, created_at) VALUES (?, ?, 0, 0, ?)",
                    (u1, u2, today)
                )
                await db.commit()

                cur_user = await db.execute("SELECT name FROM users WHERE telegram_id = ?", (swiper_id,))
                user_obj = await cur_user.fetchone()

                cur_target = await db.execute("SELECT name FROM users WHERE telegram_id = ?", (target_id,))
                target_obj = await cur_target.fetchone()

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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT u.* FROM users u
            JOIN swipes s ON u.telegram_id = s.swiper_id
            WHERE s.target_id = ? AND s.action = 'like'
              AND u.is_approved = 1 AND u.is_banned = 0
              AND u.telegram_id NOT IN (SELECT target_id FROM swipes WHERE swiper_id = ?)
            LIMIT 1
        """
        cursor = await db.execute(query, (user_id, user_id))
        admirer = await cursor.fetchone()

    if not admirer:
        menu = await get_main_menu(user_id)
        await message.answer(
            "💌 <b>No pending likes right now.</b>\nKeep discovering in <b>🔍 Discover</b> to be seen by more members!",
            reply_markup=menu,
            parse_mode="HTML"
        )
        return

    admirer_goal_label = GOAL_LABELS.get(admirer["dating_goal"], "☕ Dates & Explore")
    v_badge = " ✅ [Verified]" if admirer["is_verified"] == 1 else ""

    icebreaker_section = ""
    if admirer["icebreaker_question"] and admirer["icebreaker_answer"]:
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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        await db.execute(
            "INSERT OR REPLACE INTO swipes (swiper_id, target_id, action) VALUES (?, ?, ?)",
            (swiper_id, target_id, action)
        )
        await db.commit()

        if action == "like":
            u1 = min(swiper_id, target_id)
            u2 = max(swiper_id, target_id)
            await db.execute(
                "INSERT OR IGNORE INTO matches (user1_id, user2_id, user1_shared, user2_shared, created_at) VALUES (?, ?, 0, 0, ?)",
                (u1, u2, today)
            )
            await db.commit()

            cur_user = await db.execute("SELECT name FROM users WHERE telegram_id = ?", (swiper_id,))
            user_obj = await cur_user.fetchone()

            cur_target = await db.execute("SELECT name FROM users WHERE telegram_id = ?", (target_id,))
            target_obj = await cur_target.fetchone()

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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        if my_id == u1:
            await db.execute("UPDATE matches SET user1_shared = 1 WHERE user1_id = ? AND user2_id = ?", (u1, u2))
        else:
            await db.execute("UPDATE matches SET user2_shared = 1 WHERE user1_id = ? AND user2_id = ?", (u1, u2))
        await db.commit()

        cur = await db.execute("SELECT * FROM matches WHERE user1_id = ? AND user2_id = ?", (u1, u2))
        match_row = await cur.fetchone()

        cur_me = await db.execute("SELECT name, username FROM users WHERE telegram_id = ?", (my_id,))
        me = await cur_me.fetchone()

        cur_partner = await db.execute("SELECT name, username FROM users WHERE telegram_id = ?", (partner_id,))
        partner = await cur_partner.fetchone()

    try:
        await callback.answer("Handle shared!", show_alert=False)
    except Exception:
        pass

    if match_row and match_row["user1_shared"] == 1 and match_row["user2_shared"] == 1:
        my_contact = f"@{me['username']}" if me['username'] else f"<a href='tg://user?id={my_id}'>Direct Telegram Link</a>"
        partner_contact = f"@{partner['username']}" if partner['username'] else f"<a href='tg://user?id={partner_id}'>Direct Telegram Link</a>"

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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT u.*, m.user1_shared, m.user2_shared, m.user1_id 
            FROM users u
            JOIN matches m ON (u.telegram_id = m.user1_id OR u.telegram_id = m.user2_id)
            WHERE (m.user1_id = ? OR m.user2_id = ?) AND u.telegram_id != ?
        """
        cursor = await db.execute(query, (user_id, user_id, user_id))
        matches = await cursor.fetchall()

    if not matches:
        await message.answer(
            "👥 <b>You don't have any active matches yet.</b>\nStart swiping in <b>🔍 Discover</b> to match!",
            parse_mode="HTML"
        )
        return

    await message.answer(f"👥 <b>Your Matches ({len(matches)}):</b>", parse_mode="HTML")

    for m in matches:
        is_u1 = (user_id == m["user1_id"])
        my_shared = m["user1_shared"] if is_u1 else m["user2_shared"]
        partner_shared = m["user2_shared"] if is_u1 else m["user1_shared"]
        m_goal_label = GOAL_LABELS.get(m["dating_goal"], "☕ Dates & Explore")
        v_badge = " ✅ [Verified]" if m["is_verified"] == 1 else ""

        if my_shared and partner_shared:
            contact = f"@{m['username']}" if m['username'] else f"<a href='tg://user?id={m['telegram_id']}'>Direct Telegram Profile</a>"
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

    async with aiosqlite.connect(DB_NAME) as db:
        cur_liked = await db.execute("SELECT COUNT(*) FROM swipes WHERE swiper_id = ? AND action = 'like'", (user_id,))
        liked_count = (await cur_liked.fetchone())[0]

        cur_passed = await db.execute("SELECT COUNT(*) FROM swipes WHERE swiper_id = ? AND action = 'pass'", (user_id,))
        passed_count = (await cur_passed.fetchone())[0]

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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
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
        cursor = await db.execute(query, (user_id, user_id, user_id))
        liked_users = await cursor.fetchall()

    try:
        await callback.answer()
    except Exception:
        pass

    if not liked_users:
        await callback.message.answer("❤️ <b>You haven't liked any profiles yet.</b>\nExplore in <b>🔍 Discover</b> to find matches!", parse_mode="HTML")
        return

    await callback.message.answer(f"❤️ <b>Profiles You Liked ({len(liked_users)}):</b>", parse_mode="HTML")

    for u in liked_users:
        status = "🎉 <b>Matched!</b>" if u["is_matched"] > 0 else "⏳ <i>Awaiting their response</i>"
        st_str = u["state"] or "India"
        ct_str = u["city"] or "Other"
        g_label = GOAL_LABELS.get(u["dating_goal"], "☕ Dates & Explore")
        v_badge = " ✅ [Verified]" if u["is_verified"] == 1 else ""

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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT u.* FROM users u
            JOIN swipes s ON u.telegram_id = s.target_id
            WHERE s.swiper_id = ? AND s.action = 'pass'
            ORDER BY u.name ASC
        """
        cursor = await db.execute(query, (user_id,))
        passed_users = await cursor.fetchall()

    try:
        await callback.answer()
    except Exception:
        pass

    if not passed_users:
        await callback.message.answer("❌ <b>You haven't passed on any profiles.</b>", parse_mode="HTML")
        return

    await callback.message.answer(f"❌ <b>Profiles You Passed ({len(passed_users)}):</b>\n<i>You can tap Rewind to change your mind!</i>", parse_mode="HTML")

    for u in passed_users:
        st_str = u["state"] or "India"
        ct_str = u["city"] or "Other"
        g_label = GOAL_LABELS.get(u["dating_goal"], "☕ Dates & Explore")
        v_badge = " ✅ [Verified]" if u["is_verified"] == 1 else ""

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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        await db.execute(
            "UPDATE swipes SET action = 'like' WHERE swiper_id = ? AND target_id = ?",
            (swiper_id, target_id)
        )
        await db.commit()

        cur = await db.execute(
            "SELECT * FROM swipes WHERE swiper_id = ? AND target_id = ? AND action = 'like'",
            (target_id, swiper_id)
        )
        mutual = await cur.fetchone()

        if mutual:
            u1, u2 = min(swiper_id, target_id), max(swiper_id, target_id)
            await db.execute(
                "INSERT OR IGNORE INTO matches (user1_id, user2_id, user1_shared, user2_shared, created_at) VALUES (?, ?, 0, 0, ?)",
                (u1, u2, today)
            )
            await db.commit()

            cur_user = await db.execute("SELECT name FROM users WHERE telegram_id = ?", (swiper_id,))
            user_obj = await cur_user.fetchone()

            cur_target = await db.execute("SELECT name FROM users WHERE telegram_id = ?", (target_id,))
            target_obj = await cur_target.fetchone()

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

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET reports_count = reports_count + 1 WHERE telegram_id = ?", (reported_id,))
        await db.execute("INSERT OR REPLACE INTO swipes (swiper_id, target_id, action) VALUES (?, ?, 'pass')", (swiper_id, reported_id))
        await db.commit()

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

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_approved = 1, is_verified = 1, is_banned = 0 WHERE telegram_id = ?", (user_id,))
        await db.commit()

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

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_approved = 0, is_verified = 0, is_banned = 1 WHERE telegram_id = ?", (user_id,))
        await db.commit()

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

    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_approved = 1 AND is_banned = 0")
        approved_users = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1")
        verified_users = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_approved = 0 AND is_banned = 0")
        pending_users = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned_users = (await cur.fetchone())[0]

        cur = await db.execute("SELECT gender, COUNT(*) FROM users WHERE is_approved = 1 GROUP BY gender")
        gender_counts = await cur.fetchall()
        gender_text = "\n".join([f"  • {g}: {c}" for g, c in gender_counts]) or "  • None"

        cur = await db.execute("SELECT dating_goal, COUNT(*) FROM users WHERE is_approved = 1 GROUP BY dating_goal")
        goal_counts = await cur.fetchall()
        goal_text = "\n".join([f"  • {GOAL_LABELS.get(g, g)}: {c}" for g, c in goal_counts]) or "  • None"

        cur = await db.execute("SELECT COUNT(*) FROM swipes")
        total_swipes = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(*) FROM matches")
        total_matches = (await cur.fetchone())[0]

        cur = await db.execute("SELECT city, COUNT(*) FROM users WHERE is_approved = 1 GROUP BY city ORDER BY COUNT(*) DESC LIMIT 5")
        top_cities = await cur.fetchall()
        cities_text = "\n".join([f"  • {city}: {count}" for city, count in top_cities]) or "  • None"

    stats_msg = (
        f"📊 <b>SOULMATE BOT ADMIN DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_banned = 1, is_approved = 0 WHERE telegram_id = ?", (target_id,))
        await db.commit()

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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET is_banned = 0, is_approved = 1, is_verified = 1 WHERE telegram_id = ?", (target_id,))
        await db.commit()

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
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (target_id,))
        u = await cur.fetchone()

    if not u:
        await message.answer(f"User <code>{target_id}</code> not found.", parse_mode="HTML")
        return

    status = "🚫 BANNED" if u["is_banned"] == 1 else ("✅ APPROVED & VERIFIED" if u["is_verified"] == 1 else "⏳ PENDING")
    inspect_text = (
        f"🔍 <b>USER DOSSIER: {u['name'].upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Telegram ID:</b> <code>{u['telegram_id']}</code>\n"
        f"🔗 <b>Username:</b> @{u['username'] if u['username'] else 'None'}\n"
        f"📞 <b>Phone:</b> <code>{u['phone_number']}</code>\n"
        f"🛡️ <b>Status:</b> {status}\n"
        f"🚩 <b>Reports:</b> {u['reports_count']}\n"
        f"📍 <b>Location:</b> {u['city']}, {u['state']}\n"
        f"🚻 <b>Gender:</b> {u['gender']} | 🎯 <b>Seeking:</b> {u['target_gender']}\n"
        f"🎯 <b>Goal:</b> {GOAL_LABELS.get(u['dating_goal'], u['dating_goal'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❝ {u['bio']} ❞"
    )
    if u["photo_file_id"]:
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

    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT telegram_id FROM users WHERE is_approved = 1 AND is_banned = 0")
        user_ids = [row[0] for row in await cur.fetchall()]

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
    return web.Response(text="Soulmate India Bot is online and running 24/7!")

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
    print("Bot is live with Viral Referrals, Daily Limits, Spotlights, and Full Verification...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())