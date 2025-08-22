#!/usr/bin/env python3
"""
Coolie Auto-Post + Sample Video Bot with MongoDB
------------------------------------------------
Admin:
• Reply to TEXT or IMAGE with /attach <keyword> → saves post
• Reply to VIDEO with /attach <keyword> → saves sample video
• /delete <keyword> → deletes post + sample video

User:
• Send <keyword> → bot sends post + sample video
• Auto-delete after 10 min
• protect_content=True
• Fixed How To Download button included automatically
"""

import asyncio, re
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from pymongo import MongoClient

import config

# -------------------- MongoDB --------------------
client = MongoClient(config.MONGO_URI)
db = client[config.DB_NAME]
collection = db[config.COLLECTION_NAME]

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

async def schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await asyncio.sleep(config.AUTO_DELETE_SECONDS)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

# -------------------- Commands --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 Hi! Send a saved keyword (e.g., 'coolie') to get post + sample video.\n\n"
        "Admins:\n• Reply to TEXT/IMAGE/VIDEO with /attach <keyword>\n"
        "• /delete <keyword>\n"
        f"Auto-delete: {config.AUTO_DELETE_SECONDS//60} min, protect_content: ON"
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

    # Text or caption → save post
    post_text = None
    if replied:
        post_text = replied.text or replied.caption
    if len(args) >= 2 and not post_text:
        post_text = update.message.text.split(None, 2)[2]
    if post_text:
        collection.update_one(
            {"keyword": keyword},
            {"$set": {"post_html": convert_bracket_links_to_html(post_text)}},
            upsert=True
        )
        saved = True

    # Video → save sample
    if replied and (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        file_id = replied.video.file_id if replied.video else replied.document.file_id
        collection.update_one({"keyword": keyword}, {"$set": {"sample_file_id": file_id}}, upsert=True)
        saved = True

    # Image → save poster
    if replied and replied.photo:
        photo_file_id = replied.photo[-1].file_id  # highest resolution
        collection.update_one({"keyword": keyword}, {"$set": {"poster_file_id": photo_file_id}}, upsert=True)
        saved = True

    if saved:
        await update.message.reply_text(f"✅ Content attached for '{keyword}'.")
    else:
        await update.message.reply_text("Nothing attached. Reply to TEXT, IMAGE, or VIDEO or provide post text after keyword.")

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
        await update.message.reply_text(f"🗑️ '{keyword}' deleted successfully.")
    else:
        await update.message.reply_text(f"'{keyword}' not found.")

async def keyword_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = norm_kw(update.message.text or "")
    data = collection.find_one({"keyword": keyword})
    if not data:
        return

    chat_id = update.effective_chat.id
    post_html = data.get("post_html") or html_escape(update.message.text)
    poster_id = data.get("poster_file_id")
    sample_id = data.get("sample_file_id")

    # Fixed How To Download button
    buttons = [[InlineKeyboardButton("How To Download — Click Here", url="https://t.me/tamilmoviedownload0/3")]]
    markup = InlineKeyboardMarkup(buttons)

    # Send poster + text if poster exists
    if poster_id:
        msg = await context.bot.send_photo(
            chat_id, photo=poster_id, caption=post_html, parse_mode=constants.ParseMode.HTML,
            protect_content=True, reply_markup=markup
        )
        asyncio.create_task(schedule_auto_delete(context, chat_id, msg.message_id))
    else:
        msg = await context.bot.send_message(
            chat_id, text=post_html, parse_mode=constants.ParseMode.HTML,
            protect_content=True, reply_markup=markup
        )
        asyncio.create_task(schedule_auto_delete(context, chat_id, msg.message_id))

    # Send sample video if exists
    if sample_id:
        msg2 = await context.bot.send_video(chat_id, video=sample_id, protect_content=True)
        asyncio.create_task(schedule_auto_delete(context, chat_id, msg2.message_id))

# -------------------- Main --------------------
def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN env required")
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attach", attach))
    app.add_handler(CommandHandler("delete", delete_keyword))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_trigger))
    print("Bot running…")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
