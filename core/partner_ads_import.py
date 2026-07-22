"""Single-cycle Partner Ads import facade for interactive callers."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config import load_config
from main import run_check
from partner_ads import PartnerAdsService
from telegram_service import TelegramService


def execute_partner_ads_check(database: Any) -> dict[str, Any]:
    """Run exactly one existing fetch/persist/notification cycle."""
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    config = load_config()
    try:
        fetched, new = run_check(
            PartnerAdsService(config.partner_ads_base_url, config.partner_ads_key),
            TelegramService(config.telegram_bot_token, config.telegram_chat_id),
            database,
            logging.getLogger("partner_ads_dashboard"),
        )
    except Exception as error:
        completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        _record_run_safely(
            database, feature_name="partner_ads_import", status="error",
            started_at=started_at, completed_at=completed_at,
            error_type=type(error).__name__, error_message=str(error),
        )
        raise
    completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    _record_run_safely(
        database, feature_name="partner_ads_import", status="success",
        started_at=started_at, completed_at=completed_at,
        records_processed=fetched, records_created=new,
    )
    return {
        "fetched": fetched,
        "new": new,
        "duplicates": max(0, fetched - new),
        "telegram_sent": new,
        "completed_at": completed_at,
    }


def _record_run_safely(database: Any, **values: Any) -> None:
    """Never let telemetry change the outcome of the actual import."""
    try:
        database.save_feature_run(**values)
    except Exception:
        logging.getLogger("partner_ads_dashboard").warning(
            "Kørselsstatus kunne ikke gemmes (%s).",
            values.get("feature_name", "ukendt"),
        )
