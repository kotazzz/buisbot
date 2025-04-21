import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration from environment variables
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "business_bot")
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_database.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Bot owner ID for special commands
BOT_OWNER_ID = 782491733
