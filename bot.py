#!/usr/bin/env python3
"""
Coolie Auto-Post + Sample Video Bot with MongoDB
------------------------------------------------
Admin:
• Reply to TEXT with /attach <keyword> → saves post
• Reply to VIDEO with /attach <keyword> → saves sample video
• /delete <keyword> → deletes post + sample video

User:
• Send <keyword> → bot sends post + sample video
• Auto-delete after 10 min
• protect_content=True
"""

import asyncio, re
from typing import Optional, Tuple
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
URL_RE = re.compile(r"https?://\S+")

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

def extract_special_links_for_buttons(text: str) -> Tuple[Optional[str], Optional[str]]:
    download_url = howto_url = None
    for line in text.splitlines():
        urls = URL_RE.findall(line.strip())
        if not urls:
            continue
        url = urls[0]
        if "🔗" in line and not download_url:
            download_url = url
        if ("How To Download" in line or "🖇️" in line) and not howto_url:
            howto_url = url
    return download_url, howto_url

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
        "Admins:\n• Reply to TEXT/VIDEO with /attach <keyword>\n"
        "• /delete <keyword>\n"
        f"Auto-delete: {config.AUTO_DELETE_SECONDS//60} min, protect_content: ON"
    )

async def attach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /attach <keyword> (reply to TEXT or VIDEO)")
        return
    keyword = norm_kw(args[0])
    replied = update.message.reply_to_message
    saved = False

    # Video → save sample
    if replied and (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        file_id = replied.video.file_id if replied.video else replied.document.file_id
        collection.update_one({"keyword": keyword}, {"$set": {"sample_file_id": file_id}}, upsert=True)
        await update.message.reply_text(f"✅ Sample video attached for '{keyword}'.")
        saved = True

    # Text → save post
    post_text = None
    if replied and replied.text:
        post_text = replied.text
    elif len(args) >= 2:
        post_text = update.message.text.split(None,2)[2]
    if post_text:
        collection.update_one({"keyword": keyword}, {"$set": {"post_html": convert_bracket_links_to_html(post_text)}}, upsert=True)
        await update.message.reply_text(f"✅ Post text attached for '{keyword}'.")
        saved = True

    if not saved:
        await update.message.reply_text("Nothing attached. Reply to TEXT or VIDEO or provide post text after keyword.")

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
    dl_url, how_url = extract_special_links_for_buttons(post_html)
    buttons = []
    if dl_url:
        buttons.append([InlineKeyboardButton("Download — Click Here", url=dl_url)])
    if how_url:
        buttons.append([InlineKeyboardButton("How To Download — Click Here", url=how_url)])
    markup = InlineKeyboardMarkup(buttons) if buttons else None
    msg1 = await context.bot.send_message(chat_id, text=post_html, parse_mode=constants.ParseMode.HTML,
                                         disable_web_page_preview=True, protect_content=True, reply_markup=markup)
    asyncio.create_task(schedule_auto_delete(context, chat_id, msg1.message_id))
    if sample_id := data.get("sample_file_id"):
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
