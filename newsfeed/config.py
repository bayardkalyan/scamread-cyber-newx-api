"""Settings, read from environment variables with sensible defaults."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Claude
MODEL = os.environ.get("NEWSFEED_MODEL", "claude-haiku-5-5")
MAX_TOKENS = _int("NEWSFEED_MAX_TOKENS", 8000)
BATCH_SIZE = _int("NEWSFEED_BATCH_SIZE", 12)
EXPLAIN_MAX_PER_RUN = _int("NEWSFEED_EXPLAIN_MAX_PER_RUN", 24)  # "Learn the concept" notes per run
EXPLAIN_BATCH_SIZE = _int("NEWSFEED_EXPLAIN_BATCH_SIZE", 8)

# Fetching
SOURCES_FILE = Path(os.environ.get("NEWSFEED_SOURCES", PACKAGE_DIR / "sources.json"))
USER_AGENT = os.environ.get("NEWSFEED_USER_AGENT", "ScamReadNewsBot/1.0 (+https://scamread.com)")
FETCH_TIMEOUT = _int("NEWSFEED_FETCH_TIMEOUT", 20)
MAX_AGE_HOURS = _int("NEWSFEED_MAX_AGE_HOURS", 48)          # ignore articles older than this
MAX_ITEMS_PER_SOURCE = _int("NEWSFEED_MAX_ITEMS_PER_SOURCE", 25)
MAX_NEW_PER_RUN = _int("NEWSFEED_MAX_NEW_PER_RUN", 60)      # caps Claude cost per run

# Output
FEED_LIMIT = _int("NEWSFEED_FEED_LIMIT", 60)                 # stories in feed.json
TOP_N = _int("NEWSFEED_TOP_N", 5)                            # stories in top.json
TOP_WINDOW_HOURS = _int("NEWSFEED_TOP_WINDOW_HOURS", 24)
STORY_RETENTION_DAYS = _int("NEWSFEED_STORY_RETENTION_DAYS", 7)
SEEN_RETENTION_DAYS = _int("NEWSFEED_SEEN_RETENTION_DAYS", 14)
TEMPLATE_DIR = REPO_DIR / "public_template"
