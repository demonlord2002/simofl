"""
config.py
Stores all environment variables and configuration.
"""

import os

class Config:
    # Telegram API
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI")

    # LinkPays Shortener
    LINKPAYS_API = os.getenv("LINKPAYS_API")

    # Admin
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

    # Auto delete seconds (default 600s = 10 min)
    AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS", "600"))
