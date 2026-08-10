"""Headless single Partner Ads sales check for Windows Task Scheduler.

Runs one idempotent Partner Ads import and sends a Telegram notification for
each genuinely new sale, then exits. Meant to be triggered every 30 minutes.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.database import Database
from core.partner_ads_import import execute_partner_ads_check

LOG_PATH = PROJECT_ROOT / "logs" / "scheduled_tasks.log"


def configure_logging() -> logging.Logger:
    """Log to a shared file so scheduled runs leave a visible trail."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("scheduled.monitor_sales")
    if not logger.handlers:
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def open_database() -> Database:
    default_path = PROJECT_ROOT / "data" / "affiliate_manager.db"
    path = Path(os.getenv("SU_MEDIA_DATABASE_PATH", default_path))
    database = Database(path)
    database.initialize()
    return database


def run(
    database: Any,
    *,
    check: Callable[..., dict] = execute_partner_ads_check,
    logger: logging.Logger | None = None,
) -> int:
    """Run one sales check. Returns a process exit code (0 = success)."""
    logger = logger or logging.getLogger("scheduled.monitor_sales")
    try:
        result = check(database)
    except Exception as error:
        # Error details are sanitized: only the type is safe to record.
        logger.error("Salgstjek fejlede: %s", type(error).__name__)
        return 1
    logger.info(
        "Salgstjek: %s hentet, %s nye, %s Telegram sendt, %s Telegram-fejl.",
        result.get("fetched", 0),
        result.get("new", 0),
        result.get("telegram_sent", 0),
        result.get("telegram_errors", 0),
    )
    return 0


def main() -> int:
    logger = configure_logging()
    database = open_database()
    try:
        return run(database, logger=logger)
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
