"""Single-cycle Partner Ads import facade for interactive callers."""

import logging
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config import load_config
from partner_ads import PartnerAdsService
from telegram_service import TelegramService


def execute_partner_ads_check(
    database: Any,
    *,
    force_full_refresh: bool = False,
    today: date | None = None,
    partner_ads: Any | None = None,
    telegram: Any | None = None,
) -> dict[str, Any]:
    """Import Partner Ads incrementally while keeping notifications idempotent."""
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    current_date = today or date.today()
    latest_sale_date = database.get_latest_partner_ads_sale_date()
    full_import = force_full_refresh or latest_sale_date is None
    start_date = (
        current_date.replace(day=1)
        if full_import
        else latest_sale_date - timedelta(days=2)
    )
    result = {
        "import_mode": "full" if full_import else "incremental",
        "start_date": start_date.isoformat(),
        "end_date": current_date.isoformat(),
        "fetched": 0,
        "new": 0,
        "updated": 0,
        "unchanged": 0,
        "duplicates": 0,
        "telegram_sent": 0,
        "telegram_skipped": 0,
        "telegram_errors": 0,
        "api_errors": [],
        "overall_status": "completed",
    }
    try:
        if partner_ads is None or telegram is None:
            config = load_config()
            if partner_ads is None:
                try:
                    partner_ads = PartnerAdsService(
                        config.partner_ads_base_url, config.partner_ads_key
                    )
                except ValueError:
                    completed_at = datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    )
                    result.update({
                        "overall_status": "skipped",
                        "skip_reason": "Partner Ads er ikke konfigureret.",
                        "completed_at": completed_at,
                    })
                    _record_run_safely(
                        database, feature_name="partner_ads_import",
                        status="skipped", started_at=started_at,
                        completed_at=completed_at,
                    )
                    return result
            if telegram is None:
                try:
                    telegram = TelegramService(
                        config.telegram_bot_token, config.telegram_chat_id
                    )
                except ValueError:
                    telegram = _UnavailableTelegram()
        _, sales = partner_ads.fetch_sales(
            start_date=start_date, end_date=current_date
        )
        database.set_system_status("partner_ads", True)
        result["fetched"] = len(sales)
        seen_ids: set[str] = set()
        baseline = not database.is_baseline_initialized()
        for sale in sales:
            kombiid = str(sale.get("kombiid", "")).strip()
            if not kombiid:
                raise ValueError("Partner Ads-salg mangler stabilt kombiid.")
            if kombiid in seen_ids:
                result["duplicates"] += 1
                continue
            seen_ids.add(kombiid)
            outcome = database.upsert_partner_ads_sale(sale)
            if outcome == "created":
                result["new"] += 1
                if baseline:
                    database.set_partner_ads_notification_status(
                        kombiid, "skipped"
                    )
                    result["telegram_skipped"] += 1
                    continue
                try:
                    daily_commission = database.get_today_commission(
                        sale.get("dato", "")
                    )
                    telegram.send_sale(sale, Decimal(daily_commission))
                except Exception:
                    database.set_partner_ads_notification_status(
                        kombiid, "failed"
                    )
                    result["telegram_errors"] += 1
                    result["overall_status"] = "completed_with_warnings"
                    continue
                database.set_partner_ads_notification_status(kombiid, "sent")
                result["telegram_sent"] += 1
            elif outcome == "updated":
                result["updated"] += 1
                result["telegram_skipped"] += 1
            else:
                result["unchanged"] += 1
                result["duplicates"] += 1
                result["telegram_skipped"] += 1
        if baseline:
            database.initialize_sales_baseline([])
    except Exception as error:
        completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            database.set_system_status("partner_ads", False)
        except Exception:
            pass
        _record_run_safely(
            database, feature_name="partner_ads_import", status="error",
            started_at=started_at, completed_at=completed_at,
            error_type=type(error).__name__, error_message=str(error),
        )
        raise
    completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    _record_run_safely(
        database, feature_name="partner_ads_import",
        status=(
            "warning"
            if result["overall_status"] == "completed_with_warnings"
            else "success"
        ),
        started_at=started_at, completed_at=completed_at,
        records_processed=result["fetched"], records_created=result["new"],
        records_updated=result["updated"],
    )
    result["completed_at"] = completed_at
    return result


class _UnavailableTelegram:
    def send_sale(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Telegram er ikke konfigureret.")


def _record_run_safely(database: Any, **values: Any) -> None:
    """Never let telemetry change the outcome of the actual import."""
    try:
        database.save_feature_run(**values)
    except Exception:
        logging.getLogger("partner_ads_dashboard").warning(
            "Kørselsstatus kunne ikke gemmes (%s).",
            values.get("feature_name", "ukendt"),
        )
