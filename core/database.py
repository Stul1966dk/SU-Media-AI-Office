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
        self._create_or_migrate_websites_table()
        self._create_work_tables()
        self._create_orchestrator_tables()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def _create_orchestrator_tables(self) -> None:
        """Create persistent event and action queues."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                website TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                priority INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                processed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                assigned_agent TEXT NOT NULL,
                website TEXT NOT NULL,
                project_id INTEGER,
                task_id INTEGER,
                reason TEXT NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                depends_on_action_id INTEGER,
                result_json TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (event_id) REFERENCES events(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (depends_on_action_id) REFERENCES actions(id)
            );
            """
        )

    def create_event_record(self, values: dict[str, Any]) -> int:
        """Persist one orchestrator event."""
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO events (
                    event_type, source, website, title, description,
                    priority, data_json, status, created_at, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["event_type"],
                    values["source"],
                    values["website"],
                    values["title"],
                    values["description"],
                    values["priority"],
                    values["data_json"],
                    values["status"],
                    values["created_at"],
                    values.get("processed_at"),
                ),
            )
        return int(cursor.lastrowid)

    def get_event_record(self, event_id: int) -> dict[str, Any] | None:
        """Return one persisted event."""
        row = self._connection.execute(
            "SELECT * FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_event_records(self, status: str | None = None) -> list[dict[str, Any]]:
        """Return events, optionally filtered by status."""
        if status is None:
            rows = self._connection.execute(
                "SELECT * FROM events ORDER BY id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM events WHERE status = ? ORDER BY id",
                (status,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_event_status(
        self,
        event_id: int,
        status: str,
        processed_at: str | None = None,
    ) -> None:
        """Update an event lifecycle state."""
        with self._connection:
            self._connection.execute(
                """
                UPDATE events
                SET status = ?, processed_at = COALESCE(?, processed_at)
                WHERE id = ?
                """,
                (status, processed_at, event_id),
            )

    def create_action_record(self, values: dict[str, Any]) -> int:
        """Persist one routed action."""
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO actions (
                    event_id, action_type, assigned_agent, website,
                    project_id, task_id, reason, priority, status,
                    depends_on_action_id, result_json, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["event_id"],
                    values["action_type"],
                    values["assigned_agent"],
                    values["website"],
                    values.get("project_id"),
                    values.get("task_id"),
                    values["reason"],
                    values["priority"],
                    values["status"],
                    values.get("depends_on_action_id"),
                    values.get("result_json"),
                    values["created_at"],
                    values.get("completed_at"),
                ),
            )
        return int(cursor.lastrowid)

    def get_action_record(self, action_id: int) -> dict[str, Any] | None:
        """Return one persisted action."""
        row = self._connection.execute(
            "SELECT * FROM actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_action_records(
        self,
        *,
        event_id: int | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Return actions filtered by event and/or lifecycle states."""
        clauses: list[str] = []
        parameters: list[Any] = []
        if event_id is not None:
            clauses.append("event_id = ?")
            parameters.append(event_id)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(statuses)
        query = "SELECT * FROM actions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id"
        rows = self._connection.execute(query, tuple(parameters)).fetchall()
        return [dict(row) for row in rows]

    def complete_action_record(
        self,
        action_id: int,
        result_json: str,
        completed_at: str,
    ) -> None:
        """Complete an action and release its direct dependants."""
        with self._connection:
            self._connection.execute(
                """
                UPDATE actions
                SET status = 'completed', result_json = ?, completed_at = ?
                WHERE id = ?
                """,
                (result_json, completed_at, action_id),
            )
            self._connection.execute(
                """
                UPDATE actions
                SET status = 'pending'
                WHERE depends_on_action_id = ? AND status = 'blocked'
                """,
                (action_id,),
            )

    def get_orchestrator_counts(self) -> dict[str, int]:
        """Return pending event and action queue sizes."""
        events = self._connection.execute(
            "SELECT COUNT(*) AS total FROM events WHERE status = 'pending'"
        ).fetchone()
        actions = self._connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM actions
            WHERE status IN ('pending', 'blocked')
            """
        ).fetchone()
        return {
            "pending_events": int(events["total"]),
            "pending_actions": int(actions["total"]),
        }

    def _create_work_tables(self) -> None:
        """Create project, subproject, and task tables."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                expected_effect TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE (website_id, title),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );

            CREATE TABLE IF NOT EXISTS subprojects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE (project_id, title),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subproject_id INTEGER NOT NULL,
                website_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reason TEXT NOT NULL,
                assigned_agent TEXT NOT NULL,
                estimated_minutes INTEGER NOT NULL,
                expected_effect TEXT NOT NULL,
                priority_score INTEGER NOT NULL,
                status TEXT NOT NULL,
                depends_on_task_id INTEGER,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (subproject_id) REFERENCES subprojects(id),
                FOREIGN KEY (website_id) REFERENCES websites(website),
                FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id)
            );
            """
        )

    def create_project_record(self, values: dict[str, Any]) -> int:
        """Insert a project or return the matching existing project ID."""
        existing = self._connection.execute(
            """
            SELECT id FROM projects
            WHERE website_id = ? AND title = ?
            """,
            (values["website_id"], values["title"]),
        ).fetchone()
        if existing:
            return int(existing["id"])

        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO projects (
                    website_id, title, description, status, priority,
                    expected_effect, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["website_id"],
                    values["title"],
                    values["description"],
                    values["status"],
                    values["priority"],
                    values["expected_effect"],
                    values["created_at"],
                    values.get("completed_at"),
                ),
            )
        return int(cursor.lastrowid)

    def create_subproject_record(self, values: dict[str, Any]) -> int:
        """Insert a subproject or return the matching existing ID."""
        existing = self._connection.execute(
            """
            SELECT id FROM subprojects
            WHERE project_id = ? AND title = ?
            """,
            (values["project_id"], values["title"]),
        ).fetchone()
        if existing:
            return int(existing["id"])

        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO subprojects (
                    project_id, title, description, status, sequence,
                    created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["project_id"],
                    values["title"],
                    values["description"],
                    values["status"],
                    values["sequence"],
                    values["created_at"],
                    values.get("completed_at"),
                ),
            )
        return int(cursor.lastrowid)

    def create_task_record(self, values: dict[str, Any]) -> int:
        """Insert one concrete task and return its ID."""
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO tasks (
                    subproject_id, website_id, title, description, reason,
                    assigned_agent, estimated_minutes, expected_effect,
                    priority_score, status, depends_on_task_id, created_at,
                    started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["subproject_id"],
                    values["website_id"],
                    values["title"],
                    values["description"],
                    values["reason"],
                    values["assigned_agent"],
                    values["estimated_minutes"],
                    values["expected_effect"],
                    values["priority_score"],
                    values["status"],
                    values.get("depends_on_task_id"),
                    values["created_at"],
                    values.get("started_at"),
                    values.get("completed_at"),
                ),
            )
        return int(cursor.lastrowid)

    def get_project_record(self, project_id: int) -> dict[str, Any] | None:
        """Return one project."""
        row = self._connection.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_subprojects_for_project(
        self, project_id: int
    ) -> list[dict[str, Any]]:
        """Return a project's subprojects in execution order."""
        rows = self._connection.execute(
            """
            SELECT * FROM subprojects
            WHERE project_id = ?
            ORDER BY sequence, id
            """,
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_task_record(self, task_id: int) -> dict[str, Any] | None:
        """Return one task with project and subproject context."""
        row = self._connection.execute(
            """
            SELECT
                t.*, sp.project_id, sp.title AS subproject_title,
                p.title AS project_title
            FROM tasks t
            JOIN subprojects sp ON sp.id = t.subproject_id
            JOIN projects p ON p.id = sp.project_id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_task_records_for_project(
        self, project_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Return tasks with their project and subproject context."""
        query = """
            SELECT
                t.*, sp.project_id, sp.title AS subproject_title,
                sp.sequence AS subproject_sequence,
                p.title AS project_title
            FROM tasks t
            JOIN subprojects sp ON sp.id = t.subproject_id
            JOIN projects p ON p.id = sp.project_id
        """
        parameters: tuple[Any, ...] = ()
        if project_id is not None:
            query += " WHERE p.id = ?"
            parameters = (project_id,)
        query += " ORDER BY sp.sequence, t.priority_score DESC, t.id"
        rows = self._connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def update_task_status(
        self,
        task_id: int,
        status: str,
        *,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        """Update a task's lifecycle status and timestamps."""
        with self._connection:
            self._connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (status, started_at, completed_at, task_id),
            )

    def _create_websites_table(self) -> None:
        """Create the shared website registry table."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS websites (
                website TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                active INTEGER NOT NULL,
                monetized INTEGER NOT NULL,
                priority TEXT NOT NULL,
                primary_income_source TEXT NOT NULL,
                niche TEXT NOT NULL,
                domain_age TEXT NOT NULL,
                notes TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )

    def _create_or_migrate_websites_table(self) -> None:
        """Create the website table or add fields introduced later."""
        exists = self._connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'websites'
            """
        ).fetchone()
        if not exists:
            self._create_websites_table()
            return

        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(websites)")
        }
        if "status" not in columns:
            with self._connection:
                self._connection.execute(
                    """
                    ALTER TABLE websites
                    ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
                    """
                )
                self._connection.execute(
                    """
                    UPDATE websites
                    SET status = 'phasing_out'
                    WHERE LOWER(notes) LIKE '%will be terminated%'
                    """
                )

    def upsert_website(self, website: dict[str, Any]) -> None:
        """Insert a website or update all fields for an existing domain."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO websites (
                    website, display_name, active, monetized, priority,
                    primary_income_source, niche, domain_age, notes
                    , status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website) DO UPDATE SET
                    display_name = excluded.display_name,
                    active = excluded.active,
                    monetized = excluded.monetized,
                    priority = excluded.priority,
                    primary_income_source = excluded.primary_income_source,
                    niche = excluded.niche,
                    domain_age = excluded.domain_age,
                    notes = excluded.notes,
                    status = excluded.status
                """,
                (
                    website["website"],
                    website["display_name"],
                    int(website["active"]),
                    int(website["monetized"]),
                    website["priority"],
                    website["primary_income_source"],
                    website["niche"],
                    website["domain_age"],
                    website["notes"],
                    website["status"],
                ),
            )

    def get_all_websites(self) -> list[dict[str, Any]]:
        """Return every website ordered by its unique domain."""
        rows = self._connection.execute(
            """
            SELECT
                website, display_name, active, monetized, priority,
                primary_income_source, niche, domain_age, notes
                , status
            FROM websites
            ORDER BY website
            """
        ).fetchall()
        return [self._website_row(row) for row in rows]

    def get_website(self, website: str) -> dict[str, Any] | None:
        """Return one website by its normalized unique domain."""
        row = self._connection.execute(
            """
            SELECT
                website, display_name, active, monetized, priority,
                primary_income_source, niche, domain_age, notes
                , status
            FROM websites
            WHERE website = ?
            """,
            (website,),
        ).fetchone()
        return self._website_row(row) if row is not None else None

    @staticmethod
    def _website_row(row: sqlite3.Row) -> dict[str, Any]:
        website = dict(row)
        website["active"] = bool(website["active"])
        website["monetized"] = bool(website["monetized"])
        return website

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

    def get_month_commission(self, year: int, month: int) -> Decimal:
        """Return total commission for a calendar month."""
        rows = self._connection.execute(
            "SELECT dato, provision FROM registered_sales"
        ).fetchall()
        total = Decimal("0")
        for row in rows:
            try:
                _, sale_month, sale_year = (
                    int(part) for part in row["dato"].split("-")
                )
            except (AttributeError, TypeError, ValueError):
                continue
            if sale_year == year and sale_month == month:
                total += Decimal(str(row["provision"]))
        return total

    def get_website_counts(self) -> dict[str, int]:
        """Return total, monetized, and phasing-out website counts."""
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN monetized = 1 THEN 1 ELSE 0 END), 0)
                    AS monetized,
                COALESCE(
                    SUM(CASE WHEN status = 'phasing_out' THEN 1 ELSE 0 END),
                    0
                ) AS phasing_out
            FROM websites
            """
        ).fetchone()
        return {
            "total": int(row["total"]),
            "monetized": int(row["monetized"]),
            "phasing_out": int(row["phasing_out"]),
        }

    def get_active_project_count(self) -> int:
        """Return projects that are neither completed nor cancelled."""
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM projects
            WHERE status NOT IN ('completed', 'cancelled')
            """
        ).fetchone()
        return int(row["total"])

    def get_open_task_count(self) -> int:
        """Return tasks that are neither completed nor cancelled."""
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM tasks
            WHERE status NOT IN ('completed', 'cancelled')
            """
        ).fetchone()
        return int(row["total"])

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
