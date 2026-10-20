import os
import re
import time
import random
import logging
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from pymongo import MongoClient

# --- Import Data ---
try:
    from chat_data import CHAT_DATA, TRUTHS, DARES, RIZZ, ROASTS, BAN_GIFS, MUTE_GIFS
except ImportError:
    CHAT_DATA, TRUTHS, DARES, RIZZ, ROASTS = {"hello": ["Hi!"]}, ["Truth"], ["Dare"], ["Rizz"], ["Roast"]
    BAN_GIFS, MUTE_GIFS = [], []

# --- Logging Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Database Setup ---
MONGO_URI = os.environ.get("MONGODB_URI")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

mongo_client = MongoClient(MONGO_URI)
db = mongo_client['aegis_db']
settings_col = db['settings']
filters_col = db['filters']
sticker_filters_col = db['sticker_filters']
warnings_col = db['warnings']
admins_col = db['custom_admins']
notes_col = db['notes']
badwords_col = db['badwords']
afk_col = db['afk']
chats_col = db['chats']
gbans_col = db['gbans']
users_col = db['users']
chat_replies_col = db['chat_replies']

# --- Languages ---
LANGS = {
    "en": {
        "denied": "🚫 <b>Access Denied!</b> You don't have enough permissions.",
        "owner_respect": "👑 <b>Hukum sar aankhon par, Janab-e-Aala!</b>\n\n",
        "owner_protection": "🛑 <b>ACCESS DENIED!</b>\n\nKisi ki aukaat nahi ki mere Owner ko touch kare! 😡",
        "user_not_found": "❌ <b>Target not found!</b> Please reply to their message.",
        "banned": "🔨 <b>BANNED!</b> {} removed. 🚫",
        "unbanned": "🕊️ {} unbanned. ✅",
        "kicked": "👢 <b>KICKED!</b> {} removed. 🚪",
        "muted": "🔇 <b>MUTED!</b> {} silenced. 🤐",
        "unmuted": "🔊 <b>UNMUTED!</b> {} can speak. 🗣️",
        "pinned": "📌 Message pinned!",
        "unpinned": "📍 Message unpinned!",
        "admin_error": "⚠️ <b>Error:</b> Action failed. User is Admin or I lack permissions.",
        "lang_changed": "🌐 Language changed to English! 🇬🇧"
    },
    "hi": {
        "denied": "🚫 <b>Permission nahi hai!</b>",
        "owner_respect": "👑 <b>Hukum sar aankhon par, Janab-e-Aala!</b>\n\n",
        "owner_protection": "🛑 <b>ACCESS DENIED!</b>\n\nKisi ki aukaat nahi ki mere Owner ko touch kare! 😡",
        "user_not_found": "❌ <b>Target nahi mila!</b> Reply karein.",
        "banned": "🔨 <b>BANNED!</b> {} ko ban kar diya. 🚫",
        "unbanned": "🕊️ {} ko unban kar diya. ✅",
        "kicked": "👢 <b>KICKED!</b> {} ko nikal diya. 🚪",
        "muted": "🔇 <b>MUTED!</b> {} ab nahi bol sakta. 🤐",
        "unmuted": "🔊 <b>UNMUTED!</b> {} ab bol sakta hai. 🗣️",
        "pinned": "📌 Message pin ho gaya!",
        "unpinned": "📍 Message unpin ho gaya!",
        "admin_error": "⚠️ <b>Error:</b> Action fail. User Admin ho sakta hai.",
        "lang_changed": "🌐 Language Hindi mein badli! 🇮🇳"
    }
}

def get_lang(chat_id):
    data = settings_col.find_one({"chat_id": chat_id})
    return data.get("lang", "en") if data else "en"

# --- Helpers ---
async def get_user_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == OWNER_ID: return 99
    chat_id = update.effective_chat.id
    data = admins_col.find_one({"chat_id": chat_id, "user_id": user_id})
    if data: return data.get("level", 0)
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']: return 2
    except: pass
    return 0

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user
    if context.args:
        arg = context.args[0]
        try:
            if arg.isdigit() or (arg.startswith('-') and arg[1:].isdigit()):
                return await context.bot.get_chat(int(arg))
            else:
                if not arg.startswith('@'): arg = '@' + arg
                return await context.bot.get_chat(arg)
        except: return None
    return None

def extract_time(time_str):
    match = re.match(r'(\d+)([mhd])', time_str.lower())
    if not match: return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == 'm': return timedelta(minutes=val)
    if unit == 'h': return timedelta(hours=val)
    if unit == 'd': return timedelta(days=val)
    return None

def get_chat_permissions():
    return ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True, can_send_polls=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True)

async def auto_unmute(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try: await context.bot.restrict_chat_member(job.chat_id, job.data['user_id'], get_chat_permissions())
    except: pass

async def auto_unban(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try: await context.bot.unban_chat_member(job.chat_id, job.data['user_id'])
    except: pass

# --- GIF Fetcher ---
def fetch_gif(action):
    try:
        url = f"https://nekos.best/api/v2/{action}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200: return res.json()["results"][0]["url"]
    except: pass
    try:
        url = f"https://api.waifu.pics/sfw/{action}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200: return res.json().get("url")
    except: pass
    return None

# --- Economy Helpers ---
def get_user_bal(user_id):
    if user_id == OWNER_ID: return "♾️ Unlimited"
    user = users_col.find_one({"user_id": user_id})
    if not user:
        users_col.insert_one({"user_id": user_id, "balance": 100, "last_daily": None})
        return 100
    return user.get("balance", 100)

def update_user_bal(user_id, amount):
    if user_id == OWNER_ID and amount < 0: return 
    users_col.update_one({"user_id": user_id}, {"$inc": {"balance": amount}}, upsert=True)

# --- Keyboards ---
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡️ Moderation", callback_data="m_mod"), InlineKeyboardButton("🎮 Fun & Games", callback_data="m_fun")],
        [InlineKeyboardButton("👑 Admin Levels", callback_data="m_admin"), InlineKeyboardButton("💰 Economy", callback_data="m_eco")],
        [InlineKeyboardButton("📝 Notes", callback_data="m_notes"), InlineKeyboardButton("🚫 Blacklist", callback_data="m_badwords")],
        [InlineKeyboardButton("⚙️ Filters", callback_data="m_filter"), InlineKeyboardButton("🔒 Locks", callback_data="m_lock")],
        [InlineKeyboardButton("🌐 Language", callback_data="m_lang")]
    ])

def mod_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔨 Ban", callback_data="cmd_ban"), InlineKeyboardButton("👢 Kick", callback_data="cmd_kick")],
        [InlineKeyboardButton("🔇 Mute", callback_data="cmd_mute"), InlineKeyboardButton("🔊 Unmute", callback_data="cmd_unmute")],
        [InlineKeyboardButton("⚠️ Warn", callback_data="cmd_warn"), InlineKeyboardButton("📌 Pin", callback_data="cmd_pin")],
        [InlineKeyboardButton("🔙 Back", callback_data="m_main")]
    ])

def fun_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Truth", callback_data="cmd_t"), InlineKeyboardButton("🔥 Dare", callback_data="cmd_d")],
        [InlineKeyboardButton("💘 Rizz", callback_data="cmd_rizz"), InlineKeyboardButton("😂 Roast", callback_data="cmd_roast")],
        [InlineKeyboardButton("🫂 Hug", callback_data="cmd_hug"), InlineKeyboardButton("👋 Slap", callback_data="cmd_slap")],
        [InlineKeyboardButton("🔙 Back", callback_data="m_main")]
    ])

def eco_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="cmd_bal"), InlineKeyboardButton("🎁 Daily", callback_data="cmd_daily")],
        [InlineKeyboardButton("🔪 Kill", callback_data="cmd_kill"), InlineKeyboardButton("🕵️ Rob", callback_data="cmd_rob")],
        [InlineKeyboardButton("🔙 Back", callback_data="m_main")]
    ])

# --- Callback Handlers ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    
    if data == "m_main": await query.edit_message_text("🛡️ <b>Aegis V10.0 Main Menu</b>", reply_markup=main_menu(), parse_mode='HTML')
    elif data == "m_mod": await query.edit_message_text("🛡️ <b>Moderation Menu</b>", reply_markup=mod_menu(), parse_mode='HTML')
    elif data == "m_fun": await query.edit_message_text("🎮 <b>Fun & Games Menu</b>", reply_markup=fun_menu(), parse_mode='HTML')
    elif data == "m_eco": await query.edit_message_text("💰 <b>Economy & Games Menu</b>", reply_markup=eco_menu(), parse_mode='HTML')
    elif data == "m_admin":
        text = "👑 <b>Admin Levels</b>\n\n<code>/promote @user 1</code> - Mod\n<code>/promote @user 2</code> - Admin\n<code>/promote @user 3</code> - Co-Owner\n<code>/demote @user</code>"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_notes":
        text = "📝 <b>Notes System</b>\n\n<code>/save name text</code>\n<code>/get name</code>\n<code>/notes</code> (List all)\n<code>/clear name</code>"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_badwords":
        text = "🚫 <b>Blacklist Words</b>\n\n<code>/addbadword gaali</code>\n<code>/delbadword gaali</code>"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_filter":
        text = "⚙️ <b>Filters (Auto-Reply)</b>\n\n<code>/addfilter hello -&gt; Hi!</code>\n<code>/delfilter hello</code>\n<code>/addsticker</code> (Reply)\n<code>/delsticker</code> (Reply)"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_lock":
        text = "🔒 <b>Group Locks</b>\n\n<code>/lock</code> / <code>/unlock</code>\n<code>/lockstickers</code> / <code>/unlockstickers</code>"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_lang":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("English 🇬🇧", callback_data="setlang_en"), InlineKeyboardButton("Hindi 🇮🇳", callback_data="setlang_hi")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_main")]
        ])
        await query.edit_message_text("🌐 <b>Select Language</b>", reply_markup=markup, parse_mode='HTML')
    elif data.startswith("setlang_"):
        lang = data.split("_")[1]
        settings_col.update_one({"chat_id": chat_id}, {"$set": {"lang": lang}}, upsert=True)
        await query.edit_message_text(LANGS[lang]["lang_changed"], reply_markup=main_menu(), parse_mode='HTML')
    elif data == "cmd_ban": await query.edit_message_text("Reply: <code>/ban</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_kick": await query.edit_message_text("Reply: <code>/kick</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_mute": await query.edit_message_text("Reply: <code>/mute</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_unmute": await query.edit_message_text("Reply: <code>/unmute</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_warn": await query.edit_message_text("Reply: <code>/warn</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_pin": await query.edit_message_text("Reply: <code>/pin</code> or <code>/unpin</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_t": await query.edit_message_text("Type: <code>/t</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_fun")]]), parse_mode='HTML')
    elif data == "cmd_d": await query.edit_message_text("Type: <code>/d</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_fun")]]), parse_mode='HTML')
    elif data == "cmd_rizz": await query.edit_message_text("Type: <code>/rizz</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_fun")]]), parse_mode='HTML')
    elif data == "cmd_roast": await query.edit_message_text("Type: <code>/roast</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_fun")]]), parse_mode='HTML')
    elif data == "cmd_hug": await query.edit_message_text("Reply: <code>/hug</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_fun")]]), parse_mode='HTML')
    elif data == "cmd_slap": await query.edit_message_text("Reply: <code>/slap</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_fun")]]), parse_mode='HTML')
    elif data == "cmd_bal": await query.edit_message_text("Type: <code>/bal</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_eco")]]), parse_mode='HTML')
    elif data == "cmd_daily": await query.edit_message_text("Type: <code>/daily</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_eco")]]), parse_mode='HTML')
    elif data == "cmd_kill": await query.edit_message_text("Reply: <code>/kill</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_eco")]]), parse_mode='HTML')
    elif data == "cmd_rob": await query.edit_message_text("Reply: <code>/rob</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_eco")]]), parse_mode='HTML')

# --- Core Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chats_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"chat_id": update.effective_chat.id}}, upsert=True)
    text = "🔥 <b>Welcome to Aegis V10.0</b> 🔥\n\nDesi Chatting, Economy aur Moderation ka perfect combo.\n\n👇 Select a category below:"
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode='HTML')

async def set_lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return await update.message.reply_text("🚫 Admin only.")
    if not context.args or context.args[0] not in ['en', 'hi']: return await update.message.reply_text("Usage: <code>/setlang en</code> or <code>/setlang hi</code>", parse_mode='HTML')
    lang = context.args[0]
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"lang": lang}}, upsert=True)
    await update.message.reply_text(LANGS[lang]["lang_changed"], parse_mode='HTML')

# --- Owner Panel ---
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return await update.message.reply_text("🚫 Owner Only Command!")
    total_chats = chats_col.count_documents({})
    text = f"👑 <b>WELCOME BOSS</b> 👑\n\n📊 <b>Total Groups:</b> {total_chats}\n💰 <b>Balance:</b> ♾️ Unlimited\n⚡ <b>Status:</b> God Mode Active\n\n<b>Commands:</b>\n<code>/broadcast &lt;msg&gt;</code>\n<code>/gban (reply)</code>"
    await update.message.reply_text(text, parse_mode='HTML')

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not context.args: return await update.message.reply_text("Usage: /broadcast message")
    msg = " ".join(context.args)
    chats = chats_col.find()
    success, fail = 0, 0
    for chat in chats:
        try:
            await context.bot.send_message(chat['chat_id'], f"📢 <b>ANNOUNCEMENT:</b>\n\n{msg}", parse_mode='HTML')
            success += 1
        except: fail += 1
    await update.message.reply_text(f"✅ Broadcast sent!\nSuccess: {success}\nFailed: {fail}")

async def gban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    target = await get_target(update, context)
    if not target: return await update.message.reply_text("Reply to a user to GBAN.")
    gbans_col.insert_one({"user_id": target.id})
    chats = chats_col.find()
    for chat in chats:
        try: await context.bot.ban_chat_member(chat['chat_id'], target.id)
        except: pass
    await update.message.reply_text(f"🔨 <b>GBANNED!</b> {target.first_name} across all groups.", parse_mode='HTML')

# --- Custom Chatting Commands ---
async def add_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return await update.message.reply_text("🚫 Admin only.")
    if len(context.args) < 2: return await update.message.reply_text("Usage: <code>/addreply trigger_word Reply text here</code>", parse_mode='HTML')
    trigger = context.args[0].lower()
    reply_text = " ".join(context.args[1:])
    chat_replies_col.update_one({"chat_id": update.effective_chat.id, "trigger": trigger}, {"$push": {"replies": reply_text}}, upsert=True)
    await update.message.reply_text(f"✅ Custom reply added for <code>{trigger}</code>!", parse_mode='HTML')

async def del_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2 or not context.args: return
    chat_replies_col.delete_one({"chat_id": update.effective_chat.id, "trigger": context.args[0].lower()})
    await update.message.reply_text(f"🗑️ Custom reply removed for <code>{context.args[0].lower()}</code>", parse_mode='HTML')

# --- Economy Commands ---
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = get_user_bal(update.effective_user.id)
    await update.message.reply_text(f"💰 <b>{update.effective_user.first_name}</b>, aapke paas <b>{bal}</b> hain.", parse_mode='HTML')

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})
    now = datetime.utcnow()
    
    if user and user.get("last_daily"):
        last_daily = user["last_daily"]
        if now - last_daily < timedelta(hours=24):
            time_left = timedelta(hours=24) - (now - last_daily)
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return await update.message.reply_text(f"⏳ Ruko bhai! Agla daily claim karne mein {hours}h {minutes}m bache hain.")
    
    update_user_bal(user_id, 500)
    users_col.update_one({"user_id": user_id}, {"$set": {"last_daily": now}}, upsert=True)
    await update.message.reply_text(f"🎁 <b>Daily Claimed!</b>\nAapko $500 mile hain. Ab total balance: {get_user_bal(user_id)}", parse_mode='HTML')

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target(update, context)
    if not target: return await update.message.reply_text("Kisko pay karna hai? Reply karo.")
    if not context.args or len(context.args) < 2:
        return await update.message.reply_text("Usage: Reply to user with `/pay 100`")
    try: amount = int(context.args[1])
    except: return await update.message.reply_text("Sahi amount daalo.")
    
    if amount <= 0: return await update.message.reply_text("Positive amount daalo.")
    
    if update.effective_user.id != OWNER_ID:
        if get_user_bal(update.effective_user.id) < amount:
            return await update.message.reply_text("❌ Aapke paas itne paise nahi hain!")
        
    update_user_bal(update.effective_user.id, -amount)
    update_user_bal(target.id, amount)
    await update.message.reply_text(f"💸 <b>Transfer Successful!</b>\n{update.effective_user.first_name} ne {target.first_name} ko ${amount} bheje.", parse_mode='HTML')

async def kill_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target(update, context)
    if not target: return await update.message.reply_text("Kisko kill karna hai? Reply karo.")
    if target.id == update.effective_user.id: return await update.message.reply_text("Khud ko kaise kill karoge? 😂")
    
    if update.effective_user.id != OWNER_ID and get_user_bal(update.effective_user.id) < 50:
        return await update.message.reply_text("❌ Attack karne ke liye $50 chahiye.")
    
    update_user_bal(update.effective_user.id, -50)
    success = random.choice([True, False])
    if success:
        gif = fetch_gif("kill") or fetch_gif("punch")
        update_user_bal(update.effective_user.id, 100)
        caption = f"☠️ <b>KILLED!</b>\n\n{update.effective_user.first_name} ne {target.first_name} ko dhamakedar tarike se maara!\n💰 Inaam: $100"
    else:
        gif = fetch_gif("cry")
        caption = f"😂 <b>MISSED!</b>\n\n{update.effective_user.first_name} ne attack kiya par {target.first_name} bach gaya!\n💸 $50 waste ho gaye."
        
    if gif: await update.message.reply_animation(animation=gif, caption=caption, parse_mode='HTML')
    else: await update.message.reply_text(caption, parse_mode='HTML')

async def rob_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target(update, context)
    if not target: return await update.message.reply_text("Kisko rob karna hai? Reply karo.")
    if target.id == update.effective_user.id: return await update.message.reply_text("Khud ko rob karoge? 🤡")
    
    if update.effective_user.id != OWNER_ID and get_user_bal(update.effective_user.id) < 20:
        return await update.message.reply_text("❌ Rob karne ke liye $20 chahiye.")
    
    update_user_bal(update.effective_user.id, -20)
    if get_user_bal(target.id) < 50:
        return await update.message.reply_text("😂 Uske paas itne paise hi nahi hain rob karne ke liye!")
    
    success = random.choice([True, False])
    if success:
        gif = fetch_gif("thief") or fetch_gif("lurk")
        stolen = 100
        update_user_bal(target.id, -stolen)
        update_user_bal(update.effective_user.id, stolen)
        caption = f"🕵️‍♂️ <b>ROBBED!</b>\n\n{update.effective_user.first_name} ne {target.first_name} ke $100 chura liye! Bhaago!"
    else:
        gif = fetch_gif("police") or fetch_gif("slap")
        update_user_bal(target.id, 20)
        caption = f"🚨 <b>CAUGHT!</b>\n\n{update.effective_user.first_name} pakda gaya! $20 ka chalan kaat kar {target.first_name} ko de diya."
        
    if gif: await update.message.reply_animation(animation=gif, caption=caption, parse_mode='HTML')
    else: await update.message.reply_text(caption, parse_mode='HTML')

# --- Moderation Commands ---
async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a message to pin.")
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await update.message.reply_text(LANGS[lang]["pinned"], parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def unpin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a message to unpin.")
    try:
        await context.bot.unpin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await update.message.reply_text(LANGS[lang]["unpinned"], parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await get_user_level(update, context)
    if role < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    if target.id == OWNER_ID: return await update.message.reply_text(LANGS[lang]["owner_protection"], parse_mode='HTML')

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        prefix = LANGS[lang]["owner_respect"] if role == 99 else ""
        caption = f"{prefix}{LANGS[lang]['banned'].format(target.first_name)}"
        if BAN_GIFS: await update.message.reply_animation(animation=random.choice(BAN_GIFS), caption=caption, parse_mode='HTML')
        else: await update.message.reply_text(caption, parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['unbanned'].format(target.first_name), parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    if target.id == OWNER_ID: return await update.message.reply_text(LANGS[lang]["owner_protection"], parse_mode='HTML')
    
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        caption = LANGS[lang]['kicked'].format(target.first_name)
        if BAN_GIFS: await update.message.reply_animation(animation=random.choice(BAN_GIFS), caption=caption, parse_mode='HTML')
        else: await update.message.reply_text(caption, parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    if target.id == OWNER_ID: return await update.message.reply_text(LANGS[lang]["owner_protection"], parse_mode='HTML')
    
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False))
        caption = LANGS[lang]['muted'].format(target.first_name)
        if MUTE_GIFS: await update.message.reply_animation(animation=random.choice(MUTE_GIFS), caption=caption, parse_mode='HTML')
        else: await update.message.reply_text(caption, parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, get_chat_permissions())
        await update.message.reply_text(LANGS[lang]['unmuted'].format(target.first_name), parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def tmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: <code>/tmute 10m</code>", parse_mode='HTML')
    time_delta = extract_time(context.args[0])
    if not time_delta: return await update.message.reply_text("❌ Invalid time. Use 10m, 1h, 1d.")
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"⏱️ {target.first_name} muted for {context.args[0]}.", parse_mode='HTML')
        context.job_queue.run_once(auto_unmute, time_delta, chat_id=update.effective_chat.id, data={'user_id': target.id})
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def tban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: <code>/tban 1d</code>", parse_mode='HTML')
    time_delta = extract_time(context.args[0])
    if not time_delta: return await update.message.reply_text("❌ Invalid time.")
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"⏱️ {target.first_name} banned for {context.args[0]}.", parse_mode='HTML')
        context.job_queue.run_once(auto_unban, time_delta, chat_id=update.effective_chat.id, data={'user_id': target.id})
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def tkick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: <code>/tkick 1h</code>", parse_mode='HTML')
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"⏱️ {target.first_name} kicked for {context.args[0]}.", parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    if target.id == OWNER_ID: return await update.message.reply_text(LANGS[lang]["owner_protection"], parse_mode='HTML')
    
    chat_id, user_id = update.effective_chat.id, target.id
    data = warnings_col.find_one({"chat_id": chat_id, "user_id": user_id})
    new_count = (data.get("count", 0) + 1) if data else 1
    if data: warnings_col.update_one({"_id": data["_id"]}, {"$set": {"count": new_count}})
    else: warnings_col.insert_one({"chat_id": chat_id, "user_id": user_id, "count": new_count})
    await update.message.reply_text(f"⚠️ {target.first_name} warned! ({new_count}/3)", parse_mode='HTML')
    if new_count >= 3:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await update.message.reply_text(f"💀 {target.first_name} banned for 3 warnings!", parse_mode='HTML')
            warnings_col.delete_one({"chat_id": chat_id, "user_id": user_id})
        except Exception: pass

async def warns_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target(update, context)
    if not target: return
    data = warnings_col.find_one({"chat_id": update.effective_chat.id, "user_id": target.id})
    count = data.get("count", 0) if data else 0
    await update.message.reply_text(f"📊 {target.first_name} has {count}/3 warnings.")

async def reset_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    target = await get_target(update, context)
    if not target: return
    warnings_col.delete_one({"chat_id": update.effective_chat.id, "user_id": target.id})
    await update.message.reply_text(f"✅ Warnings reset for {target.first_name}.")

async def purge_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not update.message.reply_to_message: return
    message_id, current_id = update.message.reply_to_message.message_id, update.message.message_id
    deleted = 0
    for msg_id in range(message_id, current_id + 1):
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            deleted += 1
        except: pass
    await context.bot.send_message(update.effective_chat.id, f"🧹 Deleted {deleted} messages.")

async def del_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 1: return
    if not update.message.reply_to_message: return
    try:
        await update.message.reply_to_message.delete()
        await update.message.delete()
    except: pass

async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    admin_tags = " ".join([f"[{a.user.first_name}](tg://user?id={a.user.id})" for a in admins if not a.user.is_bot])
    await update.message.reply_text(f"🚨 REPORT! {update.effective_user.first_name} reported {update.message.reply_to_message.from_user.first_name}!\n\n{admin_tags}", parse_mode='Markdown')

async def promote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 3: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target or len(context.args) < 2: return await update.message.reply_text("Usage: <code>/promote @user 1</code>", parse_mode='HTML')
    try: level = int(context.args[1])
    except: return await update.message.reply_text("❌ Level 1, 2 or 3.", parse_mode='HTML')
    if level not in [1, 2, 3]: return await update.message.reply_text("❌ Level 1, 2 or 3.", parse_mode='HTML')
    admins_col.update_one({"chat_id": update.effective_chat.id, "user_id": target.id}, {"$set": {"level": level}}, upsert=True)
    await update.message.reply_text(f"✅ {target.first_name} promoted to Level {level}!", parse_mode='HTML')

async def demote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 3: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    admins_col.delete_one({"chat_id": update.effective_chat.id, "user_id": target.id})
    await update.message.reply_text(f"📉 {target.first_name} demoted!", parse_mode='HTML')

# --- Fun Commands ---
async def truth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    truth = random.choice(TRUTHS)
    if target: await update.message.reply_text(f"🎯 <b>Truth for {target.first_name}:</b>\n\n{truth}", parse_mode='HTML')
    else: await update.message.reply_text(f"🎯 <b>Truth:</b>\n\n{truth}", parse_mode='HTML')

async def dare_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    dare = random.choice(DARES)
    if target: await update.message.reply_text(f"🔥 <b>Dare for {target.first_name}:</b>\n\n{dare}", parse_mode='HTML')
    else: await update.message.reply_text(f"🔥 <b>Dare:</b>\n\n{dare}", parse_mode='HTML')

async def rizz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    rizz = random.choice(RIZZ)
    if target: await update.message.reply_text(f"💘 {update.effective_user.first_name} to {target.first_name}:\n\n<i>{rizz}</i>", parse_mode='HTML')
    else: await update.message.reply_text(f"💘 <i>{rizz}</i>", parse_mode='HTML')

async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    roast = random.choice(ROASTS)
    if target: await update.message.reply_text(f"😂 <b>{target.first_name}</b>, {roast}", parse_mode='HTML')
    else: await update.message.reply_text(f"😂 {roast}", parse_mode='HTML')

async def action_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, action_name):
    if not update.message.reply_to_message: return await update.message.reply_text(f"Reply to someone with /{action_name}")
    target = update.message.reply_to_message.from_user
    user = update.effective_user.first_name
    gif_url = fetch_gif(action_name)
    caption = f"✨ <b>{user}</b> {action_name}ed <b>{target.first_name}</b>! 😂"
    if gif_url: await update.message.reply_animation(animation=gif_url, caption=caption, parse_mode='HTML')
    else: await update.message.reply_text(caption, parse_mode='HTML')

async def hug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await action_cmd(update, context, "hug")
async def slap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await action_cmd(update, context, "slap")
async def kiss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await action_cmd(update, context, "kiss")
async def punch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await action_cmd(update, context, "punch")
async def pat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await action_cmd(update, context, "pat")
async def cuddle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await action_cmd(update, context, "cuddle")
async def poke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await action_cmd(update, context, "poke")

async def dice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_dice(emoji="🎲")

async def eight_ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answers = ["Yes.", "No.", "Maybe.", "Definitely!", "Absolutely not.", "Ask again later.", "I don't know."]
    await update.message.reply_text(f"🎱 {random.choice(answers)}")

# --- Settings, Notes, Filters, Locks ---
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not update.message.reply_to_message and not context.args: return await update.message.reply_text("Reply or write text.")
    
    media_id, media_type = None, None
    if update.message.reply_to_message:
        if update.message.reply_to_message.animation: media_id, media_type = update.message.reply_to_message.animation.file_id, "animation"
        elif update.message.reply_to_message.photo: media_id, media_type = update.message.reply_to_message.photo[-1].file_id, "photo"
        elif update.message.reply_to_message.video: media_id, media_type = update.message.reply_to_message.video.file_id, "video"

    text = " ".join(context.args) if context.args else "Welcome {name}! 🎉"
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"welcome_text": text, "welcome_media": media_id, "media_type": media_type}}, upsert=True)
    await update.message.reply_text("🎉 Welcome updated!")

async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not context.args: return
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"goodbye": " ".join(context.args)}}, upsert=True)
    await update.message.reply_text("👋 Goodbye updated!")

async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not context.args: return
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"rules": " ".join(context.args)}}, upsert=True)
    await update.message.reply_text("📜 Rules updated!")

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "rules" in data: await update.message.reply_text(f"📜 <b>Rules:</b>\n{data['rules']}", parse_mode='HTML')
    else: await update.message.reply_text("❌ No rules set.")

async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if len(context.args) < 2: return await update.message.reply_text("Usage: <code>/save name text</code>", parse_mode='HTML')
    notes_col.update_one({"chat_id": update.effective_chat.id, "name": context.args[0].lower()}, {"$set": {"text": " ".join(context.args[1:])}}, upsert=True)
    await update.message.reply_text(f"✅ Note <code>{context.args[0].lower()}</code> saved!", parse_mode='HTML')

async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    data = notes_col.find_one({"chat_id": update.effective_chat.id, "name": context.args[0].lower()})
    if data: await update.message.reply_text(data['text'])
    else: await update.message.reply_text("❌ Note not found.", parse_mode='HTML')

async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = notes_col.find({"chat_id": update.effective_chat.id})
    text = "📝 <b>Saved Notes:</b>\n" + "\n".join([f"• <code>{n['name']}</code>" for n in notes])
    await update.message.reply_text(text if notes.count() > 0 else "❌ No notes saved.", parse_mode='HTML')

async def clear_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not context.args: return
    notes_col.delete_one({"chat_id": update.effective_chat.id, "name": context.args[0].lower()})
    await update.message.reply_text(f"🗑️ Note deleted.")

async def add_badword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2 or not context.args: return
    badwords_col.update_one({"chat_id": update.effective_chat.id, "word": context.args[0].lower()}, {"$set": {"word": context.args[0].lower()}}, upsert=True)
    await update.message.reply_text(f"✅ <code>{context.args[0].lower()}</code> blacklisted.", parse_mode='HTML')

async def del_badword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2 or not context.args: return
    badwords_col.delete_one({"chat_id": update.effective_chat.id, "word": context.args[0].lower()})
    await update.message.reply_text(f"🗑️ <code>{context.args[0].lower()}</code> removed.", parse_mode='HTML')

async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if "->" not in update.message.text: return await update.message.reply_text("Format: <code>/addfilter hello -&gt; Hi!</code>", parse_mode='HTML')
    parts = update.message.text.split("->", 1)
    trigger = parts[0].replace("/addfilter", "").strip().lower()
    filters_col.update_one({"chat_id": update.effective_chat.id, "trigger": trigger}, {"$set": {"reply": parts[1].strip()}}, upsert=True)
    await update.message.reply_text(f"✅ Filter added for <code>{trigger}</code>", parse_mode='HTML')

async def del_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2 or not context.args: return
    filters_col.delete_one({"chat_id": update.effective_chat.id, "trigger": context.args[0].lower()})
    await update.message.reply_text(f"🗑️ Filter removed for <code>{context.args[0].lower()}</code>", parse_mode='HTML')

async def add_sticker_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not update.message.reply_to_message or not update.message.reply_to_message.sticker: return await update.message.reply_text("Reply to a sticker.")
    sticker_filters_col.update_one({"chat_id": update.effective_chat.id, "sticker_id": update.message.reply_to_message.sticker.file_unique_id}, {"$set": {"reply": "Sticker detected! 🖼️"}}, upsert=True)
    await update.message.reply_text("🖼️ Sticker filter added!")

async def del_sticker_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not update.message.reply_to_message or not update.message.reply_to_message.sticker: return await update.message.reply_text("Reply to a sticker.")
    sticker_filters_col.delete_one({"chat_id": update.effective_chat.id, "sticker_id": update.message.reply_to_message.sticker.file_unique_id})
    await update.message.reply_text("🗑️ Sticker filter removed!")

async def lock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text("🔒 Group Locked!")
    except Exception: pass

async def unlock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, get_chat_permissions())
        await update.message.reply_text("🔓 Group Unlocked!")
    except Exception: pass

async def lock_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"stickers_locked": True}}, upsert=True)
    await update.message.reply_text("🔒 Stickers Locked!")

async def unlock_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"stickers_locked": False}}, upsert=True)
    await update.message.reply_text("🔓 Stickers Unlocked!")

async def set_afk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = " ".join(context.args) if context.args else "No reason"
    afk_col.update_one({"chat_id": update.effective_chat.id, "user_id": update.effective_user.id}, {"$set": {"reason": reason}}, upsert=True)
    await update.message.reply_text(f"💤 {update.effective_user.first_name} is now AFK: {reason}")

# --- Message Handlers ---
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        welcome = data.get("welcome_text", "Welcome {name}! 👋").replace("{name}", member.first_name) if data else f"Welcome {member.first_name}! 👋"
        media = data.get("welcome_media") if data else None
        media_type = data.get("media_type") if data else None
        
        if media and media_type == "animation": await update.message.reply_animation(animation=media, caption=welcome)
        elif media and media_type == "photo": await update.message.reply_photo(photo=media, caption=welcome)
        elif media and media_type == "video": await update.message.reply_video(video=media, caption=welcome)
        else: await update.message.reply_text(welcome)
        
        if data and "rules" in data: await update.message.reply_text(f"📜 <b>Rules:</b>\n{data['rules']}", parse_mode='HTML')

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "goodbye" in data:
        await update.message.reply_text(data['goodbye'].replace("{name}", update.message.left_chat_member.first_name))

async def handle_chatting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.lower()
    
    db_reply = chat_replies_col.find_one({"chat_id": update.effective_chat.id, "trigger": text})
    if db_reply and db_reply.get("replies"):
        return await update.message.reply_text(random.choice(db_reply["replies"]))
        
    for trigger, replies in CHAT_DATA.items():
        if re.search(r'\b' + re.escape(trigger) + r'\b', text) or text == trigger:
            if random.random() < 0.4:
                return await update.message.reply_text(random.choice(replies))

async def handle_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = settings_col.find_one({"chat_id": chat_id})
    
    if data and data.get("stickers_locked", False):
        if await get_user_level(update, context) < 1:
            try:
                await update.message.delete()
                await update.message.reply_text("🔒 Stickers locked!")
            except: pass
            return
            
    sticker_replies = [
        "Ye kya bhej diya bhai? 😂", "Meme bhejna tha, sticker nahi.", 
        "Sticker kha jaunga. 🍔", "Bhai thoda sharam kar, sticker mat bhej.",
        "Arre wah, sundar sticker. 🙄", "Isse accha toh mera code hai."
    ]
    if random.random() < 0.3:
        await update.message.reply_text(random.choice(sticker_replies))
        
    sticker_id = update.message.sticker.file_unique_id
    sfilter = sticker_filters_col.find_one({"chat_id": chat_id, "sticker_id": sticker_id})
    if sfilter: await update.message.reply_text(sfilter['reply'])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id, user_id = update.effective_chat.id, update.effective_user.id
    text = update.message.text.lower()

    if await get_user_level(update, context) < 1:
        if "http://" in text or "https://" in text or "t.me/" in text:
            try:
                await update.message.delete()
                await update.message.reply_text(f"⚠️ {update.effective_user.first_name}, links allowed nahi hain! 🚫")
                return
            except: pass

# --- Main App ---
async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Start Bot"), BotCommand("balance", "Check Money"), BotCommand("daily", "Claim Daily $500"),
        BotCommand("kill", "Kill user (Costs $50)"), BotCommand("rob", "Rob user (Costs $20)"),
        BotCommand("ban", "Ban"), BotCommand("kick", "Kick"), BotCommand("mute", "Mute"),
        BotCommand("t", "Truth"), BotCommand("d", "Dare"), BotCommand("roast", "Roast"),
        BotCommand("hug", "Hug"), BotCommand("slap", "Slap"), BotCommand("addreply", "Teach bot a reply")
    ]
    await application.bot.set_my_commands(commands)

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("setlang", set_lang_cmd))
    app.add_handler(CommandHandler("owner", owner_panel))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("gban", gban_user))
    
    app.add_handler(CommandHandler("addreply", add_reply))
    app.add_handler(CommandHandler("delreply", del_reply))
    
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("bal", balance))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("kill", kill_user))
    app.add_handler(CommandHandler("rob", rob_user))
    
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("tmute", tmute_user))
    app.add_handler(CommandHandler("tban", tban_user))
    app.add_handler(CommandHandler("tkick", tkick_user))
    app.add_handler(CommandHandler("pin", pin_message))
    app.add_handler(CommandHandler("unpin", unpin_message))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("warns", warns_check))
    app.add_handler(CommandHandler("resetwarns", reset_warns))
    app.add_handler(CommandHandler("purge", purge_messages))
    app.add_handler(CommandHandler("del", del_message))
    app.add_handler(CommandHandler("report", report_user))
    app.add_handler(CommandHandler("promote", promote_user))
    app.add_handler(CommandHandler("demote", demote_user))
    
    app.add_handler(CommandHandler("t", truth_cmd))
    app.add_handler(CommandHandler("d", dare_cmd))
    app.add_handler(CommandHandler("rizz", rizz_cmd))
    app.add_handler(CommandHandler("roast", roast_cmd))
    app.add_handler(CommandHandler("hug", hug_cmd))
    app.add_handler(CommandHandler("slap", slap_cmd))
    app.add_handler(CommandHandler("kiss", kiss_cmd))
    app.add_handler(CommandHandler("punch", punch_cmd))
    app.add_handler(CommandHandler("pat", pat_cmd))
    app.add_handler(CommandHandler("cuddle", cuddle_cmd))
    app.add_handler(CommandHandler("poke", poke_cmd))
    app.add_handler(CommandHandler("dice", dice_cmd))
    app.add_handler(CommandHandler("8ball", eight_ball))
    
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("setgoodbye", set_goodbye))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("rules", show_rules))
    app.add_handler(CommandHandler("save", save_note))
    app.add_handler(CommandHandler("get", get_note))
    app.add_handler(CommandHandler("notes", list_notes))
    app.add_handler(CommandHandler("clear", clear_note))
    app.add_handler(CommandHandler("addbadword", add_badword))
    app.add_handler(CommandHandler("delbadword", del_badword))
    app.add_handler(CommandHandler("addfilter", add_filter))
    app.add_handler(CommandHandler("delfilter", del_filter))
    app.add_handler(CommandHandler("addsticker", add_sticker_filter))
    app.add_handler(CommandHandler("delsticker", del_sticker_filter))
    app.add_handler(CommandHandler("lock", lock_group))
    app.add_handler(CommandHandler("unlock", unlock_group))
    app.add_handler(CommandHandler("lockstickers", lock_stickers))
    app.add_handler(CommandHandler("unlockstickers", unlock_stickers))
    app.add_handler(CommandHandler("afk", set_afk))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_stickers))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chatting))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Aegis V10.0 (Bro Mode) running perfectly...")
    app.run_polling()

if __name__ == '__main__':
    main()
