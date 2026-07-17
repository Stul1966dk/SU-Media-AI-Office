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
