"""Central SQLite database access for SU Media AI Office.

All SQL and SQLite-specific behavior lives in this module. Application
components use :class:`Database` methods and therefore do not depend on the
underlying database engine. This boundary also prepares the project for a
later migration to Supabase PostgreSQL.
"""

import json
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SALE_COLUMNS = (
    "kombiid",
    "programid",
    "program",
    "dato",
    "tidspunkt",
    "ordrenr",
    "omsaetning",
    "provision",
    "url",
    "valuta",
    "created_at",
)


class Database:
    """Provide the central persistence API for SU Media AI Office.

    The class owns the SQLite connection, schema initialization, automatic
    migration of the legacy sales table, duplicate checks, sale persistence,
    and sales queries. Call :meth:`initialize` before using other methods and
    :meth:`close` when the application stops.
    """

    def __init__(self, path: Path) -> None:
        """Configure a database located at ``path`` without opening it."""
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Open the database and create or migrate its schema."""
        if self.connection is not None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_or_migrate_sales_table()
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
        """Close the active database connection."""
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def sale_exists(self, kombiid: str) -> bool:
        """Return whether a Partner-ads sale is already registered."""
        row = self._connection.execute(
            "SELECT 1 FROM registered_sales WHERE kombiid = ?",
            (kombiid,),
        ).fetchone()
        return row is not None

    def save_sale(
        self,
        sale: dict[str, str],
        created_at: str | None = None,
    ) -> None:
        """Persist every supported field from a Partner-ads sale."""
        timestamp = created_at or datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        with self._connection:
            self._insert_sale(sale, timestamp)

    def get_today_commission(self, date: str) -> Decimal:
        """Return total registered commission for the supplied sale date."""
        row = self._connection.execute(
            """
            SELECT COALESCE(SUM(provision), 0) AS total
            FROM registered_sales
            WHERE dato = ?
            """,
            (date,),
        ).fetchone()
        return Decimal(str(row["total"]))

    def get_sales(self, date: str) -> list[dict[str, Any]]:
        """Return all registered sales for the supplied sale date."""
        rows = self._connection.execute(
            """
            SELECT
                kombiid, programid, program, dato, tidspunkt, ordrenr,
                omsaetning, provision, url, valuta, created_at
            FROM registered_sales
            WHERE dato = ?
            ORDER BY tidspunkt, created_at
            """,
            (date,),
        ).fetchall()
        return [dict(row) for row in rows]

    def is_baseline_initialized(self) -> bool:
        """Return whether existing sales have been registered as a baseline."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = 'baseline_initialized'"
        ).fetchone()
        return row is not None and row["value"] == "1"

    def initialize_sales_baseline(self, sales: list[dict[str, str]]) -> None:
        """Persist existing sales and mark the no-notification baseline."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            for sale in sales:
                self._insert_sale(sale, timestamp)
            self._connection.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES ('baseline_initialized', '1')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )

    @property
    def _connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("Databasen skal initialiseres før brug.")
        return self.connection

    def _create_sales_table(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE registered_sales (
                kombiid TEXT PRIMARY KEY,
                programid TEXT NOT NULL,
                program TEXT NOT NULL,
                dato TEXT NOT NULL,
                tidspunkt TEXT NOT NULL,
                ordrenr TEXT NOT NULL,
                omsaetning NUMERIC NOT NULL,
                provision NUMERIC NOT NULL,
                url TEXT NOT NULL,
                valuta TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    def _create_or_migrate_sales_table(self) -> None:
        exists = self._connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'registered_sales'
            """
        ).fetchone()
        if not exists:
            self._create_sales_table()
            return

        current_columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(registered_sales)"
            )
        }
        if set(SALE_COLUMNS).issubset(current_columns):
            return

        legacy_rows = list(
            self._connection.execute("SELECT * FROM registered_sales")
        )
        with self._connection:
            self._connection.execute(
                "ALTER TABLE registered_sales RENAME TO registered_sales_legacy"
            )
            self._create_sales_table()
            for row in legacy_rows:
                sale = self._sale_from_legacy_row(row)
                self._insert_sale(sale, sale["created_at"])
            self._connection.execute("DROP TABLE registered_sales_legacy")

    @staticmethod
    def _sale_from_legacy_row(row: sqlite3.Row) -> dict[str, str]:
        available = set(row.keys())
        sale: dict[str, str] = {}
        if "sale_json" in available and row["sale_json"]:
            try:
                sale.update(json.loads(row["sale_json"]))
            except (TypeError, json.JSONDecodeError):
                pass

        for field in SALE_COLUMNS:
            if field in available and row[field] is not None:
                sale[field] = str(row[field])

        sale["kombiid"] = sale.get("kombiid", "")
        sale["created_at"] = sale.get(
            "created_at",
            str(row["registered_at"])
            if "registered_at" in available
            else datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        return sale

    def _insert_sale(self, sale: dict[str, str], created_at: str) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO registered_sales (
                kombiid, programid, program, dato, tidspunkt, ordrenr,
                omsaetning, provision, url, valuta, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._get_kombiid(sale),
                sale.get("programid", ""),
                sale.get("program", ""),
                sale.get("dato", ""),
                sale.get("tidspunkt", ""),
                sale.get("ordrenr", ""),
                self._as_number(sale.get("omsaetning", "0")),
                self._as_number(sale.get("provision", "0")),
                sale.get("url", ""),
                sale.get("valuta", ""),
                created_at,
            ),
        )

    @staticmethod
    def _as_number(value: str | int | float | Decimal) -> float:
        normalized = str(value).strip().replace(" ", "")
        if "," in normalized and "." in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", ".")
        try:
            return float(Decimal(normalized))
        except InvalidOperation:
            raise ValueError(f"Ugyldigt beløb fra Partner-ads: {value}") from None

    @staticmethod
    def _get_kombiid(sale: dict[str, str]) -> str:
        kombiid = sale.get("kombiid")
        if not kombiid:
            raise ValueError("Et Partner-ads-salg mangler feltet kombiid.")
        return kombiid
