"""Fault-isolated import of daily Plausible visitor totals."""

from datetime import date, timedelta
from typing import Any

from connectors.plausible_connector import PlausibleConnector


class PlausibleImportService:
    """Import a bounded daily period for every active website."""

    def __init__(
        self, database: Any, *, connector: Any | None = None, days: int = 30
    ) -> None:
        self.database = database
        self.connector = connector or PlausibleConnector()
        self.days = days

    def import_active_websites(
        self, reference_date: date | None = None
    ) -> dict[str, Any]:
        """Continue after individual site failures and return a clear summary."""
        end_date = (reference_date or date.today()) - timedelta(days=1)
        start_date = end_date - timedelta(days=self.days - 1)
        websites = [
            item["website"] for item in self.database.get_all_websites()
            if item.get("active") and item.get("status") != "phasing_out"
        ]
        result: dict[str, Any] = {
            "websites_attempted": len(websites),
            "websites_updated": 0,
            "datapoints_saved": 0,
            "rows_created": 0,
            "rows_updated": 0,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "errors": [],
        }
        for website in websites:
            try:
                daily = self.connector.get_daily_visitors_range(
                    website, start_date, end_date
                )
                for metric_date, visitors in daily.items():
                    created = self.database.upsert_plausible_daily_metric(
                        website_id=website,
                        metric_date=metric_date,
                        visitors=visitors,
                    )
                    result["datapoints_saved"] += 1
                    result["rows_created" if created else "rows_updated"] += 1
                result["websites_updated"] += 1
            except Exception as error:
                result["errors"].append({
                    "website": website,
                    "error_type": type(error).__name__,
                    "message": str(error)[:200],
                })
        result["websites_failed"] = len(result["errors"])
        return result
