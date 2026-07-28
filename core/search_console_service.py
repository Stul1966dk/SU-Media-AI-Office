"""Search Console property and daily metric synchronization service."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from integrations.search_console import SearchConsoleConnector

from .database import Database
from .website_registry import WebsiteRegistry


DEFAULT_DAILY_IMPORT_DAYS = 35
DAILY_IMPORT_OVERLAP_DAYS = 5


@dataclass(frozen=True)
class SearchConsoleSyncResult:
    """Structured status from property discovery."""

    connection_ok: bool
    total: int
    matched: int
    unmatched: int
    properties: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class SearchConsoleDataSyncResult:
    """Aggregate result from a daily metric synchronization."""

    properties_processed: int
    properties_failed: int
    rows_created: int
    rows_updated: int
    start_date: str
    end_date: str
    earliest_fetched_date: str
    latest_fetched_date: str
    import_mode: str
    errors: list[dict[str, str]]
    property_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SearchConsoleDimensionSyncResult:
    """Aggregate result for two 28-day dimensional imports."""

    properties_processed: int
    properties_failed: int
    page_rows: int
    query_rows: int
    page_query_rows: int
    rows_created: int
    rows_updated: int
    errors: list[dict[str, str]]
    properties_evaluated: int = 0
    properties_skipped: int = 0
    api_calls_executed: int = 0
    api_calls_avoided: int = 0
    property_results: list[dict[str, Any]] = field(default_factory=list)
    refresh_mode: str = "normal"
    overall_status: str = "completed"


class SearchConsoleService:
    """Fetch, match, persist, and compare Search Console data."""

    def __init__(
        self,
        connector: SearchConsoleConnector,
        database: Database,
        website_registry: WebsiteRegistry,
        logger: logging.Logger | None = None,
    ) -> None:
        self.connector = connector
        self.database = database
        self.website_registry = website_registry
        self.logger = logger or logging.getLogger(__name__)

    def synchronize(self) -> SearchConsoleSyncResult:
        """Fetch all properties, match domains, and upsert each property."""
        self.connector.authenticate()
        properties = self.connector.list_properties()
        available_site_urls = {
            str(item["site_url"]) for item in properties
        }
        self.database.deactivate_missing_search_console_properties(
            available_site_urls
        )
        matched = 0
        stored: list[dict[str, Any]] = []
        for item in properties:
            website = self._match_website(item["site_url"])
            website_id = website["website"] if website else None
            if website_id:
                matched += 1
            self.database.upsert_search_console_property(
                site_url=item["site_url"],
                permission_level=item["permission_level"],
                website_id=website_id,
                active=True,
            )
            stored.append({**item, "website_id": website_id})

        return SearchConsoleSyncResult(
            connection_ok=True,
            total=len(stored),
            matched=matched,
            unmatched=len(stored) - matched,
            properties=stored,
        )

    def sync_all_properties(
        self,
        days: int = DEFAULT_DAILY_IMPORT_DAYS,
        website_ids: list[str] | None = None,
        *,
        property_urls: list[str] | None = None,
        force_full_refresh: bool = True,
        reference_date: date | None = None,
    ) -> SearchConsoleDataSyncResult:
        """Synchronize daily data for every active, matched property."""
        if days < 1:
            raise ValueError("days skal være mindst 1.")
        end_date = reference_date or date.today()
        full_start_date = end_date - timedelta(days=days - 1)
        active_websites = set(self.database.get_active_website_ids())
        selected_properties = (
            set(property_urls) if property_urls is not None else None
        )
        properties = [
            item
            for item in self.database.get_search_console_properties()
            if item["active"] and item["website_id"]
            and item["website_id"] in active_websites
            and (website_ids is None or item["website_id"] in website_ids)
            and (
                selected_properties is None
                or item["site_url"] in selected_properties
            )
        ]
        processed = 0
        failed = 0
        created = 0
        updated = 0
        errors: list[dict[str, str]] = []
        fetched_start_dates: list[date] = []
        property_modes: list[str] = []
        property_results: list[dict[str, Any]] = []

        for item in properties:
            processed += 1
            try:
                latest_stored = (
                    None if force_full_refresh
                    else self.database.get_latest_search_console_metric_date(
                        item["website_id"]
                    )
                )
                if latest_stored:
                    property_start_date = (
                        date.fromisoformat(latest_stored)
                        - timedelta(days=DAILY_IMPORT_OVERLAP_DAYS)
                    )
                    property_mode = "incremental"
                else:
                    property_start_date = full_start_date
                    property_mode = "full"
                fetched_start_dates.append(property_start_date)
                property_modes.append(property_mode)
                result = self.sync_property(
                    site_url=item["site_url"],
                    website_id=item["website_id"],
                    days=days,
                    start_date=property_start_date,
                    end_date=end_date,
                )
            except Exception as error:
                failed += 1
                error_type = type(error).__name__
                errors.append(
                    {
                        "site_url": item["site_url"],
                        "error_type": error_type,
                    }
                )
                self.logger.error(
                    "Search Console-property fejlede: %s (%s)",
                    item["site_url"],
                    error_type,
                )
                continue
            created += result["rows_created"]
            updated += result["rows_updated"]
            property_results.append({
                "site_url": item["site_url"],
                "website_id": item["website_id"],
                "rows_created": result["rows_created"],
                "rows_updated": result["rows_updated"],
                "rows_changed": result["rows_changed"],
            })

        import_mode = (
            property_modes[0]
            if property_modes and len(set(property_modes)) == 1
            else "mixed" if property_modes
            else "full" if force_full_refresh
            else "incremental"
        )
        earliest = min(fetched_start_dates, default=full_start_date)
        return SearchConsoleDataSyncResult(
            properties_processed=processed,
            properties_failed=failed,
            rows_created=created,
            rows_updated=updated,
            start_date=earliest.isoformat(),
            end_date=end_date.isoformat(),
            earliest_fetched_date=earliest.isoformat(),
            latest_fetched_date=end_date.isoformat(),
            import_mode=import_mode,
            errors=errors,
            property_results=property_results,
        )

    def sync_dimensions(
        self, website_ids: list[str] | None = None,
        reference_date: date | None = None,
        *,
        property_urls: list[str] | None = None,
        force_dimensions_refresh: bool = False,
        new_daily_website_ids: set[str] | None = None,
        reference_time: datetime | None = None,
    ) -> SearchConsoleDimensionSyncResult:
        """Import page, query, and page-query rows for two 28-day periods."""
        today = reference_date or date.today()
        now = reference_time or datetime.now().astimezone()
        if now.tzinfo is None:
            now = now.astimezone()
        new_daily = new_daily_website_ids or set()
        current_end = today - timedelta(days=1)
        current_start = current_end - timedelta(days=27)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=27)
        periods = (
            (previous_start, previous_end), (current_start, current_end),
        )
        active_websites = set(self.database.get_active_website_ids())
        selected_properties = (
            set(property_urls) if property_urls is not None else None
        )
        properties = [
            item for item in self.database.get_search_console_properties()
            if item["active"] and item["website_id"]
            and item["website_id"] in active_websites
            and (website_ids is None or item["website_id"] in website_ids)
            and (
                selected_properties is None
                or item["site_url"] in selected_properties
            )
        ]
        totals = {"page": 0, "query": 0, "page_query": 0}
        created = updated = failed = skipped = api_calls = 0
        errors: list[dict[str, str]] = []
        property_results: list[dict[str, Any]] = []
        experiment_websites = self._dimension_experiment_websites()
        specs = (
            ("page", ["page"], 1000),
            ("query", ["query"], 2000),
            ("page_query", ["page", "query"], 5000),
        )
        for prop in properties:
            state = self.database.get_search_console_dimension_state(
                prop["site_url"]
            )
            last_success = state.get("last_success")
            reason = self._dimension_run_reason(
                force=force_dimensions_refresh,
                website_id=prop["website_id"],
                last_success=last_success,
                now=now,
                new_daily=new_daily,
                experiment_websites=experiment_websites,
            )
            if reason is None:
                skipped += 1
                property_results.append({
                    "site_url": prop["site_url"],
                    "website_id": prop["website_id"],
                    "status": "skipped",
                    "reason": (
                        "Search Console-dimensioner er allerede opdateret "
                        "inden for de seneste 24 timer"
                    ),
                    "last_success_before": last_success,
                    "last_success_after": last_success,
                    "api_calls_executed": 0,
                    "api_calls_avoided": 6,
                })
                continue
            property_failed = False
            property_calls = 0
            property_created = 0
            property_updated = 0
            property_changed = 0
            attempted_at = now.isoformat(timespec="seconds")
            for period_start, period_end in periods:
                for dimension_type, dimensions, limit in specs:
                    try:
                        property_calls += 1
                        api_calls += 1
                        rows = self.connector.get_search_analytics_dimensions(
                            prop["site_url"], period_start.isoformat(),
                            period_end.isoformat(), dimensions, limit,
                        )
                        actions = (
                            self.database.upsert_search_console_dimensions(
                                dimension_type=dimension_type,
                                website_id=prop["website_id"],
                                site_url=prop["site_url"],
                                period_start=period_start.isoformat(),
                                period_end=period_end.isoformat(),
                                rows=rows,
                            )
                        )
                        created += actions["rows_created"]
                        updated += actions["rows_updated"]
                        property_created += actions["rows_created"]
                        property_updated += actions["rows_updated"]
                        property_changed += actions.get(
                            "rows_changed",
                            actions["rows_created"] + actions["rows_updated"],
                        )
                        totals[dimension_type] += len(rows)
                    except Exception as error:
                        property_failed = True
                        errors.append({
                            "site_url": prop["site_url"],
                            "dimension_type": dimension_type,
                            "error_type": type(error).__name__,
                        })
                        self.logger.error(
                            "Search Console-dimension fejlede: %s %s (%s)",
                            prop["site_url"], dimension_type,
                            type(error).__name__,
                        )
            failed += property_failed
            new_state = dict(state)
            new_state["last_attempt"] = attempted_at
            if property_failed:
                new_state["last_error"] = attempted_at
                status = "error"
                success_after = last_success
            else:
                new_state["last_success"] = attempted_at
                status = "completed"
                success_after = attempted_at
            self.database.set_search_console_dimension_state(
                prop["site_url"], new_state
            )
            property_results.append({
                "site_url": prop["site_url"],
                "website_id": prop["website_id"],
                "status": status,
                "reason": reason,
                "last_success_before": last_success,
                "last_success_after": success_after,
                "api_calls_executed": property_calls,
                "api_calls_avoided": 6 - property_calls,
                "rows_created": property_created,
                "rows_updated": property_updated,
                "rows_changed": property_changed,
            })
        processed = len(properties) - skipped
        if not properties or skipped == len(properties):
            overall_status = "skipped"
        elif failed == processed and processed:
            overall_status = "failed"
        elif failed:
            overall_status = "completed_with_warnings"
        else:
            overall_status = "completed"
        return SearchConsoleDimensionSyncResult(
            properties_processed=processed,
            properties_failed=failed,
            page_rows=totals["page"], query_rows=totals["query"],
            page_query_rows=totals["page_query"],
            rows_created=created, rows_updated=updated, errors=errors,
            properties_evaluated=len(properties),
            properties_skipped=skipped,
            api_calls_executed=api_calls,
            api_calls_avoided=(len(properties) * 6) - api_calls,
            property_results=property_results,
            refresh_mode=(
                "forced" if force_dimensions_refresh else "normal"
            ),
            overall_status=overall_status,
        )

    def _dimension_experiment_websites(self) -> set[str]:
        """Return websites whose active SEO experiment needs fresh dimensions."""
        try:
            experiments = self.database.get_seo_experiments(
                statuses=("waiting_for_data", "ready_for_evaluation")
            )
        except (AttributeError, TypeError):
            return set()
        if not isinstance(experiments, list):
            return set()
        return {
            str(item["website_id"])
            for item in experiments
            if item.get("website_id")
        }

    @staticmethod
    def _dimension_run_reason(
        *, force: bool, website_id: str, last_success: str | None,
        now: datetime, new_daily: set[str], experiment_websites: set[str],
    ) -> str | None:
        if force:
            return "tvungen opdatering"
        if website_id in new_daily:
            return "nye Search Console-dagstal"
        if website_id in experiment_websites:
            return "aktivt SEO-eksperiment"
        if not last_success:
            return "ingen tidligere dimensionsimport"
        try:
            previous = datetime.fromisoformat(last_success)
            if previous.tzinfo is None:
                previous = previous.astimezone()
        except (TypeError, ValueError):
            return "ingen tidligere dimensionsimport"
        if now - previous >= timedelta(hours=24):
            return "mere end 24 timer siden seneste succes"
        return None

    def get_dimension_comparisons(
        self, website_id: str, dimension_type: str,
    ) -> list[dict[str, Any]]:
        """Compare the latest stored period with its immediate predecessor."""
        rows = self.database.get_search_console_dimensions(
            dimension_type, website_id=website_id
        )
        periods = sorted(
            {(row["period_start"], row["period_end"]) for row in rows},
            reverse=True,
        )
        if len(periods) < 2:
            return []
        current_period, previous_period = periods[:2]
        key_fields = {
            "page": ("page_url",), "query": ("query",),
            "page_query": ("page_url", "query"),
        }[dimension_type]
        def key(row: dict[str, Any]) -> tuple[Any, ...]:
            return tuple(row.get(field) for field in key_fields)
        current = {
            key(row): row for row in rows
            if (row["period_start"], row["period_end"]) == current_period
        }
        previous = {
            key(row): row for row in rows
            if (row["period_start"], row["period_end"]) == previous_period
        }
        comparisons = []
        for row_key in current.keys() | previous.keys():
            now = current.get(row_key, {})
            before = previous.get(row_key, {})
            current_clicks = int(now.get("clicks", 0))
            previous_clicks = int(before.get("clicks", 0))
            current_ctr = float(now.get("ctr", 0))
            previous_ctr = float(before.get("ctr", 0))
            item = {
                **dict(zip(key_fields, row_key)),
                "current_clicks": current_clicks,
                "previous_clicks": previous_clicks,
                "click_change": current_clicks - previous_clicks,
                "current_impressions": int(now.get("impressions", 0)),
                "previous_impressions": int(before.get("impressions", 0)),
                "current_ctr": current_ctr,
                "previous_ctr": previous_ctr,
                "ctr_change": current_ctr - previous_ctr,
                "current_position": float(now.get("average_position", 0)),
                "previous_position": float(before.get("average_position", 0)),
                "trend": (
                    "Vækst" if current_clicks > previous_clicks else
                    "Fald" if current_clicks < previous_clicks else "Stabil"
                ),
                "period_start": current_period[0],
                "period_end": current_period[1],
            }
            comparisons.append(item)
        return sorted(
            comparisons,
            key=lambda item: (
                item["current_clicks"], item["current_impressions"]
            ),
            reverse=True,
        )

    def sync_property(
        self,
        site_url: str,
        website_id: str,
        days: int = DEFAULT_DAILY_IMPORT_DAYS,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]:
        """Fetch and persist the latest daily metrics for one property."""
        if days < 1:
            raise ValueError("days skal være mindst 1.")
        resolved_end_date = end_date or date.today()
        resolved_start_date = (
            start_date
            or resolved_end_date - timedelta(days=days - 1)
        )
        metrics = self.get_property_metrics(
            site_url,
            resolved_start_date.isoformat(),
            resolved_end_date.isoformat(),
        )
        created = 0
        updated = 0
        changed = 0
        for metric in metrics:
            action = self.database.upsert_search_console_daily_metric(
                website_id=website_id,
                site_url=site_url,
                metric_date=metric["date"],
                clicks=metric["clicks"],
                impressions=metric["impressions"],
                ctr=metric["ctr"],
                average_position=metric["position"],
            )
            if action == "created":
                created += 1
            else:
                updated += 1
            if action in {"created", "updated"}:
                changed += 1
        return {
            "rows_created": created,
            "rows_updated": updated,
            "rows_changed": changed,
        }

    def get_property_metrics(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Fetch aggregate daily Search Analytics data for one property."""
        return self.connector.get_search_analytics(
            site_url,
            start_date,
            end_date,
        )

    def get_comparisons(
        self,
        reference_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Return latest-seven versus previous-seven website comparisons."""
        return self.database.get_search_console_comparisons(reference_date)

    def _match_website(self, site_url: str) -> dict[str, Any] | None:
        domain = site_url
        if domain.lower().startswith("sc-domain:"):
            domain = domain.split(":", 1)[1]
        return self.website_registry.get(domain)

    @staticmethod
    def format_property_table(properties: list[dict[str, Any]]) -> str:
        """Return a readable property URL and permission table."""
        headers = ("property URL", "permission level")
        rows = [
            (item["site_url"], item["permission_level"])
            for item in properties
        ]
        widths = [
            max(
                len(headers[index]),
                *(len(str(row[index])) for row in rows),
            )
            if rows
            else len(headers[index])
            for index in range(2)
        ]
        lines = [
            " | ".join(
                headers[index].ljust(widths[index]) for index in range(2)
            ),
            "-+-".join("-" * width for width in widths),
        ]
        lines.extend(
            " | ".join(
                str(row[index]).ljust(widths[index]) for index in range(2)
            )
            for row in rows
        )
        return "\n".join(lines)
