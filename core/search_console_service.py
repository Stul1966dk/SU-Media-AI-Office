"""Search Console property and daily metric synchronization service."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from integrations.search_console import SearchConsoleConnector

from .database import Database
from .website_registry import WebsiteRegistry


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
    errors: list[dict[str, str]]


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
        days: int = 35,
        website_ids: list[str] | None = None,
    ) -> SearchConsoleDataSyncResult:
        """Synchronize daily data for every active, matched property."""
        if days < 1:
            raise ValueError("days skal være mindst 1.")
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        properties = [
            item
            for item in self.database.get_search_console_properties()
            if item["active"] and item["website_id"]
            and (website_ids is None or item["website_id"] in website_ids)
        ]
        processed = 0
        failed = 0
        created = 0
        updated = 0
        errors: list[dict[str, str]] = []

        for item in properties:
            processed += 1
            try:
                result = self.sync_property(
                    site_url=item["site_url"],
                    website_id=item["website_id"],
                    days=days,
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

        return SearchConsoleDataSyncResult(
            properties_processed=processed,
            properties_failed=failed,
            rows_created=created,
            rows_updated=updated,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            errors=errors,
        )

    def sync_dimensions(
        self, website_ids: list[str] | None = None,
        reference_date: date | None = None,
    ) -> SearchConsoleDimensionSyncResult:
        """Import page, query, and page-query rows for two 28-day periods."""
        today = reference_date or date.today()
        current_end = today - timedelta(days=1)
        current_start = current_end - timedelta(days=27)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=27)
        periods = (
            (previous_start, previous_end), (current_start, current_end),
        )
        properties = [
            item for item in self.database.get_search_console_properties()
            if item["active"] and item["website_id"]
            and (website_ids is None or item["website_id"] in website_ids)
        ]
        totals = {"page": 0, "query": 0, "page_query": 0}
        created = updated = failed = 0
        errors: list[dict[str, str]] = []
        specs = (
            ("page", ["page"], 1000),
            ("query", ["query"], 2000),
            ("page_query", ["page", "query"], 5000),
        )
        for prop in properties:
            property_failed = False
            for period_start, period_end in periods:
                for dimension_type, dimensions, limit in specs:
                    try:
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
        return SearchConsoleDimensionSyncResult(
            properties_processed=len(properties),
            properties_failed=failed,
            page_rows=totals["page"], query_rows=totals["query"],
            page_query_rows=totals["page_query"],
            rows_created=created, rows_updated=updated, errors=errors,
        )

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
        days: int = 35,
    ) -> dict[str, int]:
        """Fetch and persist the latest daily metrics for one property."""
        if days < 1:
            raise ValueError("days skal være mindst 1.")
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        metrics = self.get_property_metrics(
            site_url,
            start_date.isoformat(),
            end_date.isoformat(),
        )
        created = 0
        updated = 0
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
        return {
            "rows_created": created,
            "rows_updated": updated,
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
