#!/usr/bin/env python3
"""
Coolie Auto-Post + Sample Video Bot with MongoDB
------------------------------------------------
Admin:
• Reply to TEXT or IMAGE with /attach <keyword> → saves post
• Reply to VIDEO with /attach <keyword> → saves sample video
• /delete <keyword> → deletes post + sample video
• /broadcast <keyword> → manually broadcast specific post+video

User:
• Send <keyword> → bot sends post + sample video
• Auto-delete after 10 min
• protect_content=True
• Fixed How To Download button included automatically
• Auto-clean old entries silently after 1 year
• Auto daily broadcast of new posts 3 times/day
• Avoid sending same post twice to same user (per day)
• Auto-overwrite support
"""

import asyncio, re, datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from pymongo import MongoClient
import config

# -------------------- MongoDB --------------------
client = MongoClient(config.MONGO_URI)
db = client[config.DB_NAME]
collection = db[config.COLLECTION_NAME]
users_col = db["users"]  # store users for broadcast

# -------------------- Utils --------------------
def is_owner(user_id: Optional[int]) -> bool:
    return bool(user_id and (user_id in config.OWNER_IDS or not config.OWNER_IDS))

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

# -------------------- Auto Delete --------------------
async def schedule_auto_delete(bot, chat_id: int, message_id: int):
    try:
        await asyncio.sleep(config.AUTO_DELETE_SECONDS)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

async def auto_clean_old_entries(app: Application):
    while True:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=365)
        collection.delete_many({"timestamp": {"$lt": cutoff}})
        await asyncio.sleep(24*60*60)

# -------------------- Sending Posts --------------------
async def send_post_to_user(app: Application, chat_id: int, post: dict):
    post_html = post.get("post_html") or ""
    poster_id = post.get("poster_file_id")
    sample_id = post.get("sample_file_id")
    buttons = [[InlineKeyboardButton("How To Download — Click Here", url="https://t.me/tamilmoviedownload0/3")]]
    markup = InlineKeyboardMarkup(buttons)

    if poster_id:
        msg = await app.bot.send_photo(
            chat_id, photo=poster_id, caption=post_html,
            parse_mode=constants.ParseMode.HTML,
            protect_content=True, reply_markup=markup
        )
        asyncio.create_task(schedule_auto_delete(app.bot, chat_id, msg.message_id))
    else:
        msg = await app.bot.send_message(
            chat_id, text=post_html,
            parse_mode=constants.ParseMode.HTML,
            protect_content=True, reply_markup=markup
        )
        asyncio.create_task(schedule_auto_delete(app.bot, chat_id, msg.message_id))

    if sample_id:
        msg2 = await app.bot.send_video(chat_id, video=sample_id, protect_content=True)
        asyncio.create_task(schedule_auto_delete(app.bot, chat_id, msg2.message_id))

# -------------------- Auto Broadcast --------------------
async def auto_broadcast_new_posts(app: Application):
    while True:
        now = datetime.datetime.utcnow()
        start_of_day = datetime.datetime(now.year, now.month, now.day)
        today_key = start_of_day.strftime("%Y-%m-%d")

        new_posts = list(collection.find({"timestamp": {"$gte": start_of_day}}))
        all_users = list(users_col.find())

        if new_posts and all_users:
            for user in all_users:
                sent_today = user.get("sent_today", {}).get(today_key, [])

                for post in new_posts:
                    keyword = post.get("keyword")
                    if not keyword or keyword in sent_today:
                        continue
                    try:
                        await send_post_to_user(app, user["chat_id"], post)
                        users_col.update_one(
                            {"chat_id": user["chat_id"]},
                            {"$push": {f"sent_today.{today_key}": keyword}}
                        )
                    except:
                        continue

        # run again in 8 hours (3 times per day)
        await asyncio.sleep(8*60*60)

        # cleanup old sent_today entries (older than 2 days)
        cutoff_key = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
        users_col.update_many({}, {"$unset": {f"sent_today.{cutoff_key}": ""}})

# -------------------- Commands --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    users_col.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "joined_at": datetime.datetime.utcnow()
        },
        "$setOnInsert": {"sent_posts": [], "sent_today": {}}},
        upsert=True
    )

    buttons = [
        [
            InlineKeyboardButton("Developer", url="https://t.me/SunsetOfMe"),
            InlineKeyboardButton("Support Channel", url="https://t.me/Cursed_Intelligence")
        ],
        [
            InlineKeyboardButton("How To Download — Click Here", url="https://t.me/tamilmoviedownload0/3")
        ]
    ]
    markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        f"👋 Hi {user.first_name}!\n\n"
        "Welcome! Here you can explore the latest clips, short videos, and posts.\n"
        "Just type the keyword you are interested in, and you'll receive the content instantly.\n\n"
        "Have fun exploring! 🎉",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=markup
)


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

    existing = collection.find_one({"keyword": keyword}) or {}

    # post text
    post_text = None
    if replied:
        post_text = replied.text or replied.caption
    if len(args) >= 2 and not post_text:
        post_text = update.message.text.split(None, 2)[2]

    if post_text and post_text != existing.get("post_html"):
        collection.update_one(
            {"keyword": keyword},
            {"$set": {"post_html": convert_bracket_links_to_html(post_text),
                      "timestamp": datetime.datetime.utcnow(),
                      "keyword": keyword}},
            upsert=True
        )
        saved = True

    # sample video
    if replied and (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        file_id = replied.video.file_id if replied.video else replied.document.file_id
        if file_id != existing.get("sample_file_id"):
            collection.update_one({"keyword": keyword}, {"$set": {"sample_file_id": file_id, "timestamp": datetime.datetime.utcnow()}}, upsert=True)
            saved = True

    # poster image
    if replied and replied.photo:
        photo_file_id = replied.photo[-1].file_id
        if photo_file_id != existing.get("poster_file_id"):
            collection.update_one({"keyword": keyword}, {"$set": {"poster_file_id": photo_file_id, "timestamp": datetime.datetime.utcnow()}}, upsert=True)
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

async def keyword_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    users_col.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "joined_at": datetime.datetime.utcnow()
        },
        "$setOnInsert": {"sent_posts": [], "sent_today": {}}},
        upsert=True
    )
    keyword = norm_kw(update.message.text or "")
    data = collection.find_one({"keyword": keyword})
    if not data:
        return
    await send_post_to_user(context.application, chat_id, data)

async def manual_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /broadcast <keyword>")
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
        except:
            continue
    await update.message.reply_text(f"✅ Broadcasted '{keyword}' to all users.")

# -------------------- Main --------------------
def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN env required")

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attach", attach))
    app.add_handler(CommandHandler("delete", delete_keyword))
    app.add_handler(CommandHandler("broadcast", manual_broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_trigger))

    async def on_startup(app: Application):
        asyncio.create_task(auto_clean_old_entries(app))
        asyncio.create_task(auto_broadcast_new_posts(app))

    app.post_init = on_startup

    print("Bot running…")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
