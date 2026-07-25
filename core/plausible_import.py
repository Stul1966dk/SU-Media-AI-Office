"""Fault-isolated import of daily Plausible visitor totals."""

from datetime import date, timedelta
from typing import Any

from connectors.plausible_connector import (
    PlausibleConnector,
    PlausibleConnectorError,
)


DEFAULT_PLAUSIBLE_IMPORT_DAYS = 30
PLAUSIBLE_OVERLAP_DAYS = 2
INACTIVE_STATUSES = {"inactive", "phasing_out", "archived", "cancelled"}


class PlausibleImportService:
    """Import a bounded daily period for every active website."""

    def __init__(
        self, database: Any, *, connector: Any | None = None,
        days: int = DEFAULT_PLAUSIBLE_IMPORT_DAYS,
    ) -> None:
        self.database = database
        self.connector = connector or PlausibleConnector()
        self.days = days

    def import_active_websites(
        self,
        reference_date: date | None = None,
        website_ids: list[str] | None = None,
        *,
        force_full_refresh: bool = True,
    ) -> dict[str, Any]:
        """Continue after individual site failures and return a clear summary."""
        end_date = (reference_date or date.today()) - timedelta(days=1)
        full_start_date = end_date - timedelta(days=self.days - 1)
        selected = set(website_ids) if website_ids is not None else None
        websites = [
            item for item in self.database.get_all_websites()
            if selected is None or item["website"] in selected
        ]
        result: dict[str, Any] = {
            "websites_evaluated": len(websites),
            "websites_attempted": 0,
            "websites_processed": 0,
            "websites_skipped": 0,
            "websites_updated": 0,
            "websites_failed": 0,
            "datapoints_saved": 0,
            "rows_created": 0,
            "rows_updated": 0,
            "period_start": full_start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "earliest_fetched_date": full_start_date.isoformat(),
            "latest_fetched_date": end_date.isoformat(),
            "import_mode": "full" if force_full_refresh else "incremental",
            "overall_status": "completed",
            "website_results": [],
            "errors": [],
        }
        fetched_start_dates: list[date] = []
        import_modes: list[str] = []
        for website_record in websites:
            website = website_record["website"]
            configuration = self._configuration(website_record)
            if configuration["skip_reason"]:
                result["websites_skipped"] += 1
                result["website_results"].append({
                    "website_id": website,
                    "domain": configuration["site_id"] or website,
                    "start_date": None,
                    "end_date": end_date.isoformat(),
                    "import_mode": None,
                    "rows_created": 0,
                    "rows_updated": 0,
                    "status": "skipped",
                    "reason": configuration["skip_reason"],
                    "error_type": None,
                })
                continue
            site_id = configuration["site_id"]
            result["websites_attempted"] += 1
            result["websites_processed"] += 1
            start_date: date | None = None
            import_mode: str | None = None
            try:
                latest_stored = (
                    None if force_full_refresh
                    else self.database.get_latest_plausible_metric_date(
                        website
                    )
                )
                if latest_stored:
                    start_date = (
                        date.fromisoformat(latest_stored)
                        - timedelta(days=PLAUSIBLE_OVERLAP_DAYS)
                    )
                    import_mode = "incremental"
                else:
                    start_date = full_start_date
                    import_mode = "full"
                fetched_start_dates.append(start_date)
                import_modes.append(import_mode)
                daily = self.connector.get_daily_visitors_range(
                    site_id, start_date, end_date
                )
                created_count = 0
                updated_count = 0
                for metric_date, visitors in daily.items():
                    created = self.database.upsert_plausible_daily_metric(
                        website_id=website,
                        metric_date=metric_date,
                        visitors=visitors,
                    )
                    result["datapoints_saved"] += 1
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                result["rows_created"] += created_count
                result["rows_updated"] += updated_count
                result["websites_updated"] += 1
                result["website_results"].append({
                    "website_id": website,
                    "domain": site_id,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "import_mode": import_mode,
                    "rows_created": created_count,
                    "rows_updated": updated_count,
                    "status": "completed",
                    "reason": None,
                    "error_type": None,
                })
            except Exception as error:
                error_type = type(error).__name__
                if self._is_missing_integration_error(error):
                    result["websites_processed"] -= 1
                    result["websites_skipped"] += 1
                    result["website_results"].append({
                        "website_id": website,
                        "domain": site_id,
                        "start_date": (
                            start_date.isoformat()
                            if start_date is not None else None
                        ),
                        "end_date": end_date.isoformat(),
                        "import_mode": import_mode,
                        "rows_created": 0,
                        "rows_updated": 0,
                        "status": "skipped",
                        "reason": "Plausible er ikke aktiveret",
                        "error_type": None,
                    })
                    continue
                message = (
                    str(error)[:200]
                    if isinstance(error, PlausibleConnectorError)
                    else "Plausible-importen fejlede for websitet."
                )
                error_result = {
                    "website": website,
                    "error_type": error_type,
                    "message": message,
                }
                result["errors"].append(error_result)
                result["website_results"].append({
                    "website_id": website,
                    "domain": site_id,
                    "start_date": (
                        start_date.isoformat()
                        if start_date is not None else None
                    ),
                    "end_date": end_date.isoformat(),
                    "import_mode": import_mode,
                    "rows_created": 0,
                    "rows_updated": 0,
                    "status": "failed",
                    "reason": message,
                    "error_type": error_type,
                })
        result["websites_failed"] = len(result["errors"])
        if fetched_start_dates:
            earliest = min(fetched_start_dates)
            result["period_start"] = earliest.isoformat()
            result["earliest_fetched_date"] = earliest.isoformat()
            result["import_mode"] = (
                import_modes[0]
                if len(set(import_modes)) == 1
                else "mixed"
            )
        if result["websites_failed"]:
            result["overall_status"] = (
                "completed_with_warnings"
                if result["websites_updated"] else "failed"
            )
        elif not result["websites_processed"]:
            result["overall_status"] = "skipped"
        return result

    @staticmethod
    def _configuration(website: dict[str, Any]) -> dict[str, str | None]:
        """Resolve optional explicit Plausible configuration safely."""
        if not website.get("active") or website.get("status") in INACTIVE_STATUSES:
            return {
                "site_id": None,
                "skip_reason": "Website er inaktivt",
            }
        if (
            "plausible_enabled" in website
            and not website.get("plausible_enabled")
        ):
            return {
                "site_id": None,
                "skip_reason": "Plausible er ikke aktiveret",
            }
        explicit_site_id = website.get("plausible_site_id")
        if "plausible_site_id" in website:
            site_id = str(explicit_site_id or "").strip()
        else:
            site_id = str(website.get("website") or "").strip()
            if "." not in site_id:
                site_id = ""
        if not site_id:
            return {
                "site_id": None,
                "skip_reason": "Plausible-site-id mangler",
            }
        return {"site_id": site_id, "skip_reason": None}

    @staticmethod
    def _is_missing_integration_error(error: Exception) -> bool:
        return (
            isinstance(error, PlausibleConnectorError)
            and str(error)
            == "Plausible kunne ikke finde statistik for det valgte website."
        )
