import os
import logging
from telegram import Update, ChatPermissions, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from datetime import datetime

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Setup
MONGO_URI = os.environ.get("MONGODB_URI")
if not MONGO_URI:
    raise ValueError("MONGODB_URI environment variable set nahi hai!")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client['aegis_db']
warnings_col = db['warnings']
settings_col = db['settings']

# --- Helpers ---
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    member = await context.bot.get_chat_member(chat_id, user_id)
    if member.status in ['administrator', 'creator']:
        return True
    await update.message.reply_text("❌ Sirf admins hi is command ka use kar sakte hain.")
    return False

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        try:
            return await context.bot.get_chat(f"@{context.args[0]}")
        except Exception:
            await update.message.reply_text("❌ User nahi mila. Reply karo ya sahi username do.")
            return None
    await update.message.reply_text("❌ Kisi user ko reply karo ya username do.")
    return None

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🛡️ **Main Aegis hoon, aapka group guardian.**\n\n"
        "**Moderation:**\n"
        "/ban, /kick, /mute, /unmute\n"
        "/warn, /warns, /resetwarns\n"
        "/purge (reply to message)\n"
        "/pin (reply to message)\n\n"
        "**Settings:**\n"
        "/setwelcome <text>\n"
        "/setrules <text>\n"
        "/rules\n"
        "/id"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    target = await get_target_user(update, context)
    if not target: return
    chat_id, user_id = update.effective_chat.id, target.id
    
    data = warnings_col.find_one({"chat_id": chat_id, "user_id": user_id})
    new_count = (data.get("count", 0) + 1) if data else 1
    
    if data:
        warnings_col.update_one({"_id": data["_id"]}, {"$set": {"count": new_count}})
    else:
        warnings_col.insert_one({"chat_id": chat_id, "user_id": user_id, "count": new_count})

    await update.message.reply_text(f"⚠️ {target.first_name} ko warning di gayi. ({new_count}/3)")

    if new_count >= 3:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            await update.message.reply_text(f"🚫 {target.first_name} ko 3 warnings ke baad ban kar diya gaya.")
            warnings_col.delete_one({"chat_id": chat_id, "user_id": user_id})
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

async def warns_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    target = await get_target_user(update, context)
    if not target: return
    data = warnings_col.find_one({"chat_id": update.effective_chat.id, "user_id": target.id})
    count = data.get("count", 0) if data else 0
    await update.message.reply_text(f"📊 {target.first_name} ki warnings: {count}/3")

async def reset_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    target = await get_target_user(update, context)
    if not target: return
    warnings_col.delete_one({"chat_id": update.effective_chat.id, "user_id": target.id})
    await update.message.reply_text(f"✅ {target.first_name} ki saari warnings reset kar di gayi hain.")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    target = await get_target_user(update, context)
    if not target: return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"✅ {target.first_name} ko ban kar diya.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    target = await get_target_user(update, context)
    if not target: return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"✅ {target.first_name} ko kick kar diya.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    target = await get_target_user(update, context)
    if not target: return
    try:
        perms = ChatPermissions(can_send_messages=False)
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, perms)
        await update.message.reply_text(f"✅ {target.first_name} ko mute kar diya.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    target = await get_target_user(update, context)
    if not target: return
    try:
        perms = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, perms)
        await update.message.reply_text(f"✅ {target.first_name} ka mute hataya.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def purge_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Jis message se purge start karna hai, usko reply karke /purge likho.")
        return
    
    message_id = update.message.reply_to_message.message_id
    current_id = update.message.message_id
    deleted = 0
    
    for msg_id in range(message_id, current_id + 1):
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            deleted += 1
        except:
            pass
    await context.bot.send_message(update.effective_chat.id, f"🧹 {deleted} messages delete kar diye gaye.")

async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Kisi message ko reply karke /pin likho.")
        return
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await update.message.reply_text("📌 Message pin kar diya gaya.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not context.args:
        await update.message.reply_text("❌ Format: /setwelcome Welcome to the group, {name}!")
        return
    welcome_text = " ".join(context.args)
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"welcome": welcome_text}}, upsert=True)
    await update.message.reply_text("✅ Welcome message set ho gaya.")

async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not context.args:
        await update.message.reply_text("❌ Format: /setrules Rule 1: No spam...")
        return
    rules_text = " ".join(context.args)
    settings_col.update_one({"chat_id": update.effective_chat.id}, {"$set": {"rules": rules_text}}, upsert=True)
    await update.message.reply_text("✅ Rules set ho gaye.")

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = settings_col.find_one({"chat_id": update.effective_chat.id})
    if data and "rules" in data:
        await update.message.reply_text(f"📜 **Group Rules:**\n\n{data['rules']}", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Is group ke liye koi rules set nahi hain.")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await update.message.reply_text(f"👤 User ID: `{user.id}`\n💬 Chat ID: `{update.effective_chat.id}`", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"💬 Chat ID: `{update.effective_chat.id}`", parse_mode='Markdown')

# --- Welcome New Members ---
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        
        data = settings_col.find_one({"chat_id": update.effective_chat.id})
        welcome_text = data.get("welcome", "Hello {name}, welcome to the group! 👋") if data else "Hello {name}, welcome to the group! 👋"
        
        await update.message.reply_text(welcome_text.replace("{name}", member.first_name))

# --- Main ---
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token: raise ValueError("TELEGRAM_BOT_TOKEN set nahi hai!")

    app = Application.builder().token(token).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("warns", warns_check))
    app.add_handler(CommandHandler("resetwarns", reset_warns))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("purge", purge_messages))
    app.add_handler(CommandHandler("pin", pin_message))
    app.add_handler(CommandHandler("setwelcome", set_welcome))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("rules", show_rules))
    app.add_handler(CommandHandler("id", get_id))
    
    # Member Join Handler
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))

    print("Aegis Bot (Advanced) start ho raha hai...")
    app.run_polling()

if __name__ == '__main__':
    main()
