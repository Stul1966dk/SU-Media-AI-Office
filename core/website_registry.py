"""Central registry for websites managed by SU Media AI Office."""

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .database import Database


REQUIRED_COLUMNS = {
    "website",
    "display_name",
    "active",
    "monetized",
    "priority",
    "primary_income_source",
    "niche",
    "domain_age",
    "notes",
}


@dataclass(frozen=True)
class ImportResult:
    """Structured result from one Website Registry synchronization."""

    total: int
    created: int
    updated: int
    phased_out: int


class WebsiteRegistry:
    """Import, normalize, and retrieve the shared website catalogue.

    The registry owns CSV interpretation and domain normalization. SQLite
    access remains encapsulated by :class:`core.database.Database`.
    """

    def __init__(self, database: Database) -> None:
        """Create a registry backed by the central database."""
        self.database = database

    def initialize(self) -> None:
        """Initialize the database and website table."""
        self.database.initialize()

    def import_csv(self, path: Path) -> ImportResult:
        """Synchronize the registry with a semicolon-separated CSV file."""
        records = self._read_csv(path)
        created = 0
        updated = 0
        phased_out = 0

        for website in records.values():
            existing = self.database.get_website(website["website"])
            if existing is None:
                self.database.upsert_website(website)
                created += 1
                continue

            if existing != website:
                if (
                    existing["status"] != "phasing_out"
                    and website["status"] == "phasing_out"
                ):
                    phased_out += 1
                self.database.upsert_website(website)
                updated += 1

        return ImportResult(
            total=len(records),
            created=created,
            updated=updated,
            phased_out=phased_out,
        )

    def sync(self) -> ImportResult:
        """Synchronize from ``websites.csv`` beside the database file."""
        return self.import_csv(self.database.path.parent / "websites.csv")

    def _read_csv(self, path: Path) -> dict[str, dict[str, Any]]:
        """Read and validate every CSV row before changing the database."""
        raw_data = path.read_bytes()
        try:
            content = raw_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw_data.decode("cp1252")

        reader = csv.DictReader(io.StringIO(content, newline=""), delimiter=";")
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(
                f"Website-CSV mangler kolonner: {', '.join(sorted(missing))}."
            )

        records: dict[str, dict[str, Any]] = {}
        for row in reader:
            domain = self._normalize_domain(row.get("website", ""))
            if not domain:
                continue

            notes = row.get("notes", "").strip()
            records[domain] = {
                "website": domain,
                "display_name": row.get("display_name", "").strip(),
                "active": self._parse_boolean(row.get("active", "")),
                "monetized": self._parse_boolean(row.get("monetized", "")),
                "priority": row.get("priority", "").strip().lower(),
                "primary_income_source": row.get(
                    "primary_income_source", ""
                ).strip(),
                "niche": row.get("niche", "").strip(),
                "domain_age": row.get("domain_age", "").strip(),
                "notes": notes,
                "status": (
                    "phasing_out"
                    if "will be terminated" in notes.lower()
                    else "active"
                ),
            }
        return records

    def get_all(self) -> list[dict[str, Any]]:
        """Return every registered website."""
        return self.database.get_all_websites()

    def get(self, domain: str) -> dict[str, Any] | None:
        """Return one website using a domain or URL."""
        normalized = self._normalize_domain(domain)
        return self.database.get_website(normalized) if normalized else None

    @staticmethod
    def _normalize_domain(value: str) -> str:
        """Normalize a website or URL to a case-insensitive domain key."""
        candidate = value.strip().lower()
        if not candidate:
            return ""

        parsed = urlsplit(
            candidate if "://" in candidate else f"//{candidate}"
        )
        domain = parsed.hostname or parsed.path.split("/", 1)[0]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.rstrip(".")

    @staticmethod
    def _parse_boolean(value: str) -> bool:
        """Convert CSV boolean text to a Python boolean."""
        normalized = value.strip().lower()
        if normalized in {"yes", "ja", "true", "1", "tes"}:
            return True
        if normalized in {"", "no", "nej", "false", "0"}:
            return False
        raise ValueError(f"Ugyldig boolean-værdi i website-CSV: {value}")
