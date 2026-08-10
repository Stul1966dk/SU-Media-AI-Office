"""Headless daily data refresh for Windows Task Scheduler.

Runs the full deterministic refresh pipeline (Website Registry, Partner Ads,
Search Console, Plausible, SEO History, Website Intelligence, experiment
monitoring, system status and priority scores) once, then exits. No analytical
AI calls are triggered. Meant to be triggered once per day.
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
from core.data_refresh_service import DataRefreshService

LOG_PATH = PROJECT_ROOT / "logs" / "scheduled_tasks.log"


def configure_logging() -> logging.Logger:
    """Log to a shared file so scheduled runs leave a visible trail."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("scheduled.daily_refresh")
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
    service_factory: Callable[[Any], Any] = DataRefreshService,
    logger: logging.Logger | None = None,
) -> int:
    """Run the full refresh once. Returns a process exit code (0 = success)."""
    logger = logger or logging.getLogger("scheduled.daily_refresh")
    try:
        result = service_factory(database).refresh_all(website_ids=None)
    except Exception as error:
        # Error details are sanitized: only the type is safe to record.
        logger.error("Dagligt refresh fejlede: %s", type(error).__name__)
        return 1
    steps = result.get("steps", [])
    failed = [step for step in steps if step.get("status") == "error"]
    logger.info(
        "Dagligt refresh: %s trin kørt, %s fejlede.", len(steps), len(failed)
    )
    for step in failed:
        logger.warning("Trin fejlede: %s.", step.get("step", "ukendt"))
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
