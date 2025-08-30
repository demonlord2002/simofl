# config.py

import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8430877877:AAFi6U6G4fTzHDFGp2p4JkwatMi5YK81KqU")
OWNER_IDS = {int(uid.strip()) for uid in os.environ.get("OWNER_IDS", "7590607726").split(",") if uid.strip().isdigit()}
AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "600"))  # default 10 min
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://vellina095:vellina095@cluster0.l1zrwj3.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
FORCE_SUB_CHANNEL = "@The_Architect_II"  # or channel ID -100xxxxxxxxxx
DB_NAME = os.environ.get("DB_NAME", "coolie_bot")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "keywords")
