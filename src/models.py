"""SQLite persistence for registered Partner-ads sales."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class SalesDatabase:
    """Track Partner-ads sales that have already been handled."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS registered_sales (
                kombiid TEXT PRIMARY KEY,
                sale_json TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        """Close the SQLite connection."""
        self.connection.close()

    def is_initialized(self) -> bool:
        """Return whether the initial no-notification baseline was recorded."""
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key = 'baseline_initialized'"
        ).fetchone()
        return row is not None and row[0] == "1"

    def contains(self, kombiid: str) -> bool:
        """Return whether a sale ID is already registered."""
        row = self.connection.execute(
            "SELECT 1 FROM registered_sales WHERE kombiid = ?",
            (kombiid,),
        ).fetchone()
        return row is not None

    def register(self, sale: dict[str, str]) -> None:
        """Register one sale after a successful notification."""
        kombiid = self._get_kombiid(sale)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO registered_sales
                (kombiid, sale_json, registered_at)
            VALUES (?, ?, ?)
            """,
            (
                kombiid,
                json.dumps(sale, ensure_ascii=False, sort_keys=True),
                datetime.now().astimezone().isoformat(timespec="seconds"),
            ),
        )
        self.connection.commit()

    def initialize_baseline(self, sales: list[dict[str, str]]) -> None:
        """Register existing sales without sending notifications."""
        registered_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.connection:
            for sale in sales:
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO registered_sales
                        (kombiid, sale_json, registered_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        self._get_kombiid(sale),
                        json.dumps(sale, ensure_ascii=False, sort_keys=True),
                        registered_at,
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES ('baseline_initialized', '1')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )

    def find_new(self, sales: list[dict[str, str]]) -> list[dict[str, str]]:
        """Return sales not yet present in the database."""
        new_sales: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for sale in sales:
            kombiid = self._get_kombiid(sale)
            if kombiid not in seen_ids and not self.contains(kombiid):
                new_sales.append(sale)
                seen_ids.add(kombiid)
        return new_sales

    @staticmethod
    def _get_kombiid(sale: dict[str, str]) -> str:
        """Read the sale's unique Partner-ads ID."""
        kombiid = sale.get("kombiid")
        if not kombiid:
            raise ValueError("Et Partner-ads-salg mangler feltet kombiid.")
        return kombiid
