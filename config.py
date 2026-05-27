"""Smart Loops MCP — Configuration"""

import os

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.environ.get("SMARTLOOPS_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("SMARTLOOPS_TELEGRAM_CHAT_ID", "")

# Database
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "smartloops.db")

# Project defaults
SMARTLOOPS_DIR = ".smartloops"  # created inside each registered project
CLAUDE_LOG_FILE = "claude_log.md"
RALPH_JOURNAL_FILE = "ralph_journal.md"
WORLD_MODEL_FILE = "WORLD_MODEL.json"
NEXT_WAKEUP_FILE = "next_wakeup.json"

# Wake-up defaults (minutes)
WAKE_SIMPLE = 10
WAKE_LARGE_FEATURE = 180
WAKE_BLOCKED = 15
WAKE_HIGH_CONFIDENCE = 360
WAKE_INACTIVE = 1440  # 24 hours

# Stuck detection thresholds
STUCK_NO_COMMIT_HOURS = 4
STUCK_LOW_CONFIDENCE = 40
STUCK_MAX_REPEATS = 3
