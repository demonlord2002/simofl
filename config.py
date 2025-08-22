# config.py

import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_IDS = {int(uid.strip()) for uid in os.environ.get("OWNER_IDS", "").split(",") if uid.strip().isdigit()}
AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "600"))  # default 10 min
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "coolie_bot")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "keywords")
