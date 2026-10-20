import os
import re
import logging
from datetime import datetime, timedelta
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

# --- Languages Setup ---
LANGS = {
    "en": {
        "denied": "🚫 Access Denied! Only admins can use this command.",
        "owner_respect": "👑 Yes, Boss! Your wish is my command. ⚡",
        "user_not_found": "❌ Target not found! Please **Reply** to their message or make sure they have sent at least one message in the group.",
        "banned": "🔨 BANNED! {} has been permanently removed. 🚫",
        "unbanned": "🕊️ {} has been unbanned. Welcome back! ✅",
        "kicked": "👢 KICKED! {} has been removed. 🚪",
        "muted": "🔇 MUTED! {} can no longer speak. 🤐",
        "unmuted": "🔊 UNMUTED! {} can speak again. 🗣️",
        "tmute_set": "⏱️ {} has been muted for {}. 🔇",
        "tban_set": "⏱️ {} has been banned for {}. 🔨",
        "tkick_set": "⏱️ {} has been kicked for {}. 👢",
        "khatarnak_warn": "☠️ KHATRA! ☠️\n\n⚠️ {} has received a warning!\n🚨 Warning Count: {}/3\n\nNext time, it's a BAN! 💀",
        "khatarnak_ban": "💀 GAME OVER! 💀\n\n🚫 {} has been permanently banned for reaching 3 warnings. ☠️",
        "purge_success": "🧹 Successfully deleted {} messages! ✅",
        "report_msg": "🚨 REPORT ALERT! 🚨\n\nAdmin Team, please check this user. {} reported them! ⚠️",
        "lang_changed": "🌐 Language successfully changed to English! 🇬🇧",
        "welcome_set": "🎉 Welcome message updated! ✅",
        "goodbye_set": "👋 Goodbye message updated! ✅",
        "rules_set": "📜 Rules updated! ✅",
        "filter_added": "⚙️ Filter added for: `{}` ✅",
        "filter_removed": "🗑️ Filter removed for: `{}` ✅",
        "sticker_added": "🖼️ Sticker filter added! ✅",
        "sticker_removed": "🗑️ Sticker filter removed! ✅",
        "chat_hello": "Hello {}! How can I help you today? 😊",
        "chat_howareyou": "I'm doing great, thanks for asking {}! Ready to protect the group! 🛡️"
    },
    "hi": {
        "denied": "🚫 Permission nahi hai! Sirf admins ye command use kar sakte hain.",
        "owner_respect": "👑 Ji Huzoor! Aapka hukum sar aankhon par. ⚡",
        "user_not_found": "❌ Target nahi mila! Kripya uske message par **Reply** karein, ya direct `/kick @username` likhein.",
        "banned": "🔨 BANNED! {} ko hamesha ke liye ban kar diya gaya. 🚫",
        "unbanned": "🕊️ {} ko unban kar diya gaya. Wapas aa sakte hain! ✅",
        "kicked": "👢 KICKED! {} ko group se bahar nikal diya gaya. 🚪",
        "muted": "🔇 MUTED! {} ab message nahi bhej sakta. 🤐",
        "unmuted": "🔊 UNMUTED! {} ab wapas bol sakta hai. 🗣️",
        "tmute_set": "⏱️ {} ko {} ke liye mute kar diya gaya. 🔇",
        "tban_set": "⏱️ {} ko {} ke liye ban kar diya gaya. 🔨",
        "tkick_set": "⏱️ {} ko {} ke liye kick kar diya gaya. 👢",
        "khatarnak_warn": "☠️ KHATRA! ☠️\n\n⚠️ {} ko warning mili hai!\n🚨 Warning Count: {}/3\n\nAgli baar direct BAN hoga! 💀",
        "khatarnak_ban": "💀 GAME OVER! 💀\n\n🚫 {} ko 3 warnings ke baad permanently BAN kar diya gaya. ☠️",
        "purge_success": "🧹 {} messages successfully delete kar diye gaye! ✅",
        "report_msg": "🚨 REPORT ALERT! 🚨\n\nAdmin Team, is user ko check karein. {} ne report kiya hai! ⚠️",
        "lang_changed": "🌐 Language successfully Hindi mein badal di gayi! 🇮🇳",
        "welcome_set": "🎉 Welcome message update ho gaya! ✅",
        "goodbye_set": "👋 Goodbye message update ho gaya! ✅",
        "rules_set": "📜 Group rules update kar diye gaye hain! ✅",
        "filter_added": "⚙️ `{}` ke liye filter add ho gaya. ✅",
        "filter_removed": "🗑️ `{}` ka filter hata diya gaya. ✅",
        "sticker_added": "🖼️ Sticker filter add ho gaya! ✅",
        "sticker_removed": "🗑️ Sticker filter hata diya gaya! ✅",
        "chat_hello": "Namaste {}! Main aapki kya madad kar sakta hoon? 😊",
        "chat_howareyou": "Main bilkul mast hoon {}! Group ki security mere haath mein hai. 🛡️"
    }
}

def get_lang(chat_id):
    data = settings_col.find_one({"chat_id": chat_id})
    return data.get("lang", "en") if data else "en"

# --- SMART TARGET SYSTEM (Fixes the "User Not Found" issue) ---
async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Agar reply kiya hai
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user
    
    # 2. Agar username ya ID di hai
    if context.args:
        arg = context.args[0]
        try:
            if arg.isdigit() or (arg.startswith('-') and arg[1:].isdigit()):
                return await context.bot.get_chat(int(arg))
            else:
                if not arg.startswith('@'):
                    arg = '@' + arg
                return await context.bot.get_chat(arg)
        except Exception as e:
            logger.error(f"Target Error: {e}")
            return None
    return None

async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == OWNER_ID: return "owner"
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        if member.status in ['administrator', 'creator']: return "admin"
        return "user"
    except Exception:
        return "user"

def extract_time(time_str):
    match = re.match(r'(\d+)([mhd])', time_str.lower())
    if not match: return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == 'm': return timedelta(minutes=val)
    if unit == 'h': return timedelta(hours=val)
    if unit == 'd': return timedelta(days=val)
    return None

# --- Background Jobs ---
async def auto_unmute(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.restrict_chat_member(job.chat_id, job.data['user_id'], ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))

async def auto_unban(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.unban_chat_member(job.chat_id, job.data['user_id'])

# --- Core Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add to Group", url="https://t.me/aegis_manager_bot?startgroup=true")],
        [InlineKeyboardButton("📚 Help Menu", callback_data="help_menu")]
    ]
    text = (
        "🛡️ **Aegis - Professional Group Manager** 🛡️\n\n"
        "Main aapke group ki security aur management ke liye yahan hoon. 🔥\n"
        "Mujhe admin banayein aur group ko spam-free rakhein. 🚀\n\n"
        "👑 **Creator:** Aman"
    )
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "📚 **Aegis Commands List** 📚\n\n"
        "🛡️ **Moderation:**\n"
        "`/ban`, `/unban`, `/kick`\n"
        "`/mute`, `/unmute`\n"
        "`/tmute 1h`, `/tban 1d`, `/tkick 1d`\n"
        "`/warn`, `/purge`, `/del`\n"
        "`/lock`, `/unlock`\n\n"
        "⚙️ **Settings:**\n"
        "`/setlang en` or `/setlang hi`\n"
        "`/setwelcome`, `/setgoodbye`\n"
        "`/setrules`, `/rules`\n"
        "`/addfilter word -> reply`\n"
        "`/addsticker` (reply to sticker)\n"
        "`/pin`, `/id`, `/info`, `/admins`, `/report`"
    )
    await query.edit_message_text(text=text, parse_mode='Markdown')

async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["denied"])
    if not context.args or context.args[0] not in ['en', 'hi']: return await update.message.reply_text("Usage: `/setlang en` OR `/setlang hi`")
    lang = context.args[0]
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"lang": lang}}, upsert=True)
    await update.message.reply_text(LANGS[lang]["lang_changed"])

# --- Moderation Commands ---
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        prefix = LANGS[lang]["owner_respect"] + "\n\n" if role == "owner" else ""
        await update.message.reply_text(f"{prefix}{LANGS[lang]['banned'].format(target.first_name)}")
    except Exception: await update.message.reply_text("❌ Failed. Check bot permissions.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['unbanned'].format(target.first_name))
    except Exception: await update.message.reply_text("❌ Failed to unban.")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['kicked'].format(target.first_name))
    except Exception: await update.message.reply_text("❌ Failed to kick.")

async def tmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: `/tmute 1h` (reply to user)")
    time_delta = extract_time(context.args[0])
    if not time_delta: return await update.message.reply_text("❌ Invalid time. Use 1m, 1h, 1d.")
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(LANGS[lang]['tmute_set'].format(target.first_name, context.args[0]))
        context.job_queue.run_once(auto_unmute, time_delta, chat_id=update.effective_chat.id, data={'user_id': target.id})
    except Exception: await update.message.reply_text("❌ Failed.")

async def tban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: `/tban 1d` (reply to user)")
    time_delta = extract_time(context.args[0])
    if not time_delta: return await update.message.reply_text("❌ Invalid time.")
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['tban_set'].format(target.first_name, context.args[0]))
        context.job_queue.run_once(auto_unban, time_delta, chat_id=update.effective_chat.id, data={'user_id': target.id})
    except Exception: await update.message.reply_text("❌ Failed.")

async def tkick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target or len(context.args) < 1: return await update.message.reply_text("Usage: `/tkick 1d` (reply to user)")
    time_delta = extract_time(context.args[0])
    if not time_delta: return await update.message.reply_text("❌ Invalid time.")
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(LANGS[lang]['tkick_set'].format(target.first_name, context.args[0]))
    except Exception: await update.message.reply_text("❌ Failed.")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(LANGS[lang]['muted'].format(target.first_name))
    except Exception: await update.message.reply_text("❌ Failed.")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
        await update.message.reply_text(LANGS[lang]['unmuted'].format(target.first_name))
    except Exception: await update.message.reply_text("❌ Failed.")

# --- Warn System ---
async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update.effective_chat.id)
    role = await is_admin_or_owner(update, context)
    if role == "user": return await update.message.reply_text(LANGS[lang]["denied"])
    target = await get_target(update, context)
    if not target: return await update.message.reply_text(LANGS[lang]["user_not_found"])
    
    chat_id, user_id = update.effective_chat.id, target.id
    data = warnings_col.find_one({"chat_id": chat_id, "user_id": user_id})
    new_count = (data.get("count", 0) + 1) if data else 1
    
    if data: warnings_col.update_one({"_id": data["_id"]}, {"$set": {"count": new_count}})
    else: warnings_col.insert_one({"chat_id": chat_id, "user_id": user_id, "count": new_count})

    await update.message.reply_text(LANGS[lang]['khatarnak_warn'].format(target.first_name, new_count))
    
    if new_count >= 3:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await update.message.reply_text(LANGS[lang]['khatarnak_ban'].format(target.first_name))
            warnings_col.delete_one({"chat_id": chat_id, "user_id": user_id})
        except Exception: pass

# --- Purge & Delete ---
async def purge_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a message to start purge.")
    message_id = update.message.reply_to_message.message_id
    current_id = update.message.message_id
    deleted = 0
    for msg_id in range(message_id, current_id + 1):
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            deleted += 1
        except: pass
    await context.bot.send_message(update.effective_chat.id, LANGS[get_lang(update.effective_chat.id)]["purge_success"].format(deleted))

async def del_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a message to delete.")
    try:
        await update.message.reply_to_message.delete()
        await update.message.delete()
    except: pass

# --- Lock / Unlock ---
async def lock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text("🔒 GROUP LOCKED! Sirf admins bol sakte hain. 🛡️")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def unlock_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
        await update.message.reply_text("🔓 GROUP UNLOCKED! Sabhi members bol sakte hain. ✅")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

# --- Settings & Welcome/Goodbye ---
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not update.message.reply_to_message and not context.args: return await update.message.reply_text("Reply to a GIF/Text or write text.")
    media_id = update.message.reply_to_message.animation.file_id if update.message.reply_to_message and update.message.reply_to_message.animation else None
    text = " ".join(context.args) if context.args else "Welcome {name}! 🎉"
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"welcome_text": text, "welcome_media": media_id}}, upsert=True)
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["welcome_set"])

async def set_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not context.args: return await update.message.reply_text("Usage: `/setgoodbye Goodbye {name} 👋`")
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"goodbye": " ".join(context.args)}}, upsert=True)
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["goodbye_set"])

async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not context.args: return await update.message.reply_text("Usage: `/setrules Rule 1...`")
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"rules": " ".join(context.args)}}, upsert=True)
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["rules_set"])

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "rules" in data: await update.message.reply_text(f"📜 **Group Rules:**\n{data['rules']}", parse_mode='Markdown')
    else: await update.message.reply_text("❌ No rules set.")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        welcome = data.get("welcome_text", "Welcome {name}! 👋").replace("{name}", member.first_name) if data else "Welcome {name}! 👋".replace("{name}", member.first_name)
        media = data.get("welcome_media") if data else None
        if media: await update.message.reply_animation(animation=media, caption=welcome)
        else: await update.message.reply_text(welcome)
        if data and "rules" in data: await update.message.reply_text(f"📜 **Please read the rules:**\n{data['rules']}", parse_mode='Markdown')

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "goodbye" in data:
        await update.message.reply_text(data['goodbye'].replace("{name}", update.message.left_chat_member.first_name))

# --- Filters (Text & Sticker) ---
async def add_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if "->" not in update.message.text: return await update.message.reply_text("Format: `/addfilter hello -> Hi there!`")
    parts = update.message.text.split("->", 1)
    trigger = parts[0].replace("/addfilter", "").strip().lower()
    reply = parts[1].strip()
    filters_col.update_one({"chat_id": update.effective_chat.id, "trigger": trigger}, {"$set": {"reply": reply}}, upsert=True)
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["filter_added"].format(trigger))

async def del_text_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not context.args: return
    filters_col.delete_one({"chat_id": update.effective_chat.id, "trigger": context.args[0].lower()})
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["filter_removed"].format(context.args[0]))

async def add_sticker_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not update.message.reply_to_message or not update.message.reply_to_message.sticker:
        return await update.message.reply_text("🖼️ Reply to a sticker with `/addsticker` to set a filter.")
    sticker_id = update.message.reply_to_message.sticker.file_unique_id
    sticker_filters_col.update_one({"chat_id": update.effective_chat.id, "sticker_id": sticker_id}, {"$set": {"reply": "Sticker detected! 🖼️"}}, upsert=True)
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["sticker_added"])

async def del_sticker_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not update.message.reply_to_message or not update.message.reply_to_message.sticker:
        return await update.message.reply_text("🖼️ Reply to a sticker with `/delsticker` to remove filter.")
    sticker_id = update.message.reply_to_message.sticker.file_unique_id
    sticker_filters_col.delete_one({"chat_id": update.effective_chat.id, "sticker_id": sticker_id})
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["sticker_removed"])

async def check_text_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.lower()
    lang = get_lang(update.effective_chat.id)
    
    if text in ["hello", "hi", "hey", "namaste"] and not update.message.reply_to_message:
        return await update.message.reply_text(LANGS[lang]["chat_hello"].format(update.effective_user.first_name))
    if text in ["how are you", "kaise ho", "kya haal hai"] and not update.message.reply_to_message:
        return await update.message.reply_text(LANGS[lang]["chat_howareyou"].format(update.effective_user.first_name))
        
    data = filters_col.find_one({"chat_id": update.effective_chat.id, "trigger": text})
    if data: await update.message.reply_text(data['reply'])

async def check_sticker_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.sticker: return
    sticker_id = update.message.sticker.file_unique_id
    data = sticker_filters_col.find_one({"chat_id": update.effective_chat.id, "sticker_id": sticker_id})
    if data: await update.message.reply_text(data['reply'])

# --- Anti-Link ---
async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    if await is_admin_or_owner(update, context) in ["admin", "owner"]: return 
    if "http://" in update.message.text or "https://" in update.message.text or "t.me/" in update.message.text:
        try:
            await update.message.delete()
            await update.message.reply_text(f"⚠️ {update.effective_user.first_name}, links allowed nahi hain! 🚫")
        except: pass

# --- Info & Utility ---
async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_admin_or_owner(update, context) == "user": return
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a message to pin.")
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await update.message.reply_text("📌 Message pinned successfully!")
    except: await update.message.reply_text("❌ Failed to pin.")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await update.message.reply_text(f"👤 User ID: `{user.id}`\n💬 Chat ID: `{update.effective_chat.id}`", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"💬 Chat ID: `{update.effective_chat.id}`", parse_mode='Markdown')

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target(update, context)
    if not target: return await update.message.reply_text("❌ User not found.")
    text = f"👤 **User Info:**\n**Name:** {target.first_name}\n**Username:** @{target.username if target.username else 'None'}\n**ID:** `{target.id}`\n**Bot:** {'Yes 🤖' if target.is_bot else 'No 👤'}"
    await update.message.reply_text(text, parse_mode='Markdown')

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    text = "👑 **Group Admins:**\n\n"
    for admin in admins: text += f"• {admin.user.first_name} 🛡️\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("❌ Reply to a user to report.")
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    admin_tags = " ".join([f"[{a.user.first_name}](tg://user?id={a.user.id})" for a in admins if not a.user.is_bot])
    await update.message.reply_text(LANGS[get_lang(update.effective_chat.id)]["report_msg"].format(update.effective_user.first_name) + f"\n\n{admin_tags}", parse_mode='Markdown')

# --- Main Application ---
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_menu)) # Added help directly
    app.add_handler(CallbackQueryHandler(help_menu, pattern="help_menu"))
    app.add_handler(CommandHandler("setlang", set_lang))
    
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("tmute", tmute_user))
    app.add_handler(CommandHandler("tban", tban_user))
    app.add_handler(CommandHandler("tkick", tkick_user))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("lock", lock_group))
    app.add_handler(CommandHandler("unlock", unlock_group))
    app.add_handler(CommandHandler("purge", purge_messages))
    app.add_handler(CommandHandler("del", del_message))
    
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("setgoodbye", set_goodbye))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("rules", show_rules))
    
    app.add_handler(CommandHandler("addfilter", add_text_filter))
    app.add_handler(CommandHandler("delfilter", del_text_filter))
    app.add_handler(CommandHandler("addsticker", add_sticker_filter))
    app.add_handler(CommandHandler("delsticker", del_sticker_filter))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))
    app.add_handler(MessageHandler(filters.Sticker.ALL, check_sticker_filters))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_text_filters))
    
    app.add_handler(CommandHandler("pin", pin_message))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("info", user_info))
    app.add_handler(CommandHandler("admins", list_admins))
    app.add_handler(CommandHandler("report", report_user))

    print("Aegis Mega Bot is running perfectly...")
    app.run_polling()

if __name__ == '__main__':
    main()
