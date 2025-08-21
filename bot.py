"""
FileBot (LinkPays shortener frontend)
Features:
- Admin commands: /addfile, /updatefile, /removefile, /listfiles, /logs
- Users get link by clicking: https://t.me/YourBot?start=<file_id>
- When user triggers the bot with a file_id, bot:
    1) looks up original (gofile/drive) link in MongoDB
    2) converts it to LinkPays shortlink via LinkPays API
    3) sends the shortlink to user with a stylish Simon-style message
    4) auto-deletes the bot's sent message after 10 minutes (600s)
    5) logs the access in MongoDB
Character Style: Fully Simon (villain swag mode 😈)
Developer: @SunsetOfMe
"""

import logging
import requests
import asyncio
from datetime import datetime, timezone, timedelta
from pyrogram import Client, filters
from pymongo import MongoClient
from config import Config   # <<--- import config

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- MongoDB ----------------
mongo_client = MongoClient(Config.MONGO_URI)
db = mongo_client["files_db"]
files_col = db["files"]
logs_col = db["access_logs"]

# ---------------- Pyrogram Client ----------------
app = Client("FileBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN)

# ---------------- Helper: shorten_url ----------------
def shorten_url(long_url: str) -> str:
    """Convert a long file URL to LinkPays shortlink using LinkPays API."""
    try:
        api_url = f"https://linkpays.in/api?api={Config.LINKPAYS_API}&url={long_url}"
        res = requests.get(api_url, timeout=10).json()
        if isinstance(res, dict) and res.get("status") == "success" and res.get("shortenedUrl"):
            return res["shortenedUrl"]
        else:
            logger.warning(f"LinkPays returned error/unknown: {res}")
            return long_url
    except Exception as e:
        logger.exception("Shorten error")
        return long_url

# ---------------- Background deletion task ----------------
async def schedule_delete_and_update_log(chat_id: int, message_id: int, log_id, delay: int = Config.AUTO_DELETE_SECONDS):
    """Sleep 'delay' seconds, delete the bot's message, and mark log as expired."""
    await asyncio.sleep(delay)
    deleted = False
    try:
        await app.delete_messages(chat_id, message_id)
        deleted = True
    except Exception as e:
        logger.warning(f"Failed to delete bot message {message_id} in chat {chat_id}: {e}")

    try:
        logs_col.update_one(
            {"_id": log_id},
            {"$set": {"deleted": deleted, "deleted_at": datetime.now(timezone.utc)}}
        )
    except Exception as e:
        logger.warning(f"Failed to update log {log_id}: {e}")

# ---------------- /start command ----------------
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    args = message.text.split(maxsplit=1)

    # Case: user clicked special link
    if len(args) == 2:
        file_id = args[1].strip().lower()
        data = files_col.find_one({"_id": file_id})
        if not data:
            await message.reply_text("❌ File illa da. Admin kitta poi pesu.")
            return

        original_link = data.get("link")
        short_link = shorten_url(original_link)

        reply_text = (
            f"📥 **{file_id.title()} Download Ready**\n\n"
            f"👉 {short_link}\n\n"
            f"⏳ Idhu **10 nimisham** ku dhaan. Apram automatic ah poidum.\n\n"
            f"😈 *Simon Dialogue:* \"Naan sonna time ku mudinchidum… link ah open pannu, illana unga chance kedaikathu da.\" \n\n"
            f"👨‍💻 Powered by @SunsetOfMe"
        )

        msg = await message.reply_text(reply_text, disable_web_page_preview=True)

        # Log access
        log_doc = {
            "file_id": file_id,
            "original_link": original_link,
            "short_link": short_link,
            "user_id": message.from_user.id,
            "username": getattr(message.from_user, "username", None),
            "first_name": getattr(message.from_user, "first_name", None),
            "requested_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=Config.AUTO_DELETE_SECONDS),
            "message_id": msg.message_id,
            "chat_id": msg.chat.id,
            "deleted": False
        }
        res = logs_col.insert_one(log_doc)
        log_id = res.inserted_id

        asyncio.create_task(schedule_delete_and_update_log(msg.chat.id, msg.message_id, log_id, Config.AUTO_DELETE_SECONDS))

    # Case: user typed /start alone
    else:
        welcome_text = (
            "👋 Vanakkam da mapla!\n\n"
            "🔗 Special link kuduthaa dhaan file kedaikum.\n"
            "⏳ Naa kudukkara link 10 nimisham ku dhaan irukkum.\n\n"
            "😈 *Simon-style:* \"Kai la irukkura vaippu use pannunga da… apram kai veliya poidum.\" \n\n"
            "👨‍💻 Powered by @SunsetOfMe"
        )
        await message.reply_text(welcome_text)

# ---------------- Admin Commands ----------------
@app.on_message(filters.command("addfile") & filters.private)
async def add_file(client, message):
    if message.from_user.id != Config.ADMIN_ID:
        return await message.reply_text("❌ Nee admin illa da, ozhunga iru.")

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply_text("Usage: /addfile <file_id> <link>")

    file_id, file_link = parts[1].lower(), parts[2]
    files_col.update_one({"_id": file_id}, {"$set": {"link": file_link}}, upsert=True)
    await message.reply_text(f"✅ File add aagiduchu da: `{file_id}`")

@app.on_message(filters.command("updatefile") & filters.private)
async def update_file(client, message):
    if message.from_user.id != Config.ADMIN_ID:
        return await message.reply_text("❌ Nee admin illa da.")

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply_text("Usage: /updatefile <file_id> <new_link>")

    file_id, new_link = parts[1].lower(), parts[2]
    result = files_col.update_one({"_id": file_id}, {"$set": {"link": new_link}})
    if result.matched_count:
        await message.reply_text(f"♻️ Link update panniduchu da: `{file_id}`")
    else:
        await message.reply_text("❌ File illa da. First /addfile pannu.")

@app.on_message(filters.command("removefile") & filters.private)
async def remove_file(client, message):
    if message.from_user.id != Config.ADMIN_ID:
        return await message.reply_text("❌ Nee admin illa da.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /removefile <file_id>")

    file_id = parts[1].lower()
    result = files_col.delete_one({"_id": file_id})
    if result.deleted_count:
        await message.reply_text(f"🗑️ File remove panniduchu da: `{file_id}`")
    else:
        await message.reply_text("❌ File kidaikkala da.")

@app.on_message(filters.command("listfiles") & filters.private)
async def list_files(client, message):
    if message.from_user.id != Config.ADMIN_ID:
        return await message.reply_text("❌ Nee admin illa da.")

    docs = files_col.find({}, {"_id": 1})
    items = [d["_id"] for d in docs]
    if not items:
        return await message.reply_text("😑 File onnum illa da.")
    await message.reply_text("📂 Stored files:\n\n" + "\n".join(f"👉 {x}" for x in items))

@app.on_message(filters.command("logs") & filters.private)
async def view_logs(client, message):
    if message.from_user.id != Config.ADMIN_ID:
        return await message.reply_text("❌ Nee admin illa da.")

    parts = message.text.split(maxsplit=1)
    n = 10
    if len(parts) == 2 and parts[1].isdigit():
        n = min(100, int(parts[1]))

    docs = logs_col.find().sort("requested_at", -1).limit(n)
    lines = []
    for d in docs:
        t = d.get("requested_at")
        user = d.get("username") or d.get("first_name") or d.get("user_id")
        lines.append(f"{t} • {d.get('file_id')} • {user} • deleted={d.get('deleted', False)}")
    if not lines:
        return await message.reply_text("😑 Logs onnum illa da.")
    await message.reply_text("📜 Recent logs:\n\n" + "\n".join(lines))

# ---------------- Run Bot ----------------
if __name__ == "__main__":
    app.run()
