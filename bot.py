import os
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from pymongo import MongoClient

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

# --- Anti-Spam Memory ---
sticker_spam_tracker = defaultdict(list)

# --- Languages ---
LANGS = {
    "en": {
        "denied": "🚫 <b>Access Denied!</b> You don't have enough permissions.",
        "owner_respect": "👑 <b>Yes, Boss!</b> Your wish is my command. ⚡",
        "coowner_respect": "⭐ <b>Yes, Co-Owner!</b> Executing command. ⚡",
        "user_not_found": "❌ <b>Target not found!</b> Please reply to their message.",
        "banned": "🔨 <b>BANNED!</b> {} removed. 🚫",
        "unbanned": "🕊️ {} unbanned. ✅",
        "kicked": "👢 <b>KICKED!</b> {} removed. 🚪",
        "muted": "🔇 <b>MUTED!</b> {} silenced. 🤐",
        "unmuted": "🔊 <b>UNMUTED!</b> {} can speak. 🗣️",
        "tmute_set": "⏱️ {} muted for {}. 🔇",
        "tban_set": "⏱️ {} banned for {}. 🔨",
        "tkick_set": "⏱️ {} kicked for {}. 👢",
        "khatarnak_warn": "☠️ <b>KHATRA!</b> ☠️\n\n⚠️ {} has received a warning!\n🚨 <b>Warning Count:</b> {}/3\n\nNext time, BAN! 💀",
        "khatarnak_ban": "💀 <b>GAME OVER!</b> 💀\n\n🚫 {} banned for 3 warnings. ☠️",
        "lang_changed": "🌐 Language changed to English! 🇬🇧",
        "promoted": "✅ {} promoted to <b>Level {}</b>! 🎖️",
        "demoted": "📉 {} demoted to normal user. 🚫",
        "sticker_mute": "🚨 <b>SPAM!</b> {} sent too many stickers. Muted for 10m! 🤐",
        "sticker_lock": "🔒 Stickers are locked here. 🖼️",
        "admin_error": "⚠️ <b>Error:</b> I cannot perform this action. The user might be an Admin or I lack permissions.",
        "bot_admin_error": "⚠️ <b>Error:</b> I need to be an Admin with 'Restrict Members' permission to do this.",
    },
    "hi": {
        "denied": "🚫 <b>Permission nahi hai!</b> Aapke paas power nahi hai.",
        "owner_respect": "👑 <b>Ji Huzoor!</b> Aapka hukum sar aankhon par. ⚡",
        "coowner_respect": "⭐ <b>Ji Co-Owner!</b> Aapka hukum sar aankhon par. ⚡",
        "user_not_found": "❌ <b>Target nahi mila!</b> Kripya uske message par Reply karein.",
        "banned": "🔨 <b>BANNED!</b> {} ko ban kar diya. 🚫",
        "unbanned": "🕊️ {} ko unban kar diya. ✅",
        "kicked": "👢 <b>KICKED!</b> {} ko nikal diya. 🚪",
        "muted": "🔇 <b>MUTED!</b> {} ab nahi bol sakta. 🤐",
        "unmuted": "🔊 <b>UNMUTED!</b> {} ab bol sakta hai. 🗣️",
        "tmute_set": "⏱️ {} ko {} ke liye mute kiya. 🔇",
        "tban_set": "⏱️ {} ko {} ke liye ban kiya. 🔨",
        "tkick_set": "⏱️ {} ko {} ke liye kick kiya. 👢",
        "khatarnak_warn": "☠️ <b>KHATRA!</b> ☠️\n\n⚠️ {} ko warning mili!\n🚨 <b>Warning:</b> {}/3\n\nAgli baar BAN! 💀",
        "khatarnak_ban": "💀 <b>GAME OVER!</b> 💀\n\n🚫 {} ko 3 warnings par BAN kiya. ☠️",
        "lang_changed": "🌐 Language Hindi mein badli! 🇮🇳",
        "promoted": "✅ {} ko <b>Level {}</b> ka admin banaya! 🎖️",
        "demoted": "📉 {} ko demote kiya gaya. 🚫",
        "sticker_mute": "🚨 <b>SPAM!</b> {} ne bahut stickers bheje. 10m mute! 🤐",
        "sticker_lock": "🔒 Stickers band hain is group mein. 🖼️",
        "admin_error": "⚠️ <b>Error:</b> Main ye nahi kar sakta. Ho sakta hai user Admin ho ya mere paas permission na ho.",
        "bot_admin_error": "⚠️ <b>Error:</b> Mujhe Admin banao aur 'Restrict Members' ki permission do.",
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

async def auto_unmute(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.restrict_chat_member(job.chat_id, job.data['user_id'], ChatPermissions.all_permissions())
    except: pass

async def auto_unban(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.unban_chat_member(job.chat_id, job.data['user_id'])
    except: pass

# --- Keyboards ---
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡️ Moderation", callback_data="m_mod"), InlineKeyboardButton("👑 Admin Levels", callback_data="m_admin")],
        [InlineKeyboardButton("🎉 Greetings", callback_data="m_greet"), InlineKeyboardButton("⚙️ Filters", callback_data="m_filter")],
        [InlineKeyboardButton("🔒 Locks", callback_data="m_lock"), InlineKeyboardButton("🌐 Language", callback_data="m_lang")],
        [InlineKeyboardButton("📚 Full Help", callback_data="m_help")]
    ])

def mod_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔨 Ban", callback_data="cmd_ban"), InlineKeyboardButton("👢 Kick", callback_data="cmd_kick")],
        [InlineKeyboardButton("🔇 Mute", callback_data="cmd_mute"), InlineKeyboardButton("🔊 Unmute", callback_data="cmd_unmute")],
        [InlineKeyboardButton("⏱️ Tmute", callback_data="cmd_tmute"), InlineKeyboardButton("⚠️ Warn", callback_data="cmd_warn")],
        [InlineKeyboardButton("🔙 Back", callback_data="m_main")]
    ])

# --- Callback Handlers ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    
    if data == "m_main":
        await query.edit_message_text("🛡️ <b>Aegis V3.0 Main Menu</b>\nChoose a category:", reply_markup=main_menu(), parse_mode='HTML')
    elif data == "m_mod":
        await query.edit_message_text("🛡️ <b>Moderation Menu</b>\nTap a button to see how to use it:", reply_markup=mod_menu(), parse_mode='HTML')
    elif data == "m_admin":
        text = "👑 <b>Admin Levels</b>\n\n<code>/promote @user 1</code> - Mod (Mute/Warn)\n<code>/promote @user 2</code> - Admin (Ban/Kick)\n<code>/promote @user 3</code> - Co-Owner (All rights)\n<code>/demote @user</code> - Remove Admin"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_greet":
        text = "🎉 <b>Greetings</b>\n\n<code>/setwelcome &lt;text&gt;</code> - Set Welcome\n<code>/setgoodbye &lt;text&gt;</code> - Set Goodbye\n<code>/setrules &lt;text&gt;</code> - Set Rules\n<code>/rules</code> - Show Rules\n\n<i>Tip: Reply to a Photo/GIF with /setwelcome to set media!</i>"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_filter":
        text = "⚙️ <b>Filters (Auto-Reply)</b>\n\n<code>/addfilter hello -&gt; Hi!</code>\n<code>/delfilter hello</code>\n<code>/addsticker</code> (Reply to sticker)"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='HTML')
    elif data == "m_lock":
        text = "🔒 <b>Group Locks</b>\n\n<code>/lock</code> - Lock group (admins only)\n<code>/unlock</code> - Unlock group\n<code>/lockstickers</code> - Block stickers\n<code>/unlockstickers</code> - Allow stickers"
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
        await query.answer(LANGS[lang]["lang_changed"], show_alert=True)
        await query.edit_message_text("🛡️ <b>Aegis Main Menu</b>", reply_markup=main_menu(), parse_mode='HTML')
    elif data == "m_help":
        text = "📚 <b>Aegis V3.0</b>\n\nUse buttons to explore.\n👑 <b>Creator:</b> Aman"
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='HTML')
    
    # Command Usage Callbacks
    elif data == "cmd_ban": await query.edit_message_text("🔨 <b>Ban User</b>\nReply to user: <code>/ban</code>\nBy Username: <code>/ban @username</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_kick": await query.edit_message_text("👢 <b>Kick User</b>\nReply to user: <code>/kick</code>\nBy Username: <code>/kick @username</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_mute": await query.edit_message_text("🔇 <b>Mute User</b>\nReply to user: <code>/mute</code>\nBy Username: <code>/mute @username</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_unmute": await query.edit_message_text("🔊 <b>Unmute User</b>\nReply to user: <code>/unmute</code>\nBy Username: <code>/unmute @username</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_tmute": await query.edit_message_text("⏱️ <b>Temporary Mute</b>\nReply to user: <code>/tmute 10m</code>\nTime formats: 10m, 1h, 1d", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')
    elif data == "cmd_warn": await query.edit_message_text("⚠️ <b>Warn User</b>\nReply to user: <code>/warn</code>\n3 Warnings = Auto Ban!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_mod")]]), parse_mode='HTML')

# --- Core Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🔥 <b>Welcome to Aegis V3.0</b> 🔥\n\nThe most advanced group manager is now live.\n\n👇 Select a category below:"
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode='HTML')

# --- Moderation ---
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await get_user_level(update, context)
    if role < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        prefix = LANGS[lang]["owner_respect"] + "\n\n" if role == 99 else (LANGS[lang]["coowner_respect"] + "\n\n" if role == 3 else "")
        await update.message.reply_text(f"{prefix}{LANGS[lang]['banned'].format(target.first_name)}", parse_mode='HTML')
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
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['kicked'].format(target.first_name), parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(LANGS[lang]['muted'].format(target.first_name), parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    try:
        # Fixed: Using ALL permissions to ensure Telegram unmutes properly
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions.all_permissions())
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
        await update.message.reply_text(LANGS[lang]['tmute_set'].format(target.first_name, context.args[0]), parse_mode='HTML')
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
        await update.message.reply_text(LANGS[lang]['tban_set'].format(target.first_name, context.args[0]), parse_mode='HTML')
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
        await update.message.reply_text(LANGS[lang]['tkick_set'].format(target.first_name, context.args[0]), parse_mode='HTML')
    except Exception: await update.message.reply_text(LANGS[lang]["admin_error"], parse_mode='HTML')

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    chat_id, user_id = update.effective_chat.id, target.id
    data = warnings_col.find_one({"chat_id": chat_id, "user_id": user_id})
    new_count = (data.get("count", 0) + 1) if data else 1
    if data: warnings_col.update_one({"_id": data["_id"]}, {"$set": {"count": new_count}})
    else: warnings_col.insert_one({"chat_id": chat_id, "user_id": user_id, "count": new_count})
    await update.message.reply_text(LANGS[lang]['khatarnak_warn'].format(target.first_name, new_count), parse_mode='HTML')
    if new_count >= 3:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await update.message.reply_text(LANGS[lang]['khatarnak_ban'].format(target.first_name), parse_mode='HTML')
            warnings_col.delete_one({"chat_id": chat_id, "user_id": user_id})
        except Exception: pass

# --- Admin Levels ---
async def promote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 3: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target or len(context.args) < 2: return await update.message.reply_text("Usage: <code>/promote @user 1</code>", parse_mode='HTML')
    try: level = int(context.args[1])
    except: return await update.message.reply_text("❌ Level 1, 2 or 3.", parse_mode='HTML')
    if level not in [1, 2, 3]: return await update.message.reply_text("❌ Level 1, 2 or 3.", parse_mode='HTML')
    admins_col.update_one({"chat_id": update.effective_chat.id, "user_id": target.id}, {"$set": {"level": level}}, upsert=True)
    await update.message.reply_text(LANGS[lang]["promoted"].format(target.first_name, level), parse_mode='HTML')

async def demote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 3: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"], parse_mode='HTML')
    admins_col.delete_one({"chat_id": update.effective_chat.id, "user_id": target.id})
    await update.message.reply_text(LANGS[lang]["demoted"].format(target.first_name), parse_mode='HTML')

# --- Settings & Filters ---
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return await update.message.reply_text("🚫 Admin only.")
    if not update.message.reply_to_message and not context.args: return await update.message.reply_text("Reply or write text.")
    media_id = update.message.reply_to_message.animation.file_id if update.message.reply_to_message and update.message.reply_to_message.animation else None
    text = " ".join(context.args) if context.args else "Welcome {name}! 🎉"
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"welcome_text": text, "welcome_media": media_id}}, upsert=True)
    await update.message.reply_text("🎉 Welcome updated!")

async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not context.args: return await update.message.reply_text("Usage: <code>/setgoodbye Goodbye {name}</code>", parse_mode='HTML')
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

async def add_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if "->" not in update.message.text: return await update.message.reply_text("Format: <code>/addfilter hello -&gt; Hi!</code>", parse_mode='HTML')
    parts = update.message.text.split("->", 1)
    trigger = parts[0].replace("/addfilter", "").strip().lower()
    filters_col.update_one({"chat_id": update.effective_chat.id, "trigger": trigger}, {"$set": {"reply": parts[1].strip()}}, upsert=True)
    await update.message.reply_text(f"✅ Filter added for <code>{trigger}</code>", parse_mode='HTML')

async def add_sticker_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not update.message.reply_to_message or not update.message.reply_to_message.sticker: return await update.message.reply_text("Reply to a sticker.")
    sticker_filters_col.update_one({"chat_id": update.effective_chat.id, "sticker_id": update.message.reply_to_message.sticker.file_unique_id}, {"$set": {"reply": "Sticker detected! 🖼️"}}, upsert=True)
    await update.message.reply_text("🖼️ Sticker filter added!")

# --- Locks & Anti-Spam ---
async def lock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text("🔒 Group Locked!")
    except Exception: await update.message.reply_text(LANGS[lang]["bot_admin_error"], parse_mode='HTML')

async def unlock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"], parse_mode='HTML')
    try:
        # Fixed: Using ALL permissions
        await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions.all_permissions())
        await update.message.reply_text("🔓 Group Unlocked!")
    except Exception: await update.message.reply_text(LANGS[lang]["bot_admin_error"], parse_mode='HTML')

async def lock_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"stickers_locked": True}}, upsert=True)
    await update.message.reply_text("🔒 Stickers Locked!")

async def unlock_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"stickers_locked": False}}, upsert=True)
    await update.message.reply_text("🔓 Stickers Unlocked!")

# --- Message Catchers ---
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        welcome = data.get("welcome_text", "Welcome {name}! 👋").replace("{name}", member.first_name) if data else f"Welcome {member.first_name}! 👋"
        media = data.get("welcome_media") if data else None
        if media: await update.message.reply_animation(animation=media, caption=welcome)
        else: await update.message.reply_text(welcome)
        if data and "rules" in data: await update.message.reply_text(f"📜 <b>Rules:</b>\n{data['rules']}", parse_mode='HTML')

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "goodbye" in data:
        await update.message.reply_text(data['goodbye'].replace("{name}", update.message.left_chat_member.first_name))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.lower()
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1:
        if "http://" in text or "https://" in text or "t.me/" in text:
            try:
                await update.message.delete()
                await update.message.reply_text(f"⚠️ {update.effective_user.first_name}, links allowed nahi hain! 🚫")
                return
            except: pass
    if text in ["hello", "hi", "hey"] and not update.message.reply_to_message:
        return await update.message.reply_text(f"Hello {update.effective_user.first_name}! 😊")
    data = filters_col.find_one({"chat_id": update.effective_chat.id, "trigger": text})
    if data: await update.message.reply_text(data['reply'])

async def handle_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_lang(chat_id)
    data = settings_col.find_one({"chat_id": chat_id})
    if data and data.get("stickers_locked", False):
        if await get_user_level(update, context) < 1:
            try:
                await update.message.delete()
                await update.message.reply_text(LANGS[lang]["sticker_lock"], parse_mode='HTML')
            except: pass
            return
    if await get_user_level(update, context) < 1:
        now = datetime.now()
        user_stickers = sticker_spam_tracker[(chat_id, user_id)]
        user_stickers = [t for t in user_stickers if (now - t).total_seconds() < 60]
        if len(user_stickers) >= 9:
            try:
                await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False))
                await update.message.reply_text(LANGS[lang]["sticker_mute"].format(update.effective_user.first_name), parse_mode='HTML')
                sticker_spam_tracker[(chat_id, user_id)] = []
                context.job_queue.run_once(auto_unmute, timedelta(minutes=10), chat_id=chat_id, data={'user_id': user_id})
            except: pass
        else:
            user_stickers.append(now)
            sticker_spam_tracker[(chat_id, user_id)] = user_stickers
    sticker_id = update.message.sticker.file_unique_id
    sfilter = sticker_filters_col.find_one({"chat_id": chat_id, "sticker_id": sticker_id})
    if sfilter: await update.message.reply_text(sfilter['reply'])

# --- Info & Utility ---
async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not update.message.reply_to_message: return
    await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
    await update.message.reply_text("📌 Pinned!")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        await update.message.reply_text(f"👤 User: <code>{update.message.reply_to_message.from_user.id}</code>\n💬 Chat: <code>{update.effective_chat.id}</code>", parse_mode='HTML')
    else:
        await update.message.reply_text(f"💬 Chat: <code>{update.effective_chat.id}</code>", parse_mode='HTML')

# --- Post Init (To set BotFather Commands) ---
async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Start the bot & show menu"),
        BotCommand("help", "Get help menu"),
        BotCommand("ban", "Ban a user (reply)"),
        BotCommand("unban", "Unban a user"),
        BotCommand("kick", "Kick a user (reply)"),
        BotCommand("mute", "Mute a user (reply)"),
        BotCommand("unmute", "Unmute a user (reply)"),
        BotCommand("tmute", "Temporary mute (10m, 1h)"),
        BotCommand("warn", "Warn a user (3 = ban)"),
        BotCommand("promote", "Promote user (Level 1/2/3)"),
        BotCommand("demote", "Demote user"),
        BotCommand("rules", "Show group rules"),
        BotCommand("id", "Get user/chat ID")
    ]
    await application.bot.set_my_commands(commands)

# --- Main App ---
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    # post_init adds the command menu on startup
    app = Application.builder().token(token).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("tmute", tmute_user))
    app.add_handler(CommandHandler("tban", tban_user))
    app.add_handler(CommandHandler("tkick", tkick_user))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("promote", promote_user))
    app.add_handler(CommandHandler("demote", demote_user))
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("setgoodbye", set_goodbye))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("rules", show_rules))
    app.add_handler(CommandHandler("addfilter", add_text_filter))
    app.add_handler(CommandHandler("addsticker", add_sticker_filter))
    app.add_handler(CommandHandler("lock", lock_group))
    app.add_handler(CommandHandler("unlock", unlock_group))
    app.add_handler(CommandHandler("lockstickers", lock_stickers))
    app.add_handler(CommandHandler("unlockstickers", unlock_stickers))
    app.add_handler(CommandHandler("pin", pin_message))
    app.add_handler(CommandHandler("id", get_id))

    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_stickers))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Aegis ULTRA V3.0 running perfectly...")
    app.run_polling()

if __name__ == '__main__':
    main()
