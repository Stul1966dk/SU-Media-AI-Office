"""Shared Plausible connection checks for all active websites."""

from datetime import date, timedelta
from typing import Any

from connectors.plausible_connector import PlausibleConnector


class PlausibleIntegration:
    """Check Stats API access without importing or persisting statistics."""

    def __init__(self, database: Any, connector: Any | None = None) -> None:
        self.database = database
        self.connector = connector or PlausibleConnector()

    def test_active_websites(self) -> dict[str, Any]:
        websites = [
            item["website"] for item in self.database.get_all_websites()
            if item.get("active") and item.get("status") not in
            {"phasing_out", "archived", "cancelled"}
        ]
        metric_date = date.today() - timedelta(days=1)
        results = []
        for website in websites:
            try:
                visitors = self.connector.get_daily_visitors(
                    website, metric_date
                )
            except Exception as error:
                results.append({
                    "website": website,
                    "ok": False,
                    "message": str(error),
                    "visitors": None,
                })
            else:
                results.append({
                    "website": website,
                    "ok": True,
                    "message": "Forbindelse OK",
                    "visitors": visitors,
                })
        return {
            "ok": bool(results) and all(item["ok"] for item in results),
            "tested": len(results),
            "failed": sum(not item["ok"] for item in results),
            "date": metric_date.isoformat(),
            "results": results,
        }
