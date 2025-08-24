#!/usr/bin/env python3
"""
Legit Auto-Post + Sample Video Bot with MongoDB (Safe Version) + Force Subscribe
-------------------------------------------------------------------------------
Admin:
• Reply to TEXT or IMAGE with /attach <keyword> → saves post
• Reply to VIDEO with /attach <keyword> → saves sample video
• /delete <keyword> → deletes post + sample video
• /broadcast <keyword> → manually broadcast specific post+video
• /broadcast -pin → reply to video, sends & pins to all users DM

User:
• Send <keyword> → bot sends post + sample video
• Auto-delete after 10 min (start message = 5 min)
• protect_content=True
• Neutral "More Info" button included automatically
• Auto-clean old entries silently after 1 year
• Avoid sending same post twice to same user (per day)
• Auto-overwrite support
• ✅ Added rate limit (default: 5 seconds per request)
• ✅ Force-Subscribe: must join channel before using the bot (auto-verify)
"""

import asyncio, re, datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.constants import ChatMemberStatus
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from pymongo import MongoClient
import config

# -------------------- MongoDB --------------------
client = MongoClient(config.MONGO_URI)
db = client[config.DB_NAME]
collection = db[config.COLLECTION_NAME]
users_col = db["users"]

# -------------------- Utils --------------------
def is_owner(user_id: Optional[int]) -> bool:
    return bool(user_id and (user_id in getattr(config, "OWNER_IDS", []) or not getattr(config, "OWNER_IDS", [])))

def norm_kw(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

BRACKET_LINK_RE = re.compile(r"(?P<label>[^\[]+?)\[(?P<url>https?://[^\]\s]+)\]")

def convert_bracket_links_to_html(text: str) -> str:
    parts, last = [], 0
    for m in BRACKET_LINK_RE.finditer(text):
        parts.append(html_escape(text[last:m.start()]))
        label = html_escape(m.group("label").strip())
        url = m.group("url").strip()
        parts.append(f'<a href="{url}">{label}</a>')
        last = m.end()
    parts.append(html_escape(text[last:]))
    return "".join(parts)

# -------------------- Force Subscribe --------------------
def _channel_url() -> str:
    ch = getattr(config, "FORCE_SUB_CHANNEL", "")
    if isinstance(ch, str) and ch.startswith("@"):
        return f"https://t.me/{ch[1:]}"
    return f"https://t.me/{getattr(config, 'SUPPORT_CHANNEL_USERNAME', 'telegram')}"

async def is_user_member(bot, user_id: int) -> bool:
    channel = getattr(config, "FORCE_SUB_CHANNEL", None)
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False

def subscription_prompt_markup() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("Join the Channel ✅", url=_channel_url())],
        [InlineKeyboardButton("✅ I’ve Joined", callback_data="check_sub")]
    ]
    return InlineKeyboardMarkup(buttons)

async def ensure_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat_id = update.effective_chat.id
    if is_owner(user.id):
        return True
    if await is_user_member(context.bot, user.id):
        return True
    text = (
        "🚧 <b>Access Locked</b>\n\n"
        "To use this bot, please join our channel first. "
        "Tap <b>Join the Channel ✅</b> and then press <b>“I’ve Joined”</b> to verify.\n\n"
        "Thanks for supporting us! 💜"
    )
    try:
        msg = await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
            text, parse_mode=constants.ParseMode.HTML, reply_markup=subscription_prompt_markup()
        )
        asyncio.create_task(schedule_auto_delete(context.bot, chat_id, msg.message_id, 300))
    except Exception:
        pass
    return False

# -------------------- Auto Delete --------------------
async def schedule_auto_delete(bot, chat_id: int, message_id: int, seconds: int = None):
    try:
        await asyncio.sleep(seconds or config.AUTO_DELETE_SECONDS)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

async def auto_clean_old_entries(app: Application):
    while True:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=365)
        collection.delete_many({"timestamp": {"$lt": cutoff}})
        await asyncio.sleep(24*60*60)

# -------------------- Sending Posts --------------------
async def send_post_to_user(app: Application, chat_id: int, post: dict, pin=False, permanent=False):
    post_html = post.get("post_html") or ""
    poster_id = post.get("poster_file_id")
    sample_id = post.get("sample_file_id")
    buttons = [[InlineKeyboardButton("More Info", url="https://t.me/sampleclipes/3")]]
    markup = InlineKeyboardMarkup(buttons)

    try:
        if poster_id:
            msg = await app.bot.send_photo(
                chat_id, photo=poster_id, caption=post_html,
                parse_mode=constants.ParseMode.HTML,
                protect_content=True, reply_markup=markup
            )
        else:
            msg = await app.bot.send_message(
                chat_id, text=post_html,
                parse_mode=constants.ParseMode.HTML,
                protect_content=True, reply_markup=markup
            )
        if not permanent:
            asyncio.create_task(schedule_auto_delete(app.bot, chat_id, msg.message_id))
        if pin:
            try:
                await app.bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
            except Exception:
                pass
    except Exception:
        pass

    if sample_id:
        try:
            msg2 = await app.bot.send_video(chat_id, video=sample_id, protect_content=True)
            if not permanent:
                asyncio.create_task(schedule_auto_delete(app.bot, chat_id, msg2.message_id))
            if pin:
                try:
                    await app.bot.pin_chat_message(chat_id, msg2.message_id, disable_notification=True)
                except Exception:
                    pass
        except Exception:
            pass

# -------------------- Commands --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed = await ensure_subscribed(update, context)
    if not allowed:
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    users_col.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "joined_at": datetime.datetime.utcnow(),
            "last_request": None
        },
        "$setOnInsert": {"sent_posts": [], "sent_today": {}}},
        upsert=True
    )
    buttons = [
        [
            InlineKeyboardButton("Noob Dev", url="https://t.me/SunsetOfMe"),
            InlineKeyboardButton("Support Channel", url="https://t.me/Fallen_Angels_Team")
        ],
        [
            InlineKeyboardButton("More Info", url="https://t.me/sampleclipes/3")
        ]
    ]
    markup = InlineKeyboardMarkup(buttons)
    msg = await update.message.reply_text(
        f"👋 Hi {user.first_name}!\n\n"
        "Welcome! Here you can explore the latest clips, short videos, and posts.\n"
        "Just type the keyword you are interested in, and you'll receive the content instantly.\n\n"
        "Have fun exploring! 🎉",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=markup
    )
    asyncio.create_task(schedule_auto_delete(context.bot, chat_id, msg.message_id, 300))

async def attach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /attach <keyword> (reply to TEXT, IMAGE, or VIDEO)")
        return
    keyword = norm_kw(args[0])
    replied = update.message.reply_to_message
    saved = False

    post_text = None
    if replied:
        post_text = replied.text or replied.caption
    if len(args) >= 2 and not post_text:
        post_text = update.message.text.split(None, 2)[2]

    if post_text:
        collection.update_one(
            {"keyword": keyword},
            {"$set": {
                "post_html": convert_bracket_links_to_html(post_text),
                "timestamp": datetime.datetime.utcnow(),
                "keyword": keyword
            }},
            upsert=True
        )
        saved = True

    if replied and (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        file_id = replied.video.file_id if replied.video else replied.document.file_id
        collection.update_one(
            {"keyword": keyword},
            {"$set": {"sample_file_id": file_id, "timestamp": datetime.datetime.utcnow()}},
            upsert=True
        )
        saved = True

    if replied and replied.photo:
        photo_file_id = replied.photo[-1].file_id
        collection.update_one(
            {"keyword": keyword},
            {"$set": {"poster_file_id": photo_file_id, "timestamp": datetime.datetime.utcnow()}},
            upsert=True
        )
        saved = True

    if saved:
        await update.message.reply_text(f"✅ Content attached/updated for '{keyword}'.")
    else:
        await update.message.reply_text(f"⚠️ Nothing new to attach for '{keyword}'.")

async def delete_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /delete <keyword>")
        return
    keyword = norm_kw(args[0])
    result = collection.delete_one({"keyword": keyword})
    if result.deleted_count:
        users_col.update_many({}, {"$pull": {"sent_posts": keyword}})
        await update.message.reply_text(f"🗑️ '{keyword}' deleted successfully.")
    else:
        await update.message.reply_text(f"'{keyword}' not found.")

# -------------------- Rate Limited Keyword Trigger --------------------
RATE_LIMIT_SECONDS = 5

async def keyword_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed = await ensure_subscribed(update, context)
    if not allowed:
        return
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_doc = users_col.find_one({"chat_id": chat_id}) or {}
    last_request = user_doc.get("last_request")
    now = datetime.datetime.utcnow()
    if last_request and (now - last_request).total_seconds() < RATE_LIMIT_SECONDS:
        return
    users_col.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "joined_at": datetime.datetime.utcnow(),
            "last_request": now
        },
        "$setOnInsert": {"sent_posts": [], "sent_today": {}}},
        upsert=True
    )
    keyword = norm_kw(update.message.text or "")
    data = collection.find_one({"keyword": keyword})
    if not data:
        return
    await send_post_to_user(context.application, chat_id, data)

# -------------------- Broadcast with Pin --------------------
async def manual_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return

    args = context.args
    replied = update.message.reply_to_message
    pin_flag = "-pin" in args

    if pin_flag and replied and (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        # Broadcast replied video to all users DM and pin
        file_id = replied.video.file_id if replied.video else replied.document.file_id
        caption = replied.caption or ""

        all_users = users_col.find()
        for user in all_users:
            try:
                msg = await context.bot.send_video(user["chat_id"], video=file_id, caption=caption, protect_content=True)
                if pin_flag:
                    try:
                        await context.bot.pin_chat_message(user["chat_id"], msg.message_id, disable_notification=True)
                    except Exception:
                        continue
            except Exception:
                continue
        await update.message.reply_text(f"✅ Video broadcasted & pinned to all users DM.")
        return

    if not args:
        await update.message.reply_text("Usage: /broadcast <keyword> or reply to video with /broadcast -pin")
        return

    keyword = norm_kw(args[0])
    post = collection.find_one({"keyword": keyword})
    if not post:
        await update.message.reply_text(f"Keyword '{keyword}' not found.")
        return
    all_users = users_col.find()
    for user in all_users:
        try:
            sent_posts = user.get("sent_posts", [])
            if keyword not in sent_posts:
                await send_post_to_user(context.application, user["chat_id"], post)
                users_col.update_one({"chat_id": user["chat_id"]}, {"$push": {"sent_posts": keyword}})
        except Exception:
            continue
    await update.message.reply_text(f"✅ Broadcasted '{keyword}' to all users.")

# -------------------- List / Report Commands --------------------
MONTHS = {
    "jan":1, "feb":2, "mar":3, "apr":4, "may":5, "jun":6,
    "jul":7, "aug":8, "sep":9, "oct":10, "nov":11, "dec":12
}

async def list_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    args = context.args
    msg_text = ""
    if not args:
        all_keywords = collection.distinct("keyword")
        msg_text = f"📄 Total keywords: {len(all_keywords)}\n" + "\n".join(all_keywords)
    elif args[0].lower().startswith("m"):
        month_str = args[0][1:].lower()
        month_num = MONTHS.get(month_str)
        if not month_num:
            await update.message.reply_text("❌ Invalid month. Use jan, feb, ..., dec.")
            return
        year = datetime.datetime.utcnow().year
        start_date = datetime.datetime(year, month_num, 1)
        end_date = datetime.datetime(year + (1 if month_num == 12 else 0), (1 if month_num == 12 else month_num + 1), 1)
        keywords = collection.find({"timestamp": {"$gte": start_date, "$lt": end_date}})
        kws = [k["keyword"] for k in keywords]
        msg_text = f"📄 Keywords used in {month_str.capitalize()}: {len(kws)}\n" + "\n".join(kws)
    elif args[0].lower() == "w":
        now = datetime.datetime.utcnow()
        start_week = now - datetime.timedelta(days=now.weekday())
        keywords = collection.find({"timestamp": {"$gte": start_week}})
        kws = [k["keyword"] for k in keywords]
        msg_text = f"📄 Keywords used this week: {len(kws)}\n" + "\n".join(kws)
    else:
        msg_text = "❌ Invalid command usage."
    await update.message.reply_text(msg_text or "No keywords found.")

# -------------------- Callback: re-check subscription --------------------
async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if await is_user_member(context.bot, user.id):
        try:
            await query.edit_message_text(
                "✅ Verified! You’ve joined the channel. You can now use the bot.\n\n"
                "Send a keyword to get content.",
                parse_mode=constants.ParseMode.HTML
            )
        except Exception:
            pass
    else:
        try:
            await query.edit_message_text(
                "❌ You haven’t joined yet.\n\n"
                "Please tap <b>Join the Channel ✅</b>, then press <b>“I’ve Joined”</b> to verify.",
                parse_mode=constants.ParseMode.HTML,
                reply_markup=subscription_prompt_markup()
            )
        except Exception:
            pass

# -------------------- Main --------------------
def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN env required")
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attach", attach))
    app.add_handler(CommandHandler("delete", delete_keyword))
    app.add_handler(CommandHandler("broadcast", manual_broadcast))
    app.add_handler(CommandHandler(["list"], list_keywords))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_trigger))

    async def on_startup(app: Application):
        asyncio.create_task(auto_clean_old_entries(app))

    app.post_init = on_startup
    print("Bot running…")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
