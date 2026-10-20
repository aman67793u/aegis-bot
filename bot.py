import os
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
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
        "denied": "🚫 Access Denied! You don't have enough permissions.",
        "owner_respect": "👑 Yes, Boss! Your wish is my command. ⚡",
        "coowner_respect": "⭐ Yes, Co-Owner! Executing command. ⚡",
        "user_not_found": "❌ Target not found! Please **Reply** to their message.",
        "banned": "🔨 BANNED! {} removed. 🚫",
        "unbanned": "🕊️ {} unbanned. ✅",
        "kicked": "👢 KICKED! {} removed. 🚪",
        "muted": "🔇 MUTED! {} silenced. 🤐",
        "unmuted": "🔊 UNMUTED! {} can speak. 🗣️",
        "tmute_set": "⏱️ {} muted for {}. 🔇",
        "tban_set": "⏱️ {} banned for {}. 🔨",
        "tkick_set": "⏱️ {} kicked for {}. 👢",
        "khatarnak_warn": "☠️ KHATRA! ☠️\n\n⚠️ {} has received a warning!\n🚨 Warning Count: {}/3\n\nNext time, BAN! 💀",
        "khatarnak_ban": "💀 GAME OVER! 💀\n\n🚫 {} banned for 3 warnings. ☠️",
        "lang_changed": "🌐 Language changed to English! 🇬🇧",
        "promoted": "✅ {} promoted to **Level {}**! 🎖️",
        "demoted": "📉 {} demoted to normal user. 🚫",
        "sticker_mute": "🚨 **SPAM!** {} sent too many stickers. Muted for 10m! 🤐",
        "sticker_lock": "🔒 Stickers are locked here. 🖼️",
    },
    "hi": {
        "denied": "🚫 Permission nahi hai! Aapke paas power nahi hai.",
        "owner_respect": "👑 Ji Huzoor! Aapka hukum sar aankhon par. ⚡",
        "coowner_respect": "⭐ Ji Co-Owner! Aapka hukum sar aankhon par. ⚡",
        "user_not_found": "❌ Target nahi mila! Kripya uske message par **Reply** karein.",
        "banned": "🔨 BANNED! {} ko ban kar diya. 🚫",
        "unbanned": "🕊️ {} ko unban kar diya. ✅",
        "kicked": "👢 KICKED! {} ko nikal diya. 🚪",
        "muted": "🔇 MUTED! {} ab nahi bol sakta. 🤐",
        "unmuted": "🔊 UNMUTED! {} ab bol sakta hai. 🗣️",
        "tmute_set": "⏱️ {} ko {} ke liye mute kiya. 🔇",
        "tban_set": "⏱️ {} ko {} ke liye ban kiya. 🔨",
        "tkick_set": "⏱️ {} ko {} ke liye kick kiya. 👢",
        "khatarnak_warn": "☠️ KHATRA! ☠️\n\n⚠️ {} ko warning mili!\n🚨 Warning: {}/3\n\nAgli baar BAN! 💀",
        "khatarnak_ban": "💀 GAME OVER! 💀\n\n🚫 {} ko 3 warnings par BAN kiya. ☠️",
        "lang_changed": "🌐 Language Hindi mein badli! 🇮🇳",
        "promoted": "✅ {} ko **Level {}** ka admin banaya! 🎖️",
        "demoted": "📉 {} ko demote kiya gaya. 🚫",
        "sticker_mute": "🚨 **SPAM!** {} ne bahut stickers bheje. 10m mute! 🤐",
        "sticker_lock": "🔒 Stickers band hain is group mein. 🖼️",
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
        await context.bot.restrict_chat_member(job.chat_id, job.data['user_id'], ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
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
        [InlineKeyboardButton("🎉 Greetings", callback_data="m_greet"), InlineKeyboardButton("⚙️ Filters & Notes", callback_data="m_filter")],
        [InlineKeyboardButton("🔒 Locks", callback_data="m_lock"), InlineKeyboardButton("🌐 Language", callback_data="m_lang")],
        [InlineKeyboardButton("📚 Full Help", callback_data="m_help")]
    ])

def mod_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔨 Ban", callback_data="help_ban"), InlineKeyboardButton("👢 Kick", callback_data="help_kick")],
        [InlineKeyboardButton("🔇 Mute", callback_data="help_mute"), InlineKeyboardButton("🔊 Unmute", callback_data="help_unmute")],
        [InlineKeyboardButton("⏱️ Tmute", callback_data="help_tmute"), InlineKeyboardButton("⚠️ Warn", callback_data="help_warn")],
        [InlineKeyboardButton("🔙 Back", callback_data="m_main")]
    ])

# --- Callback Handlers (Buttons) ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    
    if data == "m_main":
        await query.edit_message_text("🛡️ **Aegis Main Menu**\nChoose a category:", reply_markup=main_menu(), parse_mode='Markdown')
    
    elif data == "m_mod":
        await query.edit_message_text("🛡️ **Moderation Menu**\nHere are the commands for this category:", reply_markup=mod_menu(), parse_mode='Markdown')
    
    elif data == "m_admin":
        text = "👑 **Admin Levels**\n\n`/promote @user 1` - Mod (Mute/Warn)\n`/promote @user 2` - Admin (Ban/Kick)\n`/promote @user 3` - Co-Owner (All rights)\n`/demote @user` - Remove Admin\n\n*Only Co-Owner/Owner can promote.*"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='Markdown')
    
    elif data == "m_greet":
        text = "🎉 **Greetings**\n\n`/setwelcome <text>` - Set Welcome\n`/setgoodbye <text>` - Set Goodbye\n`/setrules <text>` - Set Rules\n`/rules` - Show Rules\n\n*Tip: Reply to a GIF to set media welcome!*"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='Markdown')
    
    elif data == "m_filter":
        text = "⚙️ **Filters (Auto-Reply)**\n\n`/addfilter hello -> Hi!`\n`/delfilter hello`\n`/addsticker` (Reply to sticker)\n`/delsticker` (Reply to sticker)"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='Markdown')
    
    elif data == "m_lock":
        text = "🔒 **Group Locks**\n\n`/lock` - Lock group (admins only)\n`/unlock` - Unlock group\n`/lockstickers` - Block stickers\n`/unlockstickers` - Allow stickers"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="m_main")]]), parse_mode='Markdown')
    
    elif data == "m_lang":
        text = "🌐 **Select Language**"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("English 🇬🇧", callback_data="setlang_en"), InlineKeyboardButton("Hindi 🇮🇳", callback_data="setlang_hi")],
            [InlineKeyboardButton("🔙 Back", callback_data="m_main")]
        ])
        await query.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')
    
    elif data.startswith("setlang_"):
        lang = data.split("_")[1]
        settings_col.update_one({"chat_id": chat_id}, {"$set": {"lang": lang}}, upsert=True)
        await query.answer(LANGS[lang]["lang_changed"], show_alert=True)
        await query.edit_message_text("🛡️ **Aegis Main Menu**", reply_markup=main_menu(), parse_mode='Markdown')
    
    elif data == "m_help":
        text = "📚 **Aegis - The Ultimate Bot**\n\nUse the buttons below to explore.\n\n👑 **Creator:** Aman"
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
    # Help command details
    elif data == "help_ban": await query.answer("Usage: /ban (reply to user)", show_alert=True)
    elif data == "help_kick": await query.answer("Usage: /kick (reply to user)", show_alert=True)
    elif data == "help_mute": await query.answer("Usage: /mute (reply to user)", show_alert=True)
    elif data == "help_unmute": await query.answer("Usage: /unmute (reply to user)", show_alert=True)
    elif data == "help_tmute": await query.answer("Usage: /tmute 10m (reply to user)", show_alert=True)
    elif data == "help_warn": await query.answer("Usage: /warn (reply to user). 3 warnings = BAN!", show_alert=True)

# --- Core Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🛡️ **Welcome to Aegis** 🛡️\n\nThe most advanced group manager.\n\n👇 Select a category below:"
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode='Markdown')

# --- Moderation Commands ---
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await get_user_level(update, context)
    if role < 2: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        prefix = LANGS[lang]["owner_respect"] + "\n\n" if role == 99 else (LANGS[lang]["coowner_respect"] + "\n\n" if role == 3 else "")
        await update.message.reply_text(f"{prefix}{LANGS[lang]['banned'].format(target.first_name)}", parse_mode='Markdown')
    except: await update.message.reply_text("❌ Failed. Is Bot Admin with Ban rights?")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['unbanned'].format(target.first_name), parse_mode='Markdown')
    except: await update.message.reply_text("❌ Failed.")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['kicked'].format(target.first_name), parse_mode='Markdown')
    except: await update.message.reply_text("❌ Failed.")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(LANGS[lang]['muted'].format(target.first_name), parse_mode='Markdown')
    except: await update.message.reply_text("❌ Failed.")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
        await update.message.reply_text(LANGS[lang]['unmuted'].format(target.first_name), parse_mode='Markdown')
    except: await update.message.reply_text("❌ Failed. Is Bot Admin with Restrict rights?")

async def tmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: `/tmute 10m` (reply to user)", parse_mode='Markdown')
    time_delta = extract_time(context.args[0])
    if not time_delta: return await update.message.reply_text("❌ Invalid time. Use 10m, 1h, 1d.")
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(LANGS[lang]['tmute_set'].format(target.first_name, context.args[0]), parse_mode='Markdown')
        context.job_queue.run_once(auto_unmute, time_delta, chat_id=update.effective_chat.id, data={'user_id': target.id})
    except: await update.message.reply_text("❌ Failed.")

async def tban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: `/tban 1d` (reply to user)", parse_mode='Markdown')
    time_delta = extract_time(context.args[0])
    if not time_delta: return await update.message.reply_text("❌ Invalid time.")
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['tban_set'].format(target.first_name, context.args[0]), parse_mode='Markdown')
        context.job_queue.run_once(auto_unban, time_delta, chat_id=update.effective_chat.id, data={'user_id': target.id})
    except: await update.message.reply_text("❌ Failed.")

async def tkick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 2: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: `/tkick 1h` (reply to user)", parse_mode='Markdown')
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['tkick_set'].format(target.first_name, context.args[0]), parse_mode='Markdown')
    except: await update.message.reply_text("❌ Failed.")

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 1: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    
    chat_id, user_id = update.effective_chat.id, target.id
    data = warnings_col.find_one({"chat_id": chat_id, "user_id": user_id})
    new_count = (data.get("count", 0) + 1) if data else 1
    
    if data: warnings_col.update_one({"_id": data["_id"]}, {"$set": {"count": new_count}})
    else: warnings_col.insert_one({"chat_id": chat_id, "user_id": user_id, "count": new_count})

    await update.message.reply_text(LANGS[lang]['khatarnak_warn'].format(target.first_name, new_count), parse_mode='Markdown')
    if new_count >= 3:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await update.message.reply_text(LANGS[lang]['khatarnak_ban'].format(target.first_name), parse_mode='Markdown')
            warnings_col.delete_one({"chat_id": chat_id, "user_id": user_id})
        except: pass

# --- Admin Levels ---
async def promote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 3: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target or len(context.args) < 2: return await update.message.reply_text("Usage: `/promote @user 1` (1=Mod, 2=Admin, 3=CoOwner)", parse_mode='Markdown')
    try: level = int(context.args[1])
    except: return await update.message.reply_text("❌ Level 1, 2 or 3.")
    if level not in [1, 2, 3]: return await update.message.reply_text("❌ Level 1, 2 or 3.")
    
    admins_col.update_one({"chat_id": update.effective_chat.id, "user_id": target.id}, {"$set": {"level": level}}, upsert=True)
    await update.message.reply_text(LANGS[lang]["promoted"].format(target.first_name, level), parse_mode='Markdown')

async def demote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    if await get_user_level(update, context) < 3: return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    admins_col.delete_one({"chat_id": update.effective_chat.id, "user_id": target.id})
    await update.message.reply_text(LANGS[lang]["demoted"].format(target.first_name), parse_mode='Markdown')

# --- Settings & Filters ---
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return await update.message.reply_text("🚫 Admin only.")
    if not update.message.reply_to_message and not context.args: return await update.message.reply_text("Reply to GIF/Text or write text.")
    media_id = update.message.reply_to_message.animation.file_id if update.message.reply_to_message and update.message.reply_to_message.animation else None
    text = " ".join(context.args) if context.args else "Welcome {name}! 🎉"
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"welcome_text": text, "welcome_media": media_id}}, upsert=True)
    await update.message.reply_text("🎉 Welcome updated!")

async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not context.args: return await update.message.reply_text("Usage: `/setgoodbye Goodbye {name}`")
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"goodbye": " ".join(context.args)}}, upsert=True)
    await update.message.reply_text("👋 Goodbye updated!")

async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not context.args: return
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"rules": " ".join(context.args)}}, upsert=True)
    await update.message.reply_text("📜 Rules updated!")

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "rules" in data: await update.message.reply_text(f"📜 **Rules:**\n{data['rules']}", parse_mode='Markdown')
    else: await update.message.reply_text("❌ No rules set.")

async def add_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if "->" not in update.message.text: return await update.message.reply_text("Format: `/addfilter hello -> Hi!`")
    parts = update.message.text.split("->", 1)
    trigger = parts[0].replace("/addfilter", "").strip().lower()
    filters_col.update_one({"chat_id": update.effective_chat.id, "trigger": trigger}, {"$set": {"reply": parts[1].strip()}}, upsert=True)
    await update.message.reply_text(f"✅ Filter added for `{trigger}`")

async def add_sticker_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    if not update.message.reply_to_message or not update.message.reply_to_message.sticker: return await update.message.reply_text("Reply to a sticker.")
    sticker_filters_col.update_one({"chat_id": update.effective_chat.id, "sticker_id": update.message.reply_to_message.sticker.file_unique_id}, {"$set": {"reply": "Sticker detected! 🖼️"}}, upsert=True)
    await update.message.reply_text("🖼️ Sticker filter added!")

# --- Locks & Anti-Spam ---
async def lock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(can_send_messages=False))
    await update.message.reply_text("🔒 Group Locked!")

async def unlock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await get_user_level(update, context) < 2: return
    await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
    await update.message.reply_text("🔓 Group Unlocked!")

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
        if data and "rules" in data: await update.message.reply_text(f"📜 **Rules:**\n{data['rules']}", parse_mode='Markdown')

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "goodbye" in data:
        await update.message.reply_text(data['goodbye'].replace("{name}", update.message.left_chat_member.first_name))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.lower()
    lang = get_lang(update.effective_chat.id)
    
    # Anti-Link
    if await get_user_level(update, context) < 1:
        if "http://" in text or "https://" in text or "t.me/" in text:
            try:
                await update.message.delete()
                await update.message.reply_text(f"⚠️ {update.effective_user.first_name}, links allowed nahi hain! 🚫")
                return
            except: pass
            
    # Auto Chat
    if text in ["hello", "hi", "hey"] and not update.message.reply_to_message:
        return await update.message.reply_text(f"Hello {update.effective_user.first_name}! 😊")
        
    # Filters
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
                await update.message.reply_text(LANGS[lang]["sticker_lock"])
            except: pass
            return

    if await get_user_level(update, context) < 1:
        now = datetime.now()
        user_stickers = sticker_spam_tracker[(chat_id, user_id)]
        user_stickers = [t for t in user_stickers if (now - t).total_seconds() < 60]
        
        if len(user_stickers) >= 9:
            try:
                await context.bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False))
                await update.message.reply_text(LANGS[lang]["sticker_mute"].format(update.effective_user.first_name))
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
        await update.message.reply_text(f"👤 User: `{update.message.reply_to_message.from_user.id}`\n💬 Chat: `{update.effective_chat.id}`", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"💬 Chat: `{update.effective_chat.id}`", parse_mode='Markdown')

# --- Main App ---
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    
    # Commands
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

    # Callbacks
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Messages
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_stickers))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Aegis ULTRA Bot running...")
    app.run_polling()

if __name__ == '__main__':
    main()
