"""Central SQLite database access for SU Media AI Office.

All SQL and SQLite-specific behavior lives in this module. Application
components use :class:`Database` methods and therefore do not depend on the
underlying database engine. This boundary also prepares the project for a
later migration to Supabase PostgreSQL.
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


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
        self._ensure_sales_sync_columns()
        self._create_or_migrate_websites_table()
        self._create_work_tables()
        self._create_orchestrator_tables()
        self._create_search_console_table()
        self._create_search_console_daily_metrics_table()
        self._create_search_console_dimension_tables()
        self._create_search_console_diagnoses_table()
        self._create_plausible_daily_metrics_table()
        self._create_plausible_diagnoses_table()
        self._create_seo_health_history_table()
        self._create_seo_recommendations_table()
        self._create_website_intelligence_tables()
        self._create_ai_analysis_table()
        self._create_executive_briefings_table()
        self._create_website_discovery_tables()
        self._create_website_content_table()
        self._create_feature_runs_table()
        self._create_decision_and_experiment_tables()
        self._create_title_optimization_tables()
        self._create_approved_changes_table()
        self._create_work_queue_tables()
        self._create_experiment_monitoring_tables()
        self._create_experiment_evaluations_table()
        self._create_priority_task_scores_table()
        self._create_traffic_recommendation_decisions_table()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def _create_priority_task_scores_table(self) -> None:
        """Create the refresh-time snapshot of dynamic task scores."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS priority_task_scores (
                task_key TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                website TEXT NOT NULL,
                priority TEXT NOT NULL,
                description TEXT NOT NULL,
                target TEXT NOT NULL,
                link_label TEXT NOT NULL,
                total_score REAL NOT NULL,
                plausible_score REAL NOT NULL,
                search_console_click_score REAL NOT NULL,
                ctr_score REAL NOT NULL,
                position_score REAL NOT NULL,
                seo_health_score REAL NOT NULL,
                experiment_score REAL NOT NULL,
                missing_data_score REAL NOT NULL,
                system_score REAL NOT NULL,
                existing_task_score REAL NOT NULL,
                payload_json TEXT NOT NULL,
                calculated_at TEXT NOT NULL
            )
            """
        )

    def _create_traffic_recommendation_decisions_table(self) -> None:
        """Create safe drafts and user decisions for traffic candidates."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS traffic_recommendation_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_key TEXT NOT NULL UNIQUE,
                website_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                target_url TEXT NOT NULL,
                measured_cause TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                snoozed_until TEXT,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def initialize_read_only(self) -> None:
        """Open an existing database without schema or data write access."""
        if self.connection is not None:
            return
        uri = "file:" + self.path.resolve().as_posix() + "?mode=ro"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.row_factory = sqlite3.Row

    def _create_experiment_evaluations_table(self) -> None:
        """Create the idempotent, structured SEO evaluation store."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiment_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                website_id TEXT NOT NULL,
                target_url TEXT NOT NULL,
                implemented_at TEXT NOT NULL,
                evaluation_due_at TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                baseline_start TEXT NOT NULL,
                baseline_end TEXT NOT NULL,
                comparison_start TEXT NOT NULL,
                comparison_end TEXT NOT NULL,
                clicks_before INTEGER NOT NULL,
                clicks_after INTEGER NOT NULL,
                clicks_absolute_change INTEGER NOT NULL,
                clicks_relative_change REAL,
                impressions_before INTEGER NOT NULL,
                impressions_after INTEGER NOT NULL,
                impressions_absolute_change INTEGER NOT NULL,
                impressions_relative_change REAL,
                ctr_before REAL NOT NULL,
                ctr_after REAL NOT NULL,
                ctr_percentage_point_change REAL NOT NULL,
                ctr_relative_change REAL,
                position_before REAL NOT NULL,
                position_after REAL NOT NULL,
                position_change REAL NOT NULL,
                sample_quality TEXT NOT NULL,
                result_status TEXT NOT NULL,
                ai_conclusion TEXT,
                post_analysis_json TEXT NOT NULL DEFAULT '{}',
                caveats_json TEXT NOT NULL DEFAULT '[]',
                evaluation_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (
                    experiment_id, evaluation_version,
                    baseline_start, baseline_end,
                    comparison_start, comparison_end
                ),
                FOREIGN KEY (experiment_id) REFERENCES seo_experiments(id),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );
            CREATE INDEX IF NOT EXISTS idx_experiment_evaluations_experiment
                ON experiment_evaluations (experiment_id, evaluated_at DESC);
            """
        )
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(experiment_evaluations)"
            )
        }
        if "post_analysis_json" not in columns:
            self._connection.execute(
                """ALTER TABLE experiment_evaluations
                   ADD COLUMN post_analysis_json TEXT NOT NULL DEFAULT '{}'"""
            )

    def save_experiment_evaluation(self, values: dict[str, Any]) -> int:
        """Upsert one evaluation version and measurement-period pair."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        fields = (
            "experiment_id", "website_id", "target_url", "implemented_at",
            "evaluation_due_at", "evaluated_at", "baseline_start",
            "baseline_end", "comparison_start", "comparison_end",
            "clicks_before", "clicks_after", "clicks_absolute_change",
            "clicks_relative_change", "impressions_before",
            "impressions_after", "impressions_absolute_change",
            "impressions_relative_change", "ctr_before", "ctr_after",
            "ctr_percentage_point_change", "ctr_relative_change",
            "position_before", "position_after", "position_change",
            "sample_quality", "result_status", "ai_conclusion",
            "post_analysis_json", "caveats_json", "evaluation_version",
            "created_at", "updated_at",
        )
        normalized = dict(values)
        normalized["post_analysis_json"] = json.dumps(
            values.get("post_analysis", {}), ensure_ascii=False
        )
        normalized["caveats_json"] = json.dumps(
            values.get("caveats", []), ensure_ascii=False
        )
        normalized["created_at"] = values.get("created_at") or timestamp
        normalized["updated_at"] = timestamp
        updates = [
            field for field in fields
            if field not in {
                "experiment_id", "evaluation_version", "baseline_start",
                "baseline_end", "comparison_start", "comparison_end",
                "created_at",
            }
        ]
        with self._connection:
            self._connection.execute(
                f"""INSERT INTO experiment_evaluations ({', '.join(fields)})
                    VALUES ({', '.join('?' for _ in fields)})
                    ON CONFLICT (
                        experiment_id, evaluation_version,
                        baseline_start, baseline_end,
                        comparison_start, comparison_end
                    ) DO UPDATE SET
                        {', '.join(f'{f} = excluded.{f}' for f in updates)}""",
                tuple(normalized.get(field) for field in fields),
            )
        row = self._connection.execute(
            """SELECT id FROM experiment_evaluations
               WHERE experiment_id = ? AND evaluation_version = ?
                 AND baseline_start = ? AND baseline_end = ?
                 AND comparison_start = ? AND comparison_end = ?""",
            tuple(normalized[field] for field in (
                "experiment_id", "evaluation_version", "baseline_start",
                "baseline_end", "comparison_start", "comparison_end",
            )),
        ).fetchone()
        return int(row["id"])

    def get_experiment_evaluations(
        self, experiment_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Return structured evaluations, newest first."""
        where, parameters = "", ()
        if experiment_id is not None:
            where, parameters = "WHERE experiment_id = ?", (experiment_id,)
        rows = self._connection.execute(
            f"""SELECT * FROM experiment_evaluations {where}
                ORDER BY evaluated_at DESC, id DESC""", parameters
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["caveats"] = json.loads(item.pop("caveats_json") or "[]")
            item["post_analysis"] = json.loads(
                item.pop("post_analysis_json") or "{}"
            )
            result.append(item)
        return result

    def _create_approved_changes_table(self) -> None:
        """Create the authoritative record of user-approved SEO changes."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS approved_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                target_url TEXT NOT NULL,
                target_query TEXT NOT NULL DEFAULT '',
                current_title TEXT NOT NULL DEFAULT '',
                approved_title TEXT NOT NULL DEFAULT '',
                current_meta TEXT NOT NULL DEFAULT '',
                approved_meta TEXT NOT NULL DEFAULT '',
                hypothesis TEXT NOT NULL,
                reason TEXT NOT NULL,
                expected_effect TEXT NOT NULL,
                project_id INTEGER,
                task_id INTEGER,
                experiment_id INTEGER,
                source_draft_id INTEGER,
                status TEXT NOT NULL,
                approved_at TEXT NOT NULL,
                implemented_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(experiment_id),
                UNIQUE(source_draft_id)
            )
            """
        )

    def save_approved_change(self, values: dict[str, Any]) -> int:
        """Persist one selected change; never model output that is not approved."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        approved_at = values.get("approved_at") or timestamp
        fields = (
            "website_id", "change_type", "target_url", "target_query",
            "current_title", "approved_title", "current_meta",
            "approved_meta", "hypothesis", "reason", "expected_effect",
            "project_id", "task_id", "experiment_id", "source_draft_id",
            "status", "approved_at", "implemented_at", "created_at",
            "updated_at",
        )
        normalized = {
            **values,
            "status": values.get("status", "awaiting_implementation"),
            "approved_at": approved_at,
            "implemented_at": values.get("implemented_at"),
            "created_at": timestamp, "updated_at": timestamp,
        }
        parameters = tuple(normalized.get(field) for field in fields)
        with self._connection:
            existing = None
            if values.get("experiment_id"):
                existing = self._connection.execute(
                    "SELECT id FROM approved_changes WHERE experiment_id = ?",
                    (values["experiment_id"],),
                ).fetchone()
            if not existing and values.get("source_draft_id"):
                existing = self._connection.execute(
                    "SELECT id FROM approved_changes WHERE source_draft_id = ?",
                    (values["source_draft_id"],),
                ).fetchone()
            if existing:
                assignments = ", ".join(
                    f"{field} = ?" for field in fields[:-2]
                )
                self._connection.execute(
                    f"""UPDATE approved_changes SET {assignments},
                        updated_at = ? WHERE id = ?""",
                    (*parameters[:-2], timestamp, existing["id"]),
                )
                return int(existing["id"])
            cursor = self._connection.execute(
                f"""INSERT INTO approved_changes ({", ".join(fields)})
                    VALUES ({", ".join("?" for _ in fields)})""",
                parameters,
            )
        return int(cursor.lastrowid)

    def get_approved_changes(
        self, *, status: str | None = None,
        experiment_id: int | None = None, source_draft_id: int | None = None,
        target_url: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        for field, value in (
            ("status", status), ("experiment_id", experiment_id),
            ("source_draft_id", source_draft_id), ("target_url", target_url),
        ):
            if value is not None:
                clauses.append(f"{field} = ?")
                parameters.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return [
            dict(row) for row in self._connection.execute(
                f"""SELECT * FROM approved_changes {where}
                    ORDER BY approved_at DESC, id DESC""",
                parameters,
            )
        ]

    def get_approved_change_for_work_item(
        self, item: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Resolve an approved change only through persisted foreign keys."""
        rows = []
        if item.get("experiment_id"):
            rows = self.get_approved_changes(
                experiment_id=item["experiment_id"]
            )
        if not rows and item.get("draft_id"):
            rows = self.get_approved_changes(
                source_draft_id=item["draft_id"]
            )
        return rows[0] if rows else None

    def update_approved_change_status(
        self, change_id: int, status: str,
        *, implemented_at: str | None = None,
    ) -> None:
        allowed = {
            "awaiting_implementation", "measurement_period",
            "ready_for_evaluation", "completed", "cancelled",
        }
        if status not in allowed:
            raise ValueError("Ugyldig status for godkendt ændring.")
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """UPDATE approved_changes
                   SET status = ?, implemented_at = COALESCE(?, implemented_at),
                       updated_at = ? WHERE id = ?""",
                (status, implemented_at, timestamp, change_id),
            )

    def _create_experiment_monitoring_tables(self) -> None:
        """Create idempotent live observations and measured SEO learning."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiment_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                observed_date TEXT NOT NULL,
                period_start TEXT,
                period_end TEXT,
                clicks INTEGER NOT NULL,
                impressions INTEGER NOT NULL,
                ctr REAL NOT NULL,
                average_position REAL NOT NULL,
                data_quality TEXT NOT NULL,
                pulse_status TEXT NOT NULL,
                observation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(experiment_id, observed_date, period_end)
            );

            CREATE TABLE IF NOT EXISTS experiment_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                observation_date TEXT NOT NULL,
                observation_type TEXT NOT NULL,
                event_key TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(experiment_id, event_key)
            );

            CREATE TABLE IF NOT EXISTS seo_learning_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL UNIQUE,
                website_id TEXT NOT NULL,
                target_url TEXT NOT NULL,
                page_type TEXT NOT NULL,
                change_type TEXT NOT NULL,
                target_query TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                original_change_json TEXT NOT NULL,
                implemented_change_json TEXT NOT NULL,
                baseline_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                effect_size REAL NOT NULL,
                data_quality TEXT NOT NULL,
                classification TEXT NOT NULL,
                conclusion TEXT NOT NULL,
                pattern_level TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS seo_url_status (
                target_url TEXT PRIMARY KEY,
                website_id TEXT NOT NULL,
                status TEXT NOT NULL,
                observation_until TEXT,
                failed_same_type_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )

    def save_experiment_snapshot(self, values: dict[str, Any]) -> bool:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            cursor = self._connection.execute(
                """INSERT OR IGNORE INTO experiment_snapshots (
                    experiment_id, observed_date, period_start, period_end,
                    clicks, impressions, ctr, average_position, data_quality,
                    pulse_status, observation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["experiment_id"], values["observed_date"],
                    values.get("period_start"), values.get("period_end"),
                    values["clicks"], values["impressions"], values["ctr"],
                    values["average_position"], values["data_quality"],
                    values["pulse_status"], values["observation"], timestamp,
                ),
            )
        return bool(cursor.rowcount)

    def get_experiment_snapshots(
        self, experiment_id: int
    ) -> list[dict[str, Any]]:
        return [
            dict(row) for row in self._connection.execute(
                """SELECT * FROM experiment_snapshots
                   WHERE experiment_id = ?
                   ORDER BY observed_date, id""",
                (experiment_id,),
            )
        ]

    def save_experiment_observation(
        self, *, experiment_id: int, observation_date: str,
        observation_type: str, event_key: str, description: str,
    ) -> bool:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            cursor = self._connection.execute(
                """INSERT OR IGNORE INTO experiment_observations (
                    experiment_id, observation_date, observation_type,
                    event_key, description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    experiment_id, observation_date, observation_type,
                    event_key, description, timestamp,
                ),
            )
        return bool(cursor.rowcount)

    def get_experiment_observations(
        self, experiment_id: int | None = None
    ) -> list[dict[str, Any]]:
        query, parameters = "SELECT * FROM experiment_observations", ()
        if experiment_id is not None:
            query += " WHERE experiment_id = ?"
            parameters = (experiment_id,)
        query += " ORDER BY observation_date DESC, id DESC"
        return [
            dict(row) for row in self._connection.execute(query, parameters)
        ]

    def save_seo_learning_entry(self, values: dict[str, Any]) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        json_fields = (
            "original_change", "implemented_change", "baseline", "result"
        )
        with self._connection:
            self._connection.execute(
                """INSERT INTO seo_learning_entries (
                    experiment_id, website_id, target_url, page_type,
                    change_type, target_query, hypothesis,
                    original_change_json, implemented_change_json,
                    baseline_json, result_json, effect_size, data_quality,
                    classification, conclusion, pattern_level, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    result_json = excluded.result_json,
                    effect_size = excluded.effect_size,
                    data_quality = excluded.data_quality,
                    classification = excluded.classification,
                    conclusion = excluded.conclusion,
                    pattern_level = excluded.pattern_level""",
                (
                    values["experiment_id"], values["website_id"],
                    values["target_url"], values.get("page_type", "ukendt"),
                    values["change_type"], values.get("target_query", ""),
                    values["hypothesis"],
                    *(json.dumps(values.get(field, {}), ensure_ascii=False)
                      for field in json_fields),
                    float(values.get("effect_size", 0)),
                    values["data_quality"], values["classification"],
                    values["conclusion"], values["pattern_level"], timestamp,
                ),
            )

    def get_seo_learning_entries(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM seo_learning_entries ORDER BY id DESC"
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for field in (
                "original_change_json", "implemented_change_json",
                "baseline_json", "result_json",
            ):
                item[field.removesuffix("_json")] = json.loads(item[field])
            result.append(item)
        return result

    def upsert_seo_url_status(
        self, *, target_url: str, website_id: str, status: str,
        observation_until: str | None = None,
        failed_same_type_count: int = 0,
    ) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """INSERT INTO seo_url_status (
                    target_url, website_id, status, observation_until,
                    failed_same_type_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_url) DO UPDATE SET
                    status = excluded.status,
                    observation_until = excluded.observation_until,
                    failed_same_type_count = excluded.failed_same_type_count,
                    updated_at = excluded.updated_at""",
                (
                    target_url, website_id, status, observation_until,
                    failed_same_type_count, timestamp,
                ),
            )

    def get_seo_url_status(
        self, target_url: str | None = None
    ) -> list[dict[str, Any]]:
        query, parameters = "SELECT * FROM seo_url_status", ()
        if target_url:
            query += " WHERE target_url = ?"
            parameters = (target_url,)
        return [
            dict(row) for row in self._connection.execute(query, parameters)
        ]

    def _create_work_queue_tables(self) -> None:
        """Create the persistent daily work queue and skip audit log."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS seo_work_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                target_url TEXT NOT NULL,
                target_query TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                candidate_json TEXT NOT NULL,
                implementation_json TEXT NOT NULL DEFAULT '{}',
                priority_score INTEGER NOT NULL,
                expected_impact TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                estimated_minutes INTEGER NOT NULL,
                queue_order INTEGER NOT NULL,
                status TEXT NOT NULL,
                draft_id INTEGER,
                decision_id INTEGER,
                project_id INTEGER,
                task_id INTEGER,
                experiment_id INTEGER,
                edited_title TEXT NOT NULL DEFAULT '',
                edited_meta TEXT NOT NULL DEFAULT '',
                implemented_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS seo_work_queue_skips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_item_id INTEGER NOT NULL,
                skipped_at TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (queue_item_id) REFERENCES seo_work_queue(id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_active_work_queue_url
            ON seo_work_queue(target_url)
            WHERE status IN ('queued', 'skipped', 'awaiting_implementation');
            """
        )
        columns = {
            row["name"] for row in
            self._connection.execute("PRAGMA table_info(seo_work_queue)")
        }
        if "implementation_json" not in columns:
            self._connection.execute(
                """ALTER TABLE seo_work_queue
                   ADD COLUMN implementation_json TEXT NOT NULL DEFAULT '{}'"""
            )

    def replace_queued_work(self, candidates: list[dict[str, Any]]) -> int:
        """Replace only untouched queue items with one newly ranked snapshot."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """DELETE FROM seo_work_queue
                   WHERE status IN ('queued', 'skipped')"""
            )
            for index, item in enumerate(candidates, start=1):
                self._connection.execute(
                    """INSERT INTO seo_work_queue (
                        website_id, target_url, target_query, action,
                        candidate_json, implementation_json, priority_score, expected_impact,
                        confidence, estimated_minutes, queue_order, status,
                        draft_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                    (
                        item["website"], item["target_url"],
                        item.get("target_query", ""), item["task_title"],
                        json.dumps(item, ensure_ascii=False),
                        json.dumps(
                            item.get("implementation_content", {}),
                            ensure_ascii=False,
                        ),
                        int(item["priority_score"]), item["expected_effect"],
                        int(item["confidence"]), int(item["estimated_minutes"]),
                        index, item.get("draft_id"), timestamp, timestamp,
                    ),
                )
        return len(candidates)

    def enqueue_work_candidate(self, item: dict[str, Any]) -> int:
        """Append one active queue row without touching historical records."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            existing = self._connection.execute(
                """SELECT id FROM seo_work_queue
                   WHERE target_url = ?
                     AND status IN ('queued', 'skipped', 'awaiting_implementation')
                   ORDER BY id DESC LIMIT 1""",
                (item["target_url"],),
            ).fetchone()
            if existing:
                return int(existing["id"])
            order = self._connection.execute(
                """SELECT COALESCE(MAX(queue_order), 0) AS value
                   FROM seo_work_queue"""
            ).fetchone()
            try:
                cursor = self._connection.execute(
                    """INSERT INTO seo_work_queue (
                        website_id, target_url, target_query, action,
                        candidate_json, implementation_json, priority_score,
                        expected_impact, confidence, estimated_minutes,
                        queue_order, status, draft_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                    (
                        item["website"], item["target_url"],
                        item.get("target_query", ""), item["task_title"],
                        json.dumps(item, ensure_ascii=False),
                        json.dumps(
                            item.get("implementation_content", {}),
                            ensure_ascii=False,
                        ),
                        int(item["priority_score"]), item["expected_effect"],
                        int(item["confidence"]), int(item["estimated_minutes"]),
                        int(order["value"]) + 1, item.get("draft_id"),
                        timestamp, timestamp,
                    ),
                )
                return int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                concurrent = self._connection.execute(
                    """SELECT id FROM seo_work_queue
                       WHERE target_url = ?
                         AND status IN (
                           'queued', 'skipped', 'awaiting_implementation'
                         ) ORDER BY id DESC LIMIT 1""",
                    (item["target_url"],),
                ).fetchone()
                if concurrent:
                    return int(concurrent["id"])
                raise

    def get_work_queue(
        self, statuses: tuple[str, ...] = ("queued", "skipped")
    ) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in statuses)
        rows = self._connection.execute(
            f"""SELECT * FROM seo_work_queue
                WHERE status IN ({placeholders})
                ORDER BY
                    CASE
                        WHEN status = 'awaiting_implementation' THEN 0
                        WHEN status = 'queued' THEN 1
                        WHEN status = 'skipped' THEN 2
                        ELSE 3
                    END,
                    priority_score DESC, queue_order, id""",
            statuses,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["candidate"] = json.loads(item["candidate_json"])
            item["implementation"] = json.loads(
                item.get("implementation_json") or "{}"
            )
            result.append(item)
        return result

    def get_work_queue_item(self, item_id: int) -> dict[str, Any] | None:
        return next((
            item for item in self.get_work_queue((
                "queued", "skipped", "awaiting_implementation", "implemented",
                "completed", "cancelled",
            )) if item["id"] == item_id
        ), None)

    def update_work_queue_item(
        self, item_id: int, values: dict[str, Any]
    ) -> None:
        allowed = {
            "status", "queue_order", "decision_id", "project_id", "task_id",
            "experiment_id", "edited_title", "edited_meta", "implemented_at",
            "implementation_json", "draft_id",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        with self._connection:
            self._connection.execute(
                "UPDATE seo_work_queue SET "
                + ", ".join(f"{key} = ?" for key in updates)
                + " WHERE id = ?",
                (*updates.values(), item_id),
            )

    def skip_work_queue_item(self, item_id: int, reason: str = "") -> None:
        """Move one item to the bottom without deleting it."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        row = self._connection.execute(
            "SELECT COALESCE(MAX(queue_order), 0) AS value FROM seo_work_queue"
        ).fetchone()
        with self._connection:
            self._connection.execute(
                """UPDATE seo_work_queue
                   SET status = 'skipped', queue_order = ?, updated_at = ?
                   WHERE id = ?""",
                (int(row["value"]) + 1, timestamp, item_id),
            )
            self._connection.execute(
                """INSERT INTO seo_work_queue_skips (
                    queue_item_id, skipped_at, reason
                ) VALUES (?, ?, ?)""",
                (item_id, timestamp, reason.strip()),
            )

    def get_work_queue_skips(
        self, item_id: int | None = None
    ) -> list[dict[str, Any]]:
        query, parameters = "SELECT * FROM seo_work_queue_skips", ()
        if item_id is not None:
            query += " WHERE queue_item_id = ?"
            parameters = (item_id,)
        query += " ORDER BY id DESC"
        return [
            dict(row) for row in self._connection.execute(query, parameters)
        ]

    def _create_feature_runs_table(self) -> None:
        """Create the shared operational run history."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                records_processed INTEGER NOT NULL DEFAULT 0,
                records_created INTEGER NOT NULL DEFAULT 0,
                records_updated INTEGER NOT NULL DEFAULT 0,
                error_type TEXT,
                error_message TEXT
            )
            """
        )

    def _create_decision_and_experiment_tables(self) -> None:
        """Create decision, experiment, and experiment-learning storage."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS decision_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                target_url TEXT NOT NULL,
                target_query TEXT NOT NULL DEFAULT '',
                task_title TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                priority_score INTEGER NOT NULL,
                confidence INTEGER NOT NULL,
                status TEXT NOT NULL,
                selected_at TEXT NOT NULL,
                approved_at TEXT,
                rejected_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );

            CREATE TABLE IF NOT EXISTS seo_experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                decision_id INTEGER,
                project_id INTEGER,
                task_id INTEGER,
                target_url TEXT NOT NULL,
                target_query TEXT NOT NULL DEFAULT '',
                experiment_type TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                change_description TEXT NOT NULL,
                goal_metric TEXT NOT NULL,
                goal_direction TEXT NOT NULL,
                target_change_pct REAL NOT NULL,
                baseline_start TEXT,
                baseline_end TEXT,
                baseline_clicks INTEGER,
                baseline_impressions INTEGER,
                baseline_ctr REAL,
                baseline_position REAL,
                baseline_commission REAL,
                started_at TEXT,
                minimum_evaluation_date TEXT,
                planned_evaluation_date TEXT,
                actual_evaluation_date TEXT,
                waiting_period_days INTEGER NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                result_summary TEXT,
                actual_click_change_pct REAL,
                actual_impression_change_pct REAL,
                actual_ctr_change REAL,
                actual_position_change REAL,
                actual_commission_change REAL,
                confidence INTEGER NOT NULL,
                extension_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (website_id) REFERENCES websites(website),
                FOREIGN KEY (decision_id) REFERENCES decision_history(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS experiment_learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL UNIQUE,
                website_id TEXT NOT NULL,
                target_url TEXT NOT NULL,
                experiment_type TEXT NOT NULL,
                outcome TEXT NOT NULL,
                learning TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES seo_experiments(id),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );
            """
        )

    def _create_title_optimization_tables(self) -> None:
        """Create approval drafts and their optional public SERP evidence."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS title_optimization_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                target_url TEXT NOT NULL,
                target_query TEXT NOT NULL,
                current_title TEXT NOT NULL,
                current_meta TEXT NOT NULL,
                page_analysis_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                title_proposals_json TEXT NOT NULL,
                meta_proposals_json TEXT NOT NULL,
                reviewer_json TEXT NOT NULL,
                recommended_title_index INTEGER NOT NULL,
                recommended_meta_index INTEGER NOT NULL,
                selected_title TEXT NOT NULL DEFAULT '',
                selected_meta TEXT NOT NULL DEFAULT '',
                confidence INTEGER NOT NULL,
                expected_effect TEXT NOT NULL,
                measurement_method TEXT NOT NULL,
                status TEXT NOT NULL,
                project_id INTEGER,
                task_id INTEGER,
                experiment_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_at TEXT,
                rejected_at TEXT,
                implemented_at TEXT,
                FOREIGN KEY (website_id) REFERENCES websites(website),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id),
                FOREIGN KEY (experiment_id) REFERENCES seo_experiments(id)
            );

            CREATE TABLE IF NOT EXISTS title_serp_competitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draft_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                domain TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                meta_description TEXT NOT NULL,
                h1 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (draft_id, position, url),
                FOREIGN KEY (draft_id) REFERENCES title_optimization_drafts(id)
            );
            """
        )

    def create_title_optimization_draft(
        self, values: dict[str, Any], competitors: list[dict[str, Any]]
    ) -> int:
        """Persist one immutable analysis with editable selected proposals."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            cursor = self._connection.execute(
                """INSERT INTO title_optimization_drafts (
                    website_id, target_url, target_query, current_title,
                    current_meta, page_analysis_json, analysis_json,
                    title_proposals_json, meta_proposals_json, reviewer_json,
                    recommended_title_index, recommended_meta_index,
                    selected_title, selected_meta, confidence, expected_effect,
                    measurement_method, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'awaiting_approval', ?, ?)""",
                (
                    values["website"], values["target_url"],
                    values["target_query"], values["current_title"],
                    values["current_meta"],
                    json.dumps(values.get("page_analysis", {}),
                               ensure_ascii=False),
                    json.dumps(values["analysis"], ensure_ascii=False),
                    json.dumps(values["title_proposals"], ensure_ascii=False),
                    json.dumps(values["meta_proposals"], ensure_ascii=False),
                    json.dumps(values["reviewer"], ensure_ascii=False),
                    values["recommended_title_index"],
                    values["recommended_meta_index"],
                    values["title_proposals"][
                        values["recommended_title_index"]
                    ]["text"],
                    values["meta_proposals"][
                        values["recommended_meta_index"]
                    ]["text"],
                    values["confidence"], values["expected_effect"],
                    values["measurement_method"], timestamp, timestamp,
                ),
            )
            draft_id = int(cursor.lastrowid)
            for item in competitors[:10]:
                self._connection.execute(
                    """INSERT OR IGNORE INTO title_serp_competitors (
                        draft_id, position, domain, url, title,
                        meta_description, h1, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        draft_id, item["position"], item["domain"], item["url"],
                        item["title"], item.get("meta_description", ""),
                        item.get("h1", ""), timestamp,
                    ),
                )
        return draft_id

    def get_title_optimization_drafts(
        self, website_id: str | None = None
    ) -> list[dict[str, Any]]:
        query, parameters = "SELECT * FROM title_optimization_drafts", ()
        if website_id:
            query += " WHERE website_id = ?"
            parameters = (website_id,)
        query += " ORDER BY id DESC"
        rows = self._connection.execute(query, parameters).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for field in (
                "page_analysis_json", "analysis_json",
                "title_proposals_json", "meta_proposals_json",
                "reviewer_json",
            ):
                item[field.removesuffix("_json")] = json.loads(item[field])
            result.append(item)
        return result

    def get_title_optimization_draft(
        self, draft_id: int
    ) -> dict[str, Any] | None:
        return next((
            item for item in self.get_title_optimization_drafts()
            if item["id"] == draft_id
        ), None)

    def update_title_optimization_draft(
        self, draft_id: int, values: dict[str, Any]
    ) -> None:
        allowed = {
            "selected_title", "selected_meta", "status", "project_id",
            "task_id", "experiment_id", "approved_at", "rejected_at",
            "implemented_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        with self._connection:
            self._connection.execute(
                "UPDATE title_optimization_drafts SET "
                + ", ".join(f"{key} = ?" for key in updates)
                + " WHERE id = ?",
                (*updates.values(), draft_id),
            )

    def get_title_serp_competitors(
        self, draft_id: int
    ) -> list[dict[str, Any]]:
        return [
            dict(row) for row in self._connection.execute(
                """SELECT * FROM title_serp_competitors
                   WHERE draft_id = ? ORDER BY position""",
                (draft_id,),
            ).fetchall()
        ]

    def create_decision(self, decision: dict[str, Any]) -> int:
        """Persist one proposed decision and its sanitized JSON payload."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            cursor = self._connection.execute(
                """INSERT INTO decision_history (
                    website_id, target_url, target_query, task_title,
                    decision_json, priority_score, confidence, status,
                    selected_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?)""",
                (
                    decision["website"], decision["target_url"],
                    decision.get("target_query", ""), decision["task_title"],
                    json.dumps(decision, ensure_ascii=False),
                    decision["priority_score"], decision["confidence"],
                    timestamp, timestamp, timestamp,
                ),
            )
        return int(cursor.lastrowid)

    def get_decisions(
        self, *, statuses: tuple[str, ...] | None = None,
        website_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        if statuses:
            clauses.append(
                "status IN (" + ", ".join("?" for _ in statuses) + ")"
            )
            parameters.extend(statuses)
        if website_id:
            clauses.append("website_id = ?")
            parameters.append(website_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM decision_history {where} ORDER BY id DESC",
            parameters,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["decision"] = json.loads(item["decision_json"])
            result.append(item)
        return result

    def update_decision_status(self, decision_id: int, status: str) -> None:
        """Update a decision and the matching lifecycle timestamp."""
        allowed = {
            "proposed", "approved", "rejected", "converted_to_experiment",
            "completed", "cancelled",
        }
        if status not in allowed:
            raise ValueError("Ugyldig beslutningsstatus.")
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        timestamp_field = {
            "approved": "approved_at", "rejected": "rejected_at",
            "completed": "completed_at",
        }.get(status)
        extra = f", {timestamp_field} = ?" if timestamp_field else ""
        parameters = (
            (status, timestamp, timestamp, decision_id)
            if timestamp_field else (status, timestamp, decision_id)
        )
        with self._connection:
            self._connection.execute(
                f"""UPDATE decision_history SET status = ?, updated_at = ?
                    {extra} WHERE id = ?""",
                parameters,
            )

    def create_seo_experiment(self, values: dict[str, Any]) -> int:
        """Persist one planned experiment without starting it."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        fields = (
            "website_id", "decision_id", "project_id", "task_id",
            "target_url", "target_query", "experiment_type", "hypothesis",
            "change_description", "goal_metric", "goal_direction",
            "target_change_pct", "waiting_period_days", "status", "confidence",
            "created_at", "updated_at",
        )
        parameters = tuple(values.get(field) for field in fields[:-2]) + (
            timestamp, timestamp,
        )
        with self._connection:
            cursor = self._connection.execute(
                f"""INSERT INTO seo_experiments ({", ".join(fields)})
                    VALUES ({", ".join("?" for _ in fields)})""",
                parameters,
            )
        return int(cursor.lastrowid)

    def get_seo_experiments(
        self, *, website_id: str | None = None,
        target_url: str | None = None, statuses: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        if website_id:
            clauses.append("website_id = ?")
            parameters.append(website_id)
        if target_url:
            clauses.append("target_url = ?")
            parameters.append(target_url)
        if statuses:
            clauses.append(
                "status IN (" + ", ".join("?" for _ in statuses) + ")"
            )
            parameters.extend(statuses)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM seo_experiments {where} ORDER BY id DESC",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_seo_experiment(self, experiment_id: int) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM seo_experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_seo_experiment(
        self, experiment_id: int, values: dict[str, Any]
    ) -> None:
        """Update explicitly supplied experiment fields."""
        allowed = {
            row["name"] for row in
            self._connection.execute("PRAGMA table_info(seo_experiments)")
        } - {"id", "created_at"}
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._connection:
            self._connection.execute(
                f"UPDATE seo_experiments SET {assignments} WHERE id = ?",
                (*updates.values(), experiment_id),
            )

    def save_experiment_learning(
        self, *, experiment_id: int, website_id: str, target_url: str,
        experiment_type: str, outcome: str, learning: str,
    ) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """INSERT INTO experiment_learnings (
                    experiment_id, website_id, target_url, experiment_type,
                    outcome, learning, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    outcome = excluded.outcome, learning = excluded.learning""",
                (
                    experiment_id, website_id, target_url, experiment_type,
                    outcome, learning, timestamp,
                ),
            )

    def get_experiment_learnings(
        self, website_id: str | None = None
    ) -> list[dict[str, Any]]:
        query, parameters = "SELECT * FROM experiment_learnings", ()
        if website_id:
            query += " WHERE website_id = ?"
            parameters = (website_id,)
        query += " ORDER BY id DESC"
        return [
            dict(row) for row in self._connection.execute(
                query, parameters
            ).fetchall()
        ]

    def preview_robotland_redesign_cleanup(self) -> dict[str, Any]:
        """Return an exact, read-only preview of the known Robotland fixture."""
        project = self.get_project_by_website_and_title(
            "robotland.dk", "Redesign af Robotland.dk"
        )
        if not project:
            return {
                "project_id": None, "subprojects": 0, "tasks": 0,
                "events": 0, "actions": 0, "recommendations": 0,
            }
        project_id = int(project["id"])
        tasks = self.get_task_records_for_project(project_id)
        task_ids = [item["id"] for item in tasks]
        action_row = self._connection.execute(
            """SELECT COUNT(*) AS total FROM actions
               WHERE project_id = ?
                  OR task_id IN (
                      SELECT t.id FROM tasks t
                      JOIN subprojects sp ON sp.id = t.subproject_id
                      WHERE sp.project_id = ?
                  )""",
            (project_id, project_id),
        ).fetchone()
        event_row = self._connection.execute(
            """SELECT COUNT(DISTINCT e.id) AS total FROM events e
               JOIN actions a ON a.event_id = e.id
               WHERE a.project_id = ?
                  OR a.task_id IN (
                      SELECT t.id FROM tasks t
                      JOIN subprojects sp ON sp.id = t.subproject_id
                      WHERE sp.project_id = ?
                  )""",
            (project_id, project_id),
        ).fetchone()
        recommendation_row = self._connection.execute(
            "SELECT COUNT(*) AS total FROM seo_recommendations WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return {
            "project_id": project_id,
            "subprojects": len(self.get_subprojects_for_project(project_id)),
            "tasks": len(tasks), "task_ids": task_ids,
            "events": int(event_row["total"]),
            "actions": int(action_row["total"]),
            "recommendations": int(recommendation_row["total"]),
        }

    def cleanup_robotland_redesign_test_data(self) -> dict[str, Any]:
        """Delete only the explicitly named Robotland redesign fixture."""
        preview = self.preview_robotland_redesign_cleanup()
        project_id = preview["project_id"]
        if project_id is None:
            return {**preview, "deleted": False}
        allowed_subprojects = {
            "Analyse og plan", "Fælles layout", "Forside", "Kategorisider",
            "Artikler og produktsider", "Test og lancering",
        }
        allowed_tasks = {
            "Gennemgå den nuværende header og noter problemer",
            "Lav forslag til ny navigation",
            "Definér krav til en ny header",
        }
        subprojects = self.get_subprojects_for_project(project_id)
        tasks = self.get_task_records_for_project(project_id)
        if {item["title"] for item in subprojects} - allowed_subprojects:
            raise ValueError("Projektet indeholder ukendte delprojekter; afbryder.")
        if {item["title"] for item in tasks} - allowed_tasks:
            raise ValueError("Projektet indeholder ukendte opgaver; afbryder.")
        with self._connection:
            event_ids = [
                row["id"] for row in self._connection.execute(
                    """SELECT DISTINCT e.id FROM events e
                       JOIN actions a ON a.event_id = e.id
                       WHERE a.project_id = ?
                          OR a.task_id IN (
                              SELECT t.id FROM tasks t
                              JOIN subprojects sp ON sp.id = t.subproject_id
                              WHERE sp.project_id = ?
                          )""",
                    (project_id, project_id),
                )
            ]
            self._connection.execute(
                """DELETE FROM actions WHERE project_id = ?
                   OR task_id IN (
                       SELECT t.id FROM tasks t
                       JOIN subprojects sp ON sp.id = t.subproject_id
                       WHERE sp.project_id = ?
                   )""",
                (project_id, project_id),
            )
            if event_ids:
                placeholders = ", ".join("?" for _ in event_ids)
                self._connection.execute(
                    f"""DELETE FROM events WHERE id IN ({placeholders})
                        AND source IN ('test', 'project_manager')""",
                    event_ids,
                )
            self._connection.execute(
                "DELETE FROM seo_recommendations WHERE project_id = ?",
                (project_id,),
            )
            self._connection.execute(
                """DELETE FROM tasks WHERE subproject_id IN (
                    SELECT id FROM subprojects WHERE project_id = ?)""",
                (project_id,),
            )
            self._connection.execute(
                "DELETE FROM subprojects WHERE project_id = ?", (project_id,)
            )
            self._connection.execute(
                """DELETE FROM projects WHERE id = ? AND website_id = ?
                   AND title = ?""",
                (project_id, "robotland.dk", "Redesign af Robotland.dk"),
            )
        return {**preview, "deleted": True}

    def _create_website_content_table(self) -> None:
        """Create idempotent public website content storage."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS website_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                content_type TEXT NOT NULL,
                content_id TEXT NOT NULL,
                title TEXT NOT NULL,
                slug TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                published_at TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                category_json TEXT NOT NULL,
                tag_json TEXT NOT NULL,
                excerpt TEXT NOT NULL DEFAULT '',
                content_text TEXT NOT NULL DEFAULT '',
                content_sections_json TEXT NOT NULL DEFAULT '[]',
                word_count INTEGER NOT NULL,
                featured_image TEXT NOT NULL,
                internal_link_count INTEGER NOT NULL,
                external_link_count INTEGER NOT NULL,
                raw_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, content_type, content_id),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )
        columns = {
            str(row["name"])
            for row in self._connection.execute(
                "PRAGMA table_info(website_content)"
            ).fetchall()
        }
        additions = {
            "excerpt": "TEXT NOT NULL DEFAULT ''",
            "content_text": "TEXT NOT NULL DEFAULT ''",
            "content_sections_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for name, definition in additions.items():
            if name not in columns:
                self._connection.execute(
                    f"ALTER TABLE website_content ADD COLUMN {name} {definition}"
                )

    def save_content(self, content: dict[str, Any]) -> str:
        """Create or update public content only when its stable hash changes."""
        existing = self._connection.execute(
            """
            SELECT id, raw_hash FROM website_content
            WHERE website_id=? AND content_type=? AND content_id=?
            """,
            (
                content["website_id"], content["content_type"],
                content["content_id"],
            ),
        ).fetchone()
        if existing and existing["raw_hash"] == content["raw_hash"]:
            return "unchanged"
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO website_content (
                    website_id, content_type, content_id, title, slug, url,
                    status, published_at, source_updated_at, category_json,
                    tag_json, excerpt, content_text, content_sections_json,
                    word_count, featured_image, internal_link_count,
                    external_link_count, raw_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, content_type, content_id) DO UPDATE SET
                    title=excluded.title, slug=excluded.slug, url=excluded.url,
                    status=excluded.status, published_at=excluded.published_at,
                    source_updated_at=excluded.source_updated_at,
                    category_json=excluded.category_json,
                    tag_json=excluded.tag_json, excerpt=excluded.excerpt,
                    content_text=excluded.content_text,
                    content_sections_json=excluded.content_sections_json,
                    word_count=excluded.word_count,
                    featured_image=excluded.featured_image,
                    internal_link_count=excluded.internal_link_count,
                    external_link_count=excluded.external_link_count,
                    raw_hash=excluded.raw_hash, updated_at=excluded.updated_at
                """,
                (
                    content["website_id"], content["content_type"],
                    content["content_id"], content.get("title", ""),
                    content.get("slug", ""), content.get("url", ""),
                    content.get("status", ""), content.get("published_at", ""),
                    content.get("updated_at", ""),
                    json.dumps(content.get("categories", []), ensure_ascii=False),
                    json.dumps(content.get("tags", []), ensure_ascii=False),
                    content.get("excerpt", ""),
                    content.get("content_text", ""),
                    json.dumps(
                        content.get("content_sections", []),
                        ensure_ascii=False,
                    ),
                    int(content.get("word_count", 0)),
                    content.get("featured_image", ""),
                    int(content.get("internal_link_count", 0)),
                    int(content.get("external_link_count", 0)),
                    content["raw_hash"], now, now,
                ),
            )
        return "updated" if existing else "created"

    def get_content(
        self, website_id: str, content_id: str | None = None
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        """Return all website content or one item by its public ID."""
        if content_id is not None:
            row = self._connection.execute(
                """
                SELECT * FROM website_content
                WHERE website_id=? AND content_id=?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (website_id, content_id),
            ).fetchone()
            return self._content_row(row) if row else None
        rows = self._connection.execute(
            """
            SELECT * FROM website_content
            WHERE website_id=? ORDER BY published_at DESC, title
            """,
            (website_id,),
        ).fetchall()
        return [self._content_row(row) for row in rows]

    def get_content_by_type(
        self, website_id: str, content_type: str
    ) -> list[dict[str, Any]]:
        """Return one public content type for a website."""
        rows = self._connection.execute(
            """
            SELECT * FROM website_content
            WHERE website_id=? AND content_type=?
            ORDER BY published_at DESC, title
            """,
            (website_id, content_type),
        ).fetchall()
        return [self._content_row(row) for row in rows]

    def get_content_freshness_reviews(self) -> dict[str, dict[str, Any]]:
        """Return cached AI freshness decisions keyed by normalized URL."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            ("content_freshness_reviews",),
        ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(str(row["value"]))
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def save_content_freshness_reviews(
        self, reviews: dict[str, dict[str, Any]]
    ) -> None:
        """Persist non-secret freshness decisions from the background check."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (
                    "content_freshness_reviews",
                    json.dumps(reviews, ensure_ascii=False, default=str),
                ),
            )

    def get_recently_updated(
        self, website_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recently imported or changed content."""
        query = "SELECT * FROM website_content"
        parameters: list[Any] = []
        if website_id:
            query += " WHERE website_id=?"
            parameters.append(website_id)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        parameters.append(max(1, int(limit)))
        rows = self._connection.execute(query, parameters).fetchall()
        return [self._content_row(row) for row in rows]

    @staticmethod
    def _content_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["categories"] = json.loads(item.pop("category_json"))
        item["tags"] = json.loads(item.pop("tag_json"))
        item["content_sections"] = json.loads(
            item.pop("content_sections_json", "[]") or "[]"
        )
        item["content_updated_at"] = item.pop("source_updated_at")
        return item

    def _create_website_discovery_tables(self) -> None:
        """Create current and change-only historical website discovery data."""
        fields = """
            website_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            cms TEXT NOT NULL,
            cms_confidence INTEGER NOT NULL,
            theme TEXT NOT NULL,
            theme_confidence INTEGER NOT NULL,
            page_builder TEXT NOT NULL,
            page_builder_confidence INTEGER NOT NULL,
            http_status INTEGER NOT NULL,
            https_enabled INTEGER NOT NULL,
            robots_status TEXT NOT NULL,
            sitemap_status TEXT NOT NULL,
            sitemap_url TEXT NOT NULL,
            sitemap_url_count INTEGER NOT NULL,
            sitemap_types_json TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            title TEXT NOT NULL,
            meta_description TEXT NOT NULL,
            h1 TEXT NOT NULL,
            schema_types_json TEXT NOT NULL,
            generator TEXT NOT NULL,
            wordpress_rest_available INTEGER NOT NULL,
            detected_signals_json TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            error_message TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        """
        self._connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS website_discovery_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {fields},
                created_at TEXT NOT NULL,
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )
        self._connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS website_discovery_current (
                {fields},
                PRIMARY KEY (website_id),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def save_website_discovery_profile(
        self, profile: dict[str, Any]
    ) -> dict[str, Any]:
        """Update current discovery facts and append history only on change."""
        now = profile.get("scanned_at") or datetime.now().astimezone(
        ).isoformat(timespec="seconds")
        current = self.get_website_discovery_profile(profile["website_id"])
        values = self._discovery_values(profile, now)
        changed = current is None or any(
            current.get(key) != profile.get(key)
            for key in self._discovery_comparison_fields()
        )
        columns = self._discovery_columns()
        placeholders = ", ".join("?" for _ in columns)
        assignments = ", ".join(
            f"{column}=excluded.{column}" for column in columns
            if column != "website_id"
        )
        with self._connection:
            self._connection.execute(
                f"""
                INSERT INTO website_discovery_current ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(website_id) DO UPDATE SET {assignments}
                """,
                values,
            )
            if changed:
                history_columns = [*columns, "created_at"]
                self._connection.execute(
                    f"""
                    INSERT INTO website_discovery_profiles
                        ({", ".join(history_columns)})
                    VALUES ({", ".join("?" for _ in history_columns)})
                    """,
                    (*values, now),
                )
        return {"changed": changed, "previous": current}

    def get_website_discovery_profile(
        self, website_id: str
    ) -> dict[str, Any] | None:
        """Return the latest discovery profile for one website."""
        row = self._connection.execute(
            "SELECT * FROM website_discovery_current WHERE website_id = ?",
            (website_id,),
        ).fetchone()
        return self._discovery_row(row) if row else None

    def get_website_discovery_profiles(self) -> list[dict[str, Any]]:
        """Return every current discovery profile."""
        rows = self._connection.execute(
            "SELECT * FROM website_discovery_current ORDER BY website_id"
        ).fetchall()
        return [self._discovery_row(row) for row in rows]

    def get_website_discovery_changes(
        self, website_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return change-only profile history, newest first."""
        rows = self._connection.execute(
            """
            SELECT * FROM website_discovery_profiles
            WHERE website_id = ? ORDER BY scanned_at DESC, id DESC LIMIT ?
            """,
            (website_id, max(1, int(limit))),
        ).fetchall()
        return [self._discovery_row(row) for row in rows]

    def get_website_discovery_summary(self) -> dict[str, Any]:
        """Return dashboard counters for current discovery profiles."""
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS scanned,
                SUM(CASE WHEN cms='wordpress' THEN 1 ELSE 0 END) AS wordpress,
                SUM(CASE WHEN cms='unknown' THEN 1 ELSE 0 END) AS unknown,
                SUM(CASE WHEN robots_status NOT IN ('ok','allowed')
                    THEN 1 ELSE 0 END) AS robots_errors,
                SUM(CASE WHEN sitemap_status!='ok' THEN 1 ELSE 0 END)
                    AS sitemap_errors,
                SUM(CASE WHEN https_enabled=0 THEN 1 ELSE 0 END) AS https_errors,
                MAX(scanned_at) AS latest_scan
            FROM website_discovery_current
            """
        ).fetchone()
        return {
            "scanned": int(row["scanned"] or 0),
            "wordpress": int(row["wordpress"] or 0),
            "unknown": int(row["unknown"] or 0),
            "robots_errors": int(row["robots_errors"] or 0),
            "sitemap_errors": int(row["sitemap_errors"] or 0),
            "https_errors": int(row["https_errors"] or 0),
            "latest_scan": row["latest_scan"],
        }

    @staticmethod
    def _discovery_columns() -> list[str]:
        return [
            "website_id", "domain", "cms", "cms_confidence", "theme",
            "theme_confidence", "page_builder", "page_builder_confidence",
            "http_status", "https_enabled", "robots_status", "sitemap_status",
            "sitemap_url", "sitemap_url_count", "sitemap_types_json",
            "canonical_url", "title", "meta_description", "h1",
            "schema_types_json", "generator", "wordpress_rest_available",
            "detected_signals_json", "scan_status", "error_message",
            "scanned_at", "updated_at",
        ]

    @classmethod
    def _discovery_values(
        cls, profile: dict[str, Any], timestamp: str
    ) -> tuple[Any, ...]:
        encoded = {
            **profile,
            "https_enabled": int(bool(profile.get("https_enabled"))),
            "wordpress_rest_available": int(
                bool(profile.get("wordpress_rest_available"))
            ),
            "sitemap_types_json": json.dumps(
                profile.get("sitemap_types", []), ensure_ascii=False
            ),
            "schema_types_json": json.dumps(
                profile.get("schema_types", []), ensure_ascii=False
            ),
            "detected_signals_json": json.dumps(
                profile.get("detected_signals", []), ensure_ascii=False
            ),
            "scanned_at": timestamp, "updated_at": timestamp,
        }
        return tuple(encoded.get(column, "") for column in cls._discovery_columns())

    @staticmethod
    def _discovery_comparison_fields() -> tuple[str, ...]:
        return (
            "cms", "theme", "page_builder", "http_status", "https_enabled",
            "robots_status", "sitemap_status", "sitemap_url_count",
            "canonical_url", "title", "meta_description", "h1",
            "schema_types", "generator", "wordpress_rest_available",
            "detected_signals", "scan_status", "error_message",
        )

    @staticmethod
    def _discovery_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for stored, exposed in (
            ("sitemap_types_json", "sitemap_types"),
            ("schema_types_json", "schema_types"),
            ("detected_signals_json", "detected_signals"),
        ):
            item[exposed] = json.loads(item.pop(stored))
        item["https_enabled"] = bool(item["https_enabled"])
        item["wordpress_rest_available"] = bool(
            item["wordpress_rest_available"]
        )
        item["suggested_connector"] = (
            "WordPressConnector" if item["cms"] == "wordpress" else None
        )
        return item

    def _create_executive_briefings_table(self) -> None:
        """Create versioned daily executive briefings without duplicates."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS executive_briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                briefing_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                company_status TEXT NOT NULL,
                focus_areas_json TEXT NOT NULL,
                risks_json TEXT NOT NULL,
                opportunities_json TEXT NOT NULL,
                total_estimated_minutes INTEGER NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (briefing_date, status)
            )
            """
        )

    def save_executive_briefing(self, briefing: dict[str, Any]) -> int:
        """Upsert one briefing by date and status and return its stable ID."""
        timestamp = briefing.get("updated_at") or datetime.now().astimezone(
        ).isoformat(timespec="seconds")
        created_at = briefing.get("created_at") or timestamp
        values = (
            briefing["briefing_date"],
            briefing["summary"],
            briefing["company_status"],
            json.dumps(briefing["focus_areas"], ensure_ascii=False),
            json.dumps(briefing["risks"], ensure_ascii=False),
            json.dumps(briefing["opportunities"], ensure_ascii=False),
            int(briefing["total_estimated_minutes"]),
            briefing["model"],
            int(briefing.get("prompt_tokens", 0)),
            int(briefing.get("completion_tokens", 0)),
            int(briefing.get("latency_ms", 0)),
            briefing.get("status", "completed"),
            created_at,
            timestamp,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO executive_briefings (
                    briefing_date, summary, company_status, focus_areas_json,
                    risks_json, opportunities_json, total_estimated_minutes,
                    model, prompt_tokens, completion_tokens, latency_ms,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(briefing_date, status) DO UPDATE SET
                    summary=excluded.summary,
                    company_status=excluded.company_status,
                    focus_areas_json=excluded.focus_areas_json,
                    risks_json=excluded.risks_json,
                    opportunities_json=excluded.opportunities_json,
                    total_estimated_minutes=excluded.total_estimated_minutes,
                    model=excluded.model,
                    prompt_tokens=excluded.prompt_tokens,
                    completion_tokens=excluded.completion_tokens,
                    latency_ms=excluded.latency_ms,
                    updated_at=excluded.updated_at
                """,
                values,
            )
        row = self._connection.execute(
            "SELECT id FROM executive_briefings "
            "WHERE briefing_date = ? AND status = ?",
            (briefing["briefing_date"], briefing.get("status", "completed")),
        ).fetchone()
        return int(row["id"])

    def get_latest_executive_briefing(self) -> dict[str, Any] | None:
        """Return the newest completed executive briefing."""
        row = self._connection.execute(
            """
            SELECT * FROM executive_briefings
            WHERE status = 'completed'
            ORDER BY briefing_date DESC, updated_at DESC, id DESC LIMIT 1
            """
        ).fetchone()
        return self._executive_briefing_row(row) if row else None

    def get_executive_briefing_history(
        self, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Return recent executive briefings for dashboards and audits."""
        rows = self._connection.execute(
            """
            SELECT * FROM executive_briefings
            ORDER BY briefing_date DESC, updated_at DESC, id DESC LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        return [self._executive_briefing_row(row) for row in rows]

    @staticmethod
    def _executive_briefing_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for stored, exposed in (
            ("focus_areas_json", "focus_areas"),
            ("risks_json", "risks"),
            ("opportunities_json", "opportunities"),
        ):
            item[exposed] = json.loads(item.pop(stored))
        return item

    def get_executive_context(self) -> dict[str, Any]:
        """Return the persisted, non-secret company context for prioritizing."""
        projects = self._connection.execute(
            "SELECT * FROM projects WHERE status NOT IN ('completed','cancelled')"
        ).fetchall()
        tasks = self._connection.execute(
            """
            SELECT t.*, sp.project_id, p.title AS project_title
            FROM tasks t JOIN subprojects sp ON sp.id=t.subproject_id
            JOIN projects p ON p.id=sp.project_id
            WHERE t.status NOT IN ('completed','cancelled')
            """
        ).fetchall()
        sales = self._connection.execute(
            """
            SELECT LOWER(REPLACE(REPLACE(url,'https://',''),'http://',''))
                AS source, COUNT(*) AS sales_count,
                COALESCE(SUM(omsaetning),0) AS revenue,
                COALESCE(SUM(provision),0) AS commission
            FROM registered_sales GROUP BY source
            """
        ).fetchall()
        return {
            "websites": self.get_all_websites(),
            "profiles": self.get_website_profiles(),
            "seo_health": self.get_lowest_seo_scores(limit=100),
            "search_console": self.get_search_console_comparisons(),
            "seo_recommendations": self.get_seo_recommendations(),
            "projects": [dict(row) for row in projects],
            "tasks": [dict(row) for row in tasks],
            "sales": [dict(row) for row in sales],
            "analyses": self.get_analysis_history(limit=100),
            "counts": {
                "active_projects": len(projects),
                "open_tasks": len(tasks),
            },
        }

    def _create_ai_analysis_table(self) -> None:
        """Create immutable AI Analyst reports and usage metadata."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT,
                project_id INTEGER,
                task_id INTEGER,
                analysis_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                problem TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                recommended_action TEXT NOT NULL,
                priority TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                expected_effect TEXT NOT NULL,
                reasoning_json TEXT NOT NULL,
                required_agents_json TEXT NOT NULL,
                suggested_tasks_json TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (website_id) REFERENCES websites(website),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
            """
        )

    def _create_search_console_table(self) -> None:
        """Create the Google Search Console property registry."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS search_console_properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_url TEXT NOT NULL UNIQUE,
                permission_level TEXT NOT NULL,
                website_id TEXT,
                active INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def _create_search_console_daily_metrics_table(self) -> None:
        """Create daily Search Console metrics with an idempotent key."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS search_console_daily_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                site_url TEXT NOT NULL,
                metric_date TEXT NOT NULL,
                clicks INTEGER NOT NULL,
                impressions INTEGER NOT NULL,
                ctr REAL NOT NULL,
                average_position REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, metric_date),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def _create_plausible_daily_metrics_table(self) -> None:
        """Create idempotent daily Plausible visitor storage."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plausible_daily_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                metric_date TEXT NOT NULL,
                visitors INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, metric_date),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def _create_search_console_dimension_tables(self) -> None:
        """Create idempotent page/query Search Console period storage."""
        for table, identity, unique_key in (
            ("search_console_pages", "page_url TEXT NOT NULL",
             "website_id, page_url, period_start, period_end"),
            ("search_console_queries", "query TEXT NOT NULL",
             "website_id, query, period_start, period_end"),
            ("search_console_page_queries",
             "page_url TEXT NOT NULL, query TEXT NOT NULL",
             "website_id, page_url, query, period_start, period_end"),
        ):
            self._connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id TEXT NOT NULL,
                    site_url TEXT NOT NULL,
                    dimension_type TEXT NOT NULL,
                    {identity},
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    clicks INTEGER NOT NULL,
                    impressions INTEGER NOT NULL,
                    ctr REAL NOT NULL,
                    average_position REAL NOT NULL,
                    imported_at TEXT NOT NULL,
                    UNIQUE ({unique_key}),
                    FOREIGN KEY (website_id) REFERENCES websites(website)
                )
                """
            )

    def _create_search_console_diagnoses_table(self) -> None:
        """Store deterministic traffic-loss diagnoses by comparison period."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS search_console_diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                previous_period_start TEXT NOT NULL,
                previous_period_end TEXT NOT NULL,
                status TEXT NOT NULL,
                data_quality TEXT NOT NULL,
                previous_clicks INTEGER NOT NULL,
                current_clicks INTEGER NOT NULL,
                click_loss INTEGER NOT NULL,
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, period_start, period_end),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def _create_plausible_diagnoses_table(self) -> None:
        """Store deterministic Plausible comparisons by period."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plausible_diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                previous_period_start TEXT NOT NULL,
                previous_period_end TEXT NOT NULL,
                status TEXT NOT NULL,
                data_quality TEXT NOT NULL,
                previous_visitors INTEGER NOT NULL,
                current_visitors INTEGER NOT NULL,
                visitor_change INTEGER NOT NULL,
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, period_start, period_end),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def _create_seo_health_history_table(self) -> None:
        """Create idempotent SEO health snapshots for every analysis period."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS seo_health_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                date TEXT NOT NULL,
                period TEXT NOT NULL,
                score REAL NOT NULL,
                trend TEXT NOT NULL,
                click_change REAL,
                impression_change REAL,
                ctr_change REAL,
                position_change REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, date, period),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            )
            """
        )

    def _create_seo_recommendations_table(self) -> None:
        """Create idempotent SEO Manager analysis recommendations."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS seo_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                analysis_date TEXT NOT NULL,
                seo_score REAL NOT NULL,
                trend TEXT NOT NULL,
                reason TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                priority TEXT NOT NULL,
                project_id INTEGER,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, analysis_date),
                FOREIGN KEY (website_id) REFERENCES websites(website),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
            """
        )

    def _create_website_intelligence_tables(self) -> None:
        """Create current, statistical, categorical, and historical profiles."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS website_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL,
                cms TEXT NOT NULL,
                theme TEXT NOT NULL,
                monetization TEXT NOT NULL,
                niche TEXT NOT NULL,
                website_health REAL NOT NULL,
                strong_areas_json TEXT NOT NULL,
                weak_areas_json TEXT NOT NULL,
                ai_recommendations_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );

            CREATE TABLE IF NOT EXISTS website_statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                statistic_date TEXT NOT NULL,
                search_clicks INTEGER NOT NULL,
                search_impressions INTEGER NOT NULL,
                search_ctr REAL NOT NULL,
                average_position REAL,
                sales_count INTEGER NOT NULL,
                revenue REAL NOT NULL,
                commission REAL NOT NULL,
                seo_score REAL,
                seo_trend TEXT,
                active_projects INTEGER NOT NULL,
                active_tasks INTEGER NOT NULL,
                website_health REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, statistic_date),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );

            CREATE TABLE IF NOT EXISTS website_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                category TEXT NOT NULL,
                category_type TEXT NOT NULL,
                rank INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (website_id, category, category_type),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );

            CREATE TABLE IF NOT EXISTS website_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id TEXT NOT NULL,
                history_date TEXT NOT NULL,
                changed_fields_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (website_id, history_date),
                FOREIGN KEY (website_id) REFERENCES websites(website)
            );
            """
        )

    def upsert_search_console_property(
        self,
        *,
        site_url: str,
        permission_level: str,
        website_id: str | None,
        active: bool = True,
    ) -> int:
        """Insert or update one Search Console property without duplicates."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO search_console_properties (
                    site_url, permission_level, website_id, active,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_url) DO UPDATE SET
                    permission_level = excluded.permission_level,
                    website_id = excluded.website_id,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    site_url,
                    permission_level,
                    website_id,
                    int(active),
                    timestamp,
                    timestamp,
                ),
            )
        row = self._connection.execute(
            "SELECT id FROM search_console_properties WHERE site_url = ?",
            (site_url,),
        ).fetchone()
        return int(row["id"])

    def get_search_console_properties(self) -> list[dict[str, Any]]:
        """Return every stored Search Console property."""
        rows = self._connection.execute(
            """
            SELECT
                id, site_url, permission_level, website_id, active,
                created_at, updated_at
            FROM search_console_properties
            ORDER BY site_url
            """
        ).fetchall()
        properties = [dict(row) for row in rows]
        for item in properties:
            item["active"] = bool(item["active"])
        return properties

    def deactivate_missing_search_console_properties(
        self, available_site_urls: set[str]
    ) -> int:
        """Deactivate stored properties no longer returned by Google."""
        available = {str(value).strip() for value in available_site_urls}
        active_rows = self._connection.execute(
            """
            SELECT site_url
            FROM search_console_properties
            WHERE active = 1
            """
        ).fetchall()
        missing = [
            str(row["site_url"])
            for row in active_rows
            if str(row["site_url"]) not in available
        ]
        if not missing:
            return 0
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        placeholders = ", ".join("?" for _ in missing)
        with self._connection:
            cursor = self._connection.execute(
                f"""
                UPDATE search_console_properties
                SET active = 0, updated_at = ?
                WHERE active = 1
                  AND site_url IN ({placeholders})
                """,
                (timestamp, *missing),
            )
        return int(cursor.rowcount)

    def upsert_search_console_daily_metric(
        self,
        *,
        website_id: str,
        site_url: str,
        metric_date: str,
        clicks: int,
        impressions: int,
        ctr: float,
        average_position: float,
    ) -> str:
        """Insert or update one daily metric and return the write action."""
        existing = self._connection.execute(
            """
            SELECT site_url, clicks, impressions, ctr, average_position
            FROM search_console_daily_metrics
            WHERE website_id = ? AND metric_date = ?
            """,
            (website_id, metric_date),
        ).fetchone()
        unchanged = bool(existing) and (
            str(existing["site_url"]) == str(site_url)
            and int(existing["clicks"]) == int(clicks)
            and int(existing["impressions"]) == int(impressions)
            and float(existing["ctr"]) == float(ctr)
            and float(existing["average_position"]) == float(average_position)
        )
        if unchanged:
            return "unchanged"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO search_console_daily_metrics (
                    website_id, site_url, metric_date, clicks, impressions,
                    ctr, average_position, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, metric_date) DO UPDATE SET
                    site_url = excluded.site_url,
                    clicks = excluded.clicks,
                    impressions = excluded.impressions,
                    ctr = excluded.ctr,
                    average_position = excluded.average_position,
                    updated_at = excluded.updated_at
                """,
                (
                    website_id,
                    site_url,
                    metric_date,
                    clicks,
                    impressions,
                    ctr,
                    average_position,
                    timestamp,
                    timestamp,
                ),
            )
        return "updated" if existing else "created"

    def upsert_plausible_daily_metric_action(
        self, *, website_id: str, metric_date: str, visitors: int
    ) -> str:
        """Upsert a Plausible metric and distinguish identical values."""
        existing = self._connection.execute(
            """
            SELECT visitors FROM plausible_daily_metrics
            WHERE website_id = ? AND metric_date = ?
            """,
            (website_id, metric_date),
        ).fetchone()
        if existing and int(existing["visitors"]) == int(visitors):
            return "unchanged"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO plausible_daily_metrics (
                    website_id, metric_date, visitors, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(website_id, metric_date) DO UPDATE SET
                    visitors = excluded.visitors,
                    updated_at = excluded.updated_at
                """,
                (website_id, metric_date, int(visitors), timestamp, timestamp),
            )
        return "updated" if existing else "created"

    def upsert_plausible_daily_metric(
        self, *, website_id: str, metric_date: str, visitors: int
    ) -> bool:
        """Upsert one Plausible metric and return whether it was inserted."""
        return self.upsert_plausible_daily_metric_action(
            website_id=website_id, metric_date=metric_date, visitors=visitors
        ) == "created"

    def get_plausible_daily_metrics(
        self, *, website_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return stored Plausible metrics for verification and later use."""
        where, parameters = "", ()
        if website_id:
            where, parameters = "WHERE website_id = ?", (website_id,)
        rows = self._connection.execute(
            f"""
            SELECT website_id, metric_date, visitors, created_at, updated_at
            FROM plausible_daily_metrics
            {where}
            ORDER BY metric_date DESC, website_id
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_plausible_metric_date(
        self, website_id: str
    ) -> str | None:
        """Return the latest stored Plausible date for one website."""
        row = self._connection.execute(
            """
            SELECT MAX(metric_date) AS latest_date
            FROM plausible_daily_metrics
            WHERE website_id = ?
            """,
            (website_id,),
        ).fetchone()
        return row["latest_date"] if row and row["latest_date"] else None

    def get_earliest_plausible_metric_date(
        self, website_id: str
    ) -> str | None:
        """Return the earliest stored Plausible date for one website."""
        row = self._connection.execute(
            """
            SELECT MIN(metric_date) AS earliest_date
            FROM plausible_daily_metrics
            WHERE website_id = ?
            """,
            (website_id,),
        ).fetchone()
        return row["earliest_date"] if row and row["earliest_date"] else None

    def get_search_console_daily_metrics(
        self,
        website_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return stored daily metrics with optional website/date filters."""
        conditions: list[str] = []
        parameters: list[str] = []
        if website_id:
            conditions.append("website_id = ?")
            parameters.append(website_id)
        if start_date:
            conditions.append("metric_date >= ?")
            parameters.append(start_date)
        if end_date:
            conditions.append("metric_date <= ?")
            parameters.append(end_date)
        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )
        rows = self._connection.execute(
            f"""
            SELECT
                id, website_id, site_url, metric_date, clicks, impressions,
                ctr, average_position, created_at, updated_at
            FROM search_console_daily_metrics
            {where_clause}
            ORDER BY website_id, metric_date
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_search_console_metric_date(
        self, website_id: str
    ) -> str | None:
        """Return the latest stored daily metric date for one website."""
        row = self._connection.execute(
            """
            SELECT MAX(metric_date) AS latest_date
            FROM search_console_daily_metrics
            WHERE website_id = ?
            """,
            (website_id,),
        ).fetchone()
        return row["latest_date"] if row and row["latest_date"] else None

    def upsert_search_console_dimension(
        self, *, dimension_type: str, website_id: str, site_url: str,
        period_start: str, period_end: str, clicks: int, impressions: int,
        ctr: float, average_position: float, page_url: str | None = None,
        query: str | None = None,
    ) -> str:
        """Insert or update one page/query period row without duplicates."""
        definitions = {
            "page": ("search_console_pages", ("page_url",), (page_url,)),
            "query": ("search_console_queries", ("query",), (query,)),
            "page_query": (
                "search_console_page_queries", ("page_url", "query"),
                (page_url, query),
            ),
        }
        if dimension_type not in definitions:
            raise ValueError("Ukendt Search Console-dimension.")
        table, columns, values = definitions[dimension_type]
        if any(value is None or value == "" for value in values):
            raise ValueError("Dimensionens nøgle mangler.")
        where = " AND ".join(f"{column} = ?" for column in columns)
        existing = self._connection.execute(
            f"""SELECT id FROM {table}
                WHERE website_id = ? AND {where}
                AND period_start = ? AND period_end = ?""",
            (website_id, *values, period_start, period_end),
        ).fetchone()
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        names = ("website_id", "site_url", "dimension_type", *columns,
                 "period_start", "period_end", "clicks", "impressions",
                 "ctr", "average_position", "imported_at")
        parameters = (
            website_id, site_url, dimension_type, *values, period_start,
            period_end, clicks, impressions, ctr, average_position, timestamp,
        )
        conflict = ", ".join(("website_id", *columns, "period_start", "period_end"))
        with self._connection:
            self._connection.execute(
                f"""INSERT INTO {table} ({", ".join(names)})
                    VALUES ({", ".join("?" for _ in names)})
                    ON CONFLICT({conflict}) DO UPDATE SET
                        site_url = excluded.site_url,
                        clicks = excluded.clicks,
                        impressions = excluded.impressions,
                        ctr = excluded.ctr,
                        average_position = excluded.average_position,
                        imported_at = excluded.imported_at""",
                parameters,
            )
        return "updated" if existing else "created"

    def upsert_search_console_dimensions(
        self, *, dimension_type: str, website_id: str, site_url: str,
        period_start: str, period_end: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Upsert one dimension batch in a single transaction."""
        definitions = {
            "page": ("search_console_pages", ("page_url",)),
            "query": ("search_console_queries", ("query",)),
            "page_query": (
                "search_console_page_queries", ("page_url", "query")
            ),
        }
        if dimension_type not in definitions:
            raise ValueError("Ukendt Search Console-dimension.")
        table, columns = definitions[dimension_type]
        valid_rows = [
            row for row in rows
            if all(row.get(column) not in (None, "") for column in columns)
        ]
        if not valid_rows:
            return {"rows_created": 0, "rows_updated": 0}

        existing_rows = self._connection.execute(
            f"""SELECT {", ".join(columns)}, site_url, clicks, impressions,
                       ctr, average_position FROM {table}
                WHERE website_id = ? AND period_start = ? AND period_end = ?""",
            (website_id, period_start, period_end),
        ).fetchall()
        existing = {
            tuple(row[column] for column in columns): row
            for row in existing_rows
        }
        keys = [
            tuple(row[column] for column in columns)
            for row in valid_rows
        ]
        updated = sum(key in existing for key in keys)
        created = len(keys) - updated
        changed = created + sum(
            key in existing and any((
                str(existing[key]["site_url"]) != str(site_url),
                int(existing[key]["clicks"]) != int(row.get("clicks", 0)),
                int(existing[key]["impressions"])
                != int(row.get("impressions", 0)),
                float(existing[key]["ctr"]) != float(row.get("ctr", 0)),
                float(existing[key]["average_position"])
                != float(row.get("average_position", 0)),
            ))
            for key, row in zip(keys, valid_rows)
        )
        timestamp = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        names = (
            "website_id", "site_url", "dimension_type", *columns,
            "period_start", "period_end", "clicks", "impressions",
            "ctr", "average_position", "imported_at",
        )
        parameters = [
            (
                website_id, site_url, dimension_type,
                *(row[column] for column in columns),
                period_start, period_end, int(row.get("clicks", 0)),
                int(row.get("impressions", 0)), float(row.get("ctr", 0)),
                float(row.get("average_position", 0)), timestamp,
            )
            for row in valid_rows
        ]
        conflict = ", ".join((
            "website_id", *columns, "period_start", "period_end"
        ))
        with self._connection:
            self._connection.executemany(
                f"""INSERT INTO {table} ({", ".join(names)})
                    VALUES ({", ".join("?" for _ in names)})
                    ON CONFLICT({conflict}) DO UPDATE SET
                        site_url = excluded.site_url,
                        clicks = excluded.clicks,
                        impressions = excluded.impressions,
                        ctr = excluded.ctr,
                        average_position = excluded.average_position,
                        imported_at = excluded.imported_at""",
                parameters,
            )
        return {
            "rows_created": created,
            "rows_updated": updated,
            "rows_changed": changed,
            "rows_unchanged": len(valid_rows) - changed,
        }

    def get_search_console_dimensions(
        self, dimension_type: str, *, website_id: str | None = None,
        period_start: str | None = None, period_end: str | None = None,
        page_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return stored page/query period rows through the database boundary."""
        tables = {
            "page": "search_console_pages",
            "query": "search_console_queries",
            "page_query": "search_console_page_queries",
        }
        if dimension_type not in tables:
            raise ValueError("Ukendt Search Console-dimension.")
        conditions, parameters = [], []
        for column, value in (
            ("website_id", website_id), ("period_start", period_start),
            ("period_end", period_end), ("page_url", page_url),
        ):
            if value is not None:
                if column == "page_url" and dimension_type == "query":
                    continue
                conditions.append(f"{column} = ?")
                parameters.append(value)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._connection.execute(
            f"""SELECT * FROM {tables[dimension_type]} {where}
                ORDER BY clicks DESC, impressions DESC""",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_search_console_summary(self) -> dict[str, Any]:
        """Return dashboard totals and the latest metric synchronization."""
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS stored_metrics,
                MAX(updated_at) AS latest_sync
            FROM search_console_daily_metrics
            """
        ).fetchone()
        property_row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS properties,
                MAX(updated_at) AS latest_property_sync
            FROM search_console_properties
            WHERE active = 1 AND website_id IS NOT NULL
            """
        ).fetchone()
        latest_sync = max(
            filter(
                None,
                [row["latest_sync"], property_row["latest_property_sync"]],
            ),
            default=None,
        )
        return {
            "properties": int(property_row["properties"]),
            "stored_metrics": int(row["stored_metrics"]),
            "latest_sync": latest_sync,
        }

    def upsert_search_console_diagnosis(
        self, diagnosis: dict[str, Any]
    ) -> str:
        """Persist one deterministic diagnosis and report the write action."""
        key = (
            str(diagnosis["website_id"]),
            str(diagnosis["period_start"]),
            str(diagnosis["period_end"]),
        )
        existing = self._connection.execute(
            """
            SELECT previous_period_start, previous_period_end, status,
                   data_quality, previous_clicks, current_clicks,
                   click_loss, analysis_json
            FROM search_console_diagnoses
            WHERE website_id = ? AND period_start = ? AND period_end = ?
            """,
            key,
        ).fetchone()
        analysis_json = json.dumps(
            diagnosis, ensure_ascii=False, sort_keys=True
        )
        values = (
            str(diagnosis["previous_period_start"]),
            str(diagnosis["previous_period_end"]),
            str(diagnosis["status"]),
            str(diagnosis["data_quality"]),
            int(diagnosis["previous_clicks"]),
            int(diagnosis["current_clicks"]),
            int(diagnosis["click_loss"]),
            analysis_json,
        )
        if existing and tuple(existing) == values:
            return "unchanged"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO search_console_diagnoses (
                    website_id, period_start, period_end,
                    previous_period_start, previous_period_end, status,
                    data_quality, previous_clicks, current_clicks, click_loss,
                    analysis_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, period_start, period_end) DO UPDATE SET
                    previous_period_start = excluded.previous_period_start,
                    previous_period_end = excluded.previous_period_end,
                    status = excluded.status,
                    data_quality = excluded.data_quality,
                    previous_clicks = excluded.previous_clicks,
                    current_clicks = excluded.current_clicks,
                    click_loss = excluded.click_loss,
                    analysis_json = excluded.analysis_json,
                    updated_at = excluded.updated_at
                """,
                (*key, *values, timestamp, timestamp),
            )
        return "updated" if existing else "created"

    def get_latest_search_console_diagnosis(
        self, website_id: str
    ) -> dict[str, Any] | None:
        """Return the latest saved structured diagnosis for one website."""
        row = self._connection.execute(
            """
            SELECT analysis_json, created_at, updated_at
            FROM search_console_diagnoses
            WHERE website_id = ?
            ORDER BY period_end DESC, id DESC
            LIMIT 1
            """,
            (website_id,),
        ).fetchone()
        if row is None:
            return None
        diagnosis = json.loads(str(row["analysis_json"]))
        diagnosis["created_at"] = row["created_at"]
        diagnosis["updated_at"] = row["updated_at"]
        return diagnosis

    def upsert_plausible_diagnosis(
        self, diagnosis: dict[str, Any]
    ) -> str:
        """Persist one Plausible period comparison idempotently."""
        key = (
            str(diagnosis["website_id"]),
            str(diagnosis["period_start"]),
            str(diagnosis["period_end"]),
        )
        existing = self._connection.execute(
            """
            SELECT previous_period_start, previous_period_end, status,
                   data_quality, previous_visitors, current_visitors,
                   visitor_change, analysis_json
            FROM plausible_diagnoses
            WHERE website_id = ? AND period_start = ? AND period_end = ?
            """,
            key,
        ).fetchone()
        analysis_json = json.dumps(
            diagnosis, ensure_ascii=False, sort_keys=True
        )
        values = (
            str(diagnosis["previous_period_start"]),
            str(diagnosis["previous_period_end"]),
            str(diagnosis["status"]),
            str(diagnosis["data_quality"]),
            int(diagnosis["previous_visitors"]),
            int(diagnosis["current_visitors"]),
            int(diagnosis["visitor_change"]),
            analysis_json,
        )
        if existing and tuple(existing) == values:
            return "unchanged"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO plausible_diagnoses (
                    website_id, period_start, period_end,
                    previous_period_start, previous_period_end, status,
                    data_quality, previous_visitors, current_visitors,
                    visitor_change, analysis_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, period_start, period_end) DO UPDATE SET
                    previous_period_start = excluded.previous_period_start,
                    previous_period_end = excluded.previous_period_end,
                    status = excluded.status,
                    data_quality = excluded.data_quality,
                    previous_visitors = excluded.previous_visitors,
                    current_visitors = excluded.current_visitors,
                    visitor_change = excluded.visitor_change,
                    analysis_json = excluded.analysis_json,
                    updated_at = excluded.updated_at
                """,
                (*key, *values, timestamp, timestamp),
            )
        return "updated" if existing else "created"

    def get_latest_plausible_diagnosis(
        self, website_id: str
    ) -> dict[str, Any] | None:
        """Return the latest saved Plausible diagnosis."""
        row = self._connection.execute(
            """
            SELECT analysis_json, created_at, updated_at
            FROM plausible_diagnoses
            WHERE website_id = ?
            ORDER BY period_end DESC, id DESC
            LIMIT 1
            """,
            (website_id,),
        ).fetchone()
        if row is None:
            return None
        diagnosis = json.loads(str(row["analysis_json"]))
        diagnosis["created_at"] = row["created_at"]
        diagnosis["updated_at"] = row["updated_at"]
        return diagnosis

    def get_search_console_comparisons(
        self,
        reference_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Compare the latest seven complete days with the prior seven."""
        today = reference_date or date.today()
        current_end = today - timedelta(days=1)
        current_start = today - timedelta(days=7)
        previous_end = today - timedelta(days=8)
        previous_start = today - timedelta(days=14)
        rows = self._connection.execute(
            """
            SELECT
                website_id,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN clicks ELSE 0 END) AS current_clicks,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN clicks ELSE 0 END) AS previous_clicks,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN impressions ELSE 0 END) AS current_impressions,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN impressions ELSE 0 END) AS previous_impressions,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN clicks ELSE 0 END) * 1.0 /
                    NULLIF(SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN impressions ELSE 0 END), 0) AS current_ctr,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN clicks ELSE 0 END) * 1.0 /
                    NULLIF(SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN impressions ELSE 0 END), 0) AS previous_ctr,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN average_position * impressions ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN impressions ELSE 0 END), 0)
                    AS current_position,
                SUM(CASE WHEN metric_date BETWEEN ? AND ?
                    THEN average_position * impressions ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN impressions ELSE 0 END), 0)
                    AS previous_position
            FROM search_console_daily_metrics
            WHERE metric_date BETWEEN ? AND ?
            GROUP BY website_id
            """,
            (
                current_start.isoformat(), current_end.isoformat(),
                previous_start.isoformat(), previous_end.isoformat(),
                current_start.isoformat(), current_end.isoformat(),
                previous_start.isoformat(), previous_end.isoformat(),
                current_start.isoformat(), current_end.isoformat(),
                current_start.isoformat(), current_end.isoformat(),
                previous_start.isoformat(), previous_end.isoformat(),
                previous_start.isoformat(), previous_end.isoformat(),
                current_start.isoformat(), current_end.isoformat(),
                current_start.isoformat(), current_end.isoformat(),
                previous_start.isoformat(), previous_end.isoformat(),
                previous_start.isoformat(), previous_end.isoformat(),
                previous_start.isoformat(), current_end.isoformat(),
            ),
        ).fetchall()
        return [
            {
                **dict(row),
                "click_change_percent": self._percent_change(
                    row["current_clicks"], row["previous_clicks"]
                ),
                "impression_change_percent": self._percent_change(
                    row["current_impressions"], row["previous_impressions"]
                ),
                "ctr_change_points": self._difference(
                    row["current_ctr"], row["previous_ctr"]
                ),
                "position_difference": self._difference(
                    row["current_position"], row["previous_position"]
                ),
            }
            for row in rows
        ]

    def get_click_change(
        self,
        website_id: str,
        reference_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Return click percentage changes for 7, 28, and 90 days."""
        return self._get_metric_changes(
            website_id,
            metric="clicks",
            change_type="percent",
            reference_date=reference_date,
        )

    def get_impression_change(
        self,
        website_id: str,
        reference_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Return impression percentage changes for 7, 28, and 90 days."""
        return self._get_metric_changes(
            website_id,
            metric="impressions",
            change_type="percent",
            reference_date=reference_date,
        )

    def get_position_change(
        self,
        website_id: str,
        reference_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Return weighted average-position differences for all periods."""
        return self._get_metric_changes(
            website_id,
            metric="average_position",
            change_type="position",
            reference_date=reference_date,
        )

    def get_ctr_change(
        self,
        website_id: str,
        reference_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Return CTR changes in percentage points for all periods."""
        return self._get_metric_changes(
            website_id,
            metric="ctr",
            change_type="ctr",
            reference_date=reference_date,
        )

    def _get_metric_changes(
        self,
        website_id: str,
        *,
        metric: str,
        change_type: str,
        reference_date: date | None,
    ) -> list[dict[str, Any]]:
        allowed_metrics = {
            "clicks",
            "impressions",
            "average_position",
            "ctr",
        }
        if metric not in allowed_metrics:
            raise ValueError("Ukendt Search Console-metrik.")
        today = reference_date or date.today()
        results: list[dict[str, Any]] = []
        for days in (7, 28, 90):
            current_start = today - timedelta(days=days)
            current_end = today - timedelta(days=1)
            previous_start = today - timedelta(days=days * 2)
            previous_end = today - timedelta(days=days + 1)
            row = self._connection.execute(
                """
                SELECT
                    COUNT(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN 1 END) AS current_rows,
                    COUNT(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN 1 END) AS previous_rows,
                    SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN clicks ELSE 0 END) AS current_clicks,
                    SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN clicks ELSE 0 END) AS previous_clicks,
                    SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN impressions ELSE 0 END) AS current_impressions,
                    SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN impressions ELSE 0 END) AS previous_impressions,
                    SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN average_position * impressions ELSE 0 END) /
                        NULLIF(SUM(CASE WHEN metric_date BETWEEN ? AND ?
                            THEN impressions ELSE 0 END), 0)
                        AS current_position,
                    SUM(CASE WHEN metric_date BETWEEN ? AND ?
                        THEN average_position * impressions ELSE 0 END) /
                        NULLIF(SUM(CASE WHEN metric_date BETWEEN ? AND ?
                            THEN impressions ELSE 0 END), 0)
                        AS previous_position
                FROM search_console_daily_metrics
                WHERE website_id = ? AND metric_date BETWEEN ? AND ?
                """,
                (
                    current_start.isoformat(),
                    current_end.isoformat(),
                    previous_start.isoformat(),
                    previous_end.isoformat(),
                    current_start.isoformat(),
                    current_end.isoformat(),
                    previous_start.isoformat(),
                    previous_end.isoformat(),
                    current_start.isoformat(),
                    current_end.isoformat(),
                    previous_start.isoformat(),
                    previous_end.isoformat(),
                    current_start.isoformat(),
                    current_end.isoformat(),
                    current_start.isoformat(),
                    current_end.isoformat(),
                    previous_start.isoformat(),
                    previous_end.isoformat(),
                    previous_start.isoformat(),
                    previous_end.isoformat(),
                    website_id,
                    previous_start.isoformat(),
                    current_end.isoformat(),
                ),
            ).fetchone()
            current: float | None = None
            previous: float | None = None
            if row["current_rows"] and row["previous_rows"]:
                if metric == "clicks":
                    current = row["current_clicks"]
                    previous = row["previous_clicks"]
                elif metric == "impressions":
                    current = row["current_impressions"]
                    previous = row["previous_impressions"]
                elif metric == "ctr":
                    current = (
                        row["current_clicks"] / row["current_impressions"]
                        if row["current_impressions"]
                        else None
                    )
                    previous = (
                        row["previous_clicks"] / row["previous_impressions"]
                        if row["previous_impressions"]
                        else None
                    )
                else:
                    current = row["current_position"]
                    previous = row["previous_position"]
            change: float | None = None
            if current is not None and previous is not None:
                if change_type == "percent":
                    change = self._percent_change(current, previous)
                elif change_type == "ctr":
                    change = (current - previous) * 100
                else:
                    change = current - previous
            results.append(
                {
                    "period": f"{days}d",
                    "current": current,
                    "previous": previous,
                    "change": change,
                }
            )
        return results

    def get_search_console_website_ids(self) -> list[str]:
        """Return websites with stored Search Console metrics."""
        rows = self._connection.execute(
            """
            SELECT DISTINCT website_id
            FROM search_console_daily_metrics
            ORDER BY website_id
            """
        ).fetchall()
        return [str(row["website_id"]) for row in rows]

    def upsert_seo_health(
        self,
        *,
        website_id: str,
        analysis_date: str,
        period: str,
        score: float,
        trend: str,
        click_change: float | None,
        impression_change: float | None,
        ctr_change: float | None,
        position_change: float | None,
    ) -> str:
        """Insert or update one SEO health snapshot."""
        existing = self._connection.execute(
            """
            SELECT score, trend, click_change, impression_change,
                   ctr_change, position_change
            FROM seo_health_history
            WHERE website_id = ? AND date = ? AND period = ?
            """,
            (website_id, analysis_date, period),
        ).fetchone()
        values = (
            float(score), str(trend), click_change, impression_change,
            ctr_change, position_change,
        )
        if existing and (
            float(existing["score"]), str(existing["trend"]),
            existing["click_change"], existing["impression_change"],
            existing["ctr_change"], existing["position_change"],
        ) == values:
            return "unchanged"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO seo_health_history (
                    website_id, date, period, score, trend, click_change,
                    impression_change, ctr_change, position_change,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, date, period) DO UPDATE SET
                    score = excluded.score,
                    trend = excluded.trend,
                    click_change = excluded.click_change,
                    impression_change = excluded.impression_change,
                    ctr_change = excluded.ctr_change,
                    position_change = excluded.position_change,
                    updated_at = excluded.updated_at
                """,
                (
                    website_id,
                    analysis_date,
                    period,
                    score,
                    trend,
                    click_change,
                    impression_change,
                    ctr_change,
                    position_change,
                    timestamp,
                    timestamp,
                ),
            )
        return "updated" if existing else "created"

    def get_seo_health_history(
        self,
        website_id: str | None = None,
        period: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return SEO health snapshots with optional filters."""
        conditions: list[str] = []
        parameters: list[str] = []
        if website_id:
            conditions.append("website_id = ?")
            parameters.append(website_id)
        if period:
            conditions.append("period = ?")
            parameters.append(period)
        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM seo_health_history
            {where_clause}
            ORDER BY date DESC, website_id, period
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_seo_health_summary(self, period: str = "28d") -> dict[str, int]:
        """Count trends from the latest analyzed date for one period."""
        rows = self._connection.execute(
            """
            SELECT h.trend, COUNT(*) AS total
            FROM seo_health_history h
            JOIN websites w ON w.website = h.website_id
            WHERE h.period = ?
              AND w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
              AND h.date = (
                  SELECT MAX(date)
                  FROM seo_health_history
                  WHERE period = ?
              )
            GROUP BY h.trend
            """,
            (period, period),
        ).fetchall()
        summary = {
            "growing": 0,
            "stable": 0,
            "declining": 0,
            "critical": 0,
        }
        for row in rows:
            summary[row["trend"]] = int(row["total"])
        return summary

    def get_lowest_seo_scores(
        self,
        limit: int = 5,
        period: str = "28d",
    ) -> list[dict[str, Any]]:
        """Return the lowest scores from the latest analysis date."""
        rows = self._connection.execute(
            """
            SELECT h.website_id, h.date, h.period, h.score, h.trend
            FROM seo_health_history h
            JOIN websites w ON w.website = h.website_id
            WHERE h.period = ?
              AND w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
              AND h.date = (
                  SELECT MAX(date)
                  FROM seo_health_history
                  WHERE period = ?
              )
            ORDER BY h.score ASC, h.website_id
            LIMIT ?
            """,
            (period, period, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_seo_recommendation(
        self,
        *,
        website_id: str,
        analysis_date: str,
        seo_score: float,
        trend: str,
        reason: str,
        recommendation: str,
        priority: str,
        project_id: int | None,
        status: str,
    ) -> str:
        """Insert or update one daily SEO Manager recommendation."""
        existing = self._connection.execute(
            """
            SELECT id FROM seo_recommendations
            WHERE website_id = ? AND analysis_date = ?
            """,
            (website_id, analysis_date),
        ).fetchone()
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO seo_recommendations (
                    website_id, analysis_date, seo_score, trend, reason,
                    recommendation, priority, project_id, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, analysis_date) DO UPDATE SET
                    seo_score = excluded.seo_score,
                    trend = excluded.trend,
                    reason = excluded.reason,
                    recommendation = excluded.recommendation,
                    priority = excluded.priority,
                    project_id = excluded.project_id,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    website_id,
                    analysis_date,
                    seo_score,
                    trend,
                    reason,
                    recommendation,
                    priority,
                    project_id,
                    status,
                    timestamp,
                    timestamp,
                ),
            )
        return "updated" if existing else "created"

    def get_seo_recommendations(
        self,
        website_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return SEO recommendations ordered by urgency and score."""
        query = "SELECT * FROM seo_recommendations"
        parameters: tuple[Any, ...] = ()
        if website_id:
            query += " WHERE website_id = ?"
            parameters = (website_id,)
        query += """
            ORDER BY
                CASE priority
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                seo_score,
                website_id
        """
        rows = self._connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _percent_change(current: float, previous: float) -> float | None:
        if previous == 0:
            return 0.0 if current == 0 else None
        return ((current - previous) / previous) * 100

    @staticmethod
    def _difference(
        current: float | None,
        previous: float | None,
    ) -> float | None:
        if current is None or previous is None:
            return None
        return current - previous

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
                measurement_method TEXT NOT NULL DEFAULT '',
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
        task_columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(tasks)")
        }
        if "measurement_method" not in task_columns:
            self._connection.execute(
                """
                ALTER TABLE tasks
                ADD COLUMN measurement_method TEXT NOT NULL DEFAULT ''
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

    def get_project_by_website_and_title(
        self,
        website_id: str,
        title: str,
    ) -> dict[str, Any] | None:
        """Return one project by its stable website/title identity."""
        row = self._connection.execute(
            """
            SELECT * FROM projects
            WHERE website_id = ? AND title = ?
            """,
            (website_id, title),
        ).fetchone()
        return dict(row) if row else None

    def update_project_record(
        self,
        project_id: int,
        *,
        description: str,
        status: str,
        priority: str,
        expected_effect: str,
    ) -> None:
        """Update the mutable planning fields of a project."""
        with self._connection:
            self._connection.execute(
                """
                UPDATE projects
                SET description = ?,
                    status = ?,
                    priority = ?,
                    expected_effect = ?,
                    completed_at = CASE
                        WHEN ? IN ('completed', 'cancelled')
                        THEN completed_at
                        ELSE NULL
                    END
                WHERE id = ?
                """,
                (
                    description,
                    status,
                    priority,
                    expected_effect,
                    status,
                    project_id,
                ),
            )

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
                    measurement_method, priority_score, status,
                    depends_on_task_id, created_at, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    values.get("measurement_method", ""),
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

    def get_projects(
        self, website_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return projects, optionally limited to one website."""
        query = "SELECT * FROM projects"
        parameters: tuple[Any, ...] = ()
        if website_id is not None:
            query += " WHERE website_id = ?"
            parameters = (website_id,)
        query += " ORDER BY created_at DESC, id DESC"
        rows = self._connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

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

    def set_website_active(self, website: str, active: bool) -> bool:
        """Toggle one existing website without changing its identity or history."""
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE websites
                SET active = ?, status = ?
                WHERE website = ?
                """,
                (int(active), "active" if active else "inactive", website),
            )
        return cursor.rowcount == 1

    def set_active_website_ids(self, active_website_ids: set[str]) -> int:
        """Replace the active set for manageable websites in one transaction."""
        selected = {str(value).strip() for value in active_website_ids}
        rows = self._connection.execute(
            """
            SELECT website, active
            FROM websites
            WHERE status IN ('active', 'inactive')
            """
        ).fetchall()
        changes = [
            (website, website in selected)
            for website, current in (
                (str(row["website"]), bool(row["active"])) for row in rows
            )
            if current != (website in selected)
        ]
        if not changes:
            return 0
        with self._connection:
            for website, active in changes:
                self._connection.execute(
                    """
                    UPDATE websites
                    SET active = ?, status = ?
                    WHERE website = ?
                    """,
                    (
                        int(active),
                        "active" if active else "inactive",
                        website,
                    ),
                )
        return len(changes)

    def get_active_website_ids(self) -> list[str]:
        """Return website IDs eligible for future processing."""
        rows = self._connection.execute(
            """
            SELECT website
            FROM websites
            WHERE active = 1
              AND status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
            ORDER BY website
            """
        ).fetchall()
        return [str(row["website"]) for row in rows]

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

    def get_latest_partner_ads_sale_date(self) -> date | None:
        """Return the latest valid Partner Ads sale date, never local creation time."""
        rows = self._connection.execute(
            "SELECT dato FROM registered_sales WHERE dato <> ''"
        ).fetchall()
        parsed = [
            value
            for row in rows
            if (value := self._parse_partner_ads_date(row["dato"])) is not None
        ]
        return max(parsed) if parsed else None

    def upsert_partner_ads_sale(
        self, sale: dict[str, str], created_at: str | None = None
    ) -> str:
        """Insert or update a sale by Partner Ads' stable ``kombiid``."""
        kombiid = self._get_kombiid(sale)
        existing = self._connection.execute(
            "SELECT * FROM registered_sales WHERE kombiid = ?", (kombiid,)
        ).fetchone()
        timestamp = created_at or datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        values = {
            "programid": sale.get("programid", ""),
            "program": sale.get("program", ""),
            "dato": sale.get("dato", ""),
            "tidspunkt": sale.get("tidspunkt", ""),
            "ordrenr": sale.get("ordrenr", ""),
            "omsaetning": self._as_number(sale.get("omsaetning", "0")),
            "provision": self._as_number(sale.get("provision", "0")),
            "url": sale.get("url", ""),
            "valuta": sale.get("valuta", ""),
            "status": sale.get("status", ""),
            "approval_status": sale.get(
                "approval_status", sale.get("godkendelsesstatus", "")
            ),
        }
        if existing is None:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO registered_sales (
                        kombiid, programid, program, dato, tidspunkt, ordrenr,
                        omsaetning, provision, url, valuta, created_at,
                        status, approval_status, telegram_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        kombiid,
                        values["programid"], values["program"], values["dato"],
                        values["tidspunkt"], values["ordrenr"],
                        values["omsaetning"], values["provision"], values["url"],
                        values["valuta"], timestamp, values["status"],
                        values["approval_status"],
                    ),
                )
            return "created"
        changed = any(
            (
                float(existing[key] or 0) != float(value)
                if key in {"omsaetning", "provision"}
                else str(existing[key] if existing[key] is not None else "")
                != str(value)
            )
            for key, value in values.items()
        )
        if not changed:
            return "unchanged"
        with self._connection:
            self._connection.execute(
                """
                UPDATE registered_sales SET
                    programid = ?, program = ?, dato = ?, tidspunkt = ?,
                    ordrenr = ?, omsaetning = ?, provision = ?, url = ?,
                    valuta = ?, status = ?, approval_status = ?
                WHERE kombiid = ?
                """,
                (*values.values(), kombiid),
            )
        return "updated"

    def get_partner_ads_notification_status(self, kombiid: str) -> str | None:
        row = self._connection.execute(
            "SELECT telegram_status FROM registered_sales WHERE kombiid = ?",
            (kombiid,),
        ).fetchone()
        return None if row is None else str(row["telegram_status"])

    def set_partner_ads_notification_status(
        self, kombiid: str, status: str
    ) -> None:
        """Persist the terminal Telegram outcome for one registered sale."""
        if status not in {"sent", "failed", "skipped"}:
            raise ValueError("Ugyldig Telegram-status.")
        with self._connection:
            self._connection.execute(
                """
                UPDATE registered_sales
                SET telegram_status = ?, telegram_attempted_at = ?
                WHERE kombiid = ?
                """,
                (
                    status,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    kombiid,
                ),
            )

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

    def get_website_intelligence_source(
        self,
        website_id: str,
    ) -> dict[str, Any] | None:
        """Return all stored inputs needed to build one website profile."""
        website = self.get_website(website_id)
        if website is None:
            return None
        search = self._connection.execute(
            """
            SELECT
                COALESCE(SUM(clicks), 0) AS clicks,
                COALESCE(SUM(impressions), 0) AS impressions,
                COALESCE(SUM(clicks) * 1.0 /
                    NULLIF(SUM(impressions), 0), 0) AS ctr,
                SUM(average_position * impressions) /
                    NULLIF(SUM(impressions), 0) AS average_position
            FROM (
                SELECT clicks, impressions, average_position
                FROM search_console_daily_metrics
                WHERE website_id = ?
                ORDER BY metric_date DESC
                LIMIT 28
            )
            """,
            (website_id,),
        ).fetchone()
        seo = self._connection.execute(
            """
            SELECT score, trend, click_change, impression_change,
                   ctr_change, position_change, date
            FROM seo_health_history
            WHERE website_id = ? AND period = '28d'
            ORDER BY date DESC
            LIMIT 1
            """,
            (website_id,),
        ).fetchone()
        project_rows = self._connection.execute(
            """
            SELECT id, title, status, priority, expected_effect, created_at
            FROM projects
            WHERE website_id = ?
              AND status NOT IN ('completed', 'cancelled')
            ORDER BY id
            """,
            (website_id,),
        ).fetchall()
        task_rows = self._connection.execute(
            """
            SELECT
                t.id, p.title AS project, sp.title AS subproject,
                t.title, t.assigned_agent, t.estimated_minutes,
                t.priority_score, t.status, t.expected_effect,
                t.measurement_method
            FROM tasks t
            JOIN subprojects sp ON sp.id = t.subproject_id
            JOIN projects p ON p.id = sp.project_id
            WHERE t.website_id = ?
              AND t.status NOT IN ('completed', 'cancelled')
            ORDER BY t.priority_score DESC, t.id
            """,
            (website_id,),
        ).fetchall()
        sales = []
        for row in self._connection.execute(
            """
            SELECT dato, tidspunkt, omsaetning, provision, url, created_at
            FROM registered_sales
            ORDER BY created_at DESC
            """
        ).fetchall():
            sale = dict(row)
            if self._normalize_website_from_url(sale["url"]) == website_id:
                sales.append(sale)
        return {
            "website": website,
            "search_console": dict(search),
            "seo_health": dict(seo) if seo else None,
            "partner_ads": {
                "sales": sales,
                "sales_count": len(sales),
                "revenue": sum(
                    Decimal(str(item["omsaetning"])) for item in sales
                ),
                "commission": sum(
                    Decimal(str(item["provision"])) for item in sales
                ),
            },
            "active_projects": [dict(row) for row in project_rows],
            "active_tasks": [dict(row) for row in task_rows],
        }

    def upsert_website_profile(self, profile: dict[str, Any]) -> str:
        """Insert or update one current website intelligence profile."""
        existing = self._connection.execute(
            "SELECT * FROM website_profiles WHERE website_id = ?",
            (profile["website_id"],),
        ).fetchone()
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        serialized = {
            "strong_areas_json": json.dumps(
                profile["strong_areas"],
                ensure_ascii=False,
                sort_keys=True,
            ),
            "weak_areas_json": json.dumps(
                profile["weak_areas"],
                ensure_ascii=False,
                sort_keys=True,
            ),
            "ai_recommendations_json": json.dumps(
                profile["ai_recommendations"],
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
        mutable_fields = (
            "display_name",
            "status",
            "cms",
            "theme",
            "monetization",
            "niche",
            "website_health",
        )
        if existing:
            unchanged = all(
                existing[field] == profile[field] for field in mutable_fields
            ) and all(
                existing[field] == value
                for field, value in serialized.items()
            )
            if unchanged:
                return "unchanged"
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO website_profiles (
                    website_id, display_name, status, cms, theme,
                    monetization, niche, website_health,
                    strong_areas_json, weak_areas_json,
                    ai_recommendations_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    status = excluded.status,
                    cms = excluded.cms,
                    theme = excluded.theme,
                    monetization = excluded.monetization,
                    niche = excluded.niche,
                    website_health = excluded.website_health,
                    strong_areas_json = excluded.strong_areas_json,
                    weak_areas_json = excluded.weak_areas_json,
                    ai_recommendations_json =
                        excluded.ai_recommendations_json,
                    updated_at = excluded.updated_at
                """,
                (
                    profile["website_id"],
                    profile["display_name"],
                    profile["status"],
                    profile["cms"],
                    profile["theme"],
                    profile["monetization"],
                    profile["niche"],
                    profile["website_health"],
                    serialized["strong_areas_json"],
                    serialized["weak_areas_json"],
                    serialized["ai_recommendations_json"],
                    timestamp,
                    timestamp,
                ),
            )
        return "updated" if existing else "created"

    def upsert_website_statistics(
        self,
        statistics: dict[str, Any],
    ) -> str:
        """Insert or update one daily website intelligence snapshot."""
        existing = self._connection.execute(
            """
            SELECT * FROM website_statistics
            WHERE website_id = ? AND statistic_date = ?
            """,
            (statistics["website_id"], statistics["statistic_date"]),
        ).fetchone()
        comparable = (
            "search_clicks", "search_impressions", "search_ctr",
            "average_position", "sales_count", "revenue", "commission",
            "seo_score", "seo_trend", "active_projects", "active_tasks",
            "website_health",
        )
        if existing and all(
            existing[field] == statistics[field] for field in comparable
        ):
            return "unchanged"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO website_statistics (
                    website_id, statistic_date, search_clicks,
                    search_impressions, search_ctr, average_position,
                    sales_count, revenue, commission, seo_score, seo_trend,
                    active_projects, active_tasks, website_health,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, statistic_date) DO UPDATE SET
                    search_clicks = excluded.search_clicks,
                    search_impressions = excluded.search_impressions,
                    search_ctr = excluded.search_ctr,
                    average_position = excluded.average_position,
                    sales_count = excluded.sales_count,
                    revenue = excluded.revenue,
                    commission = excluded.commission,
                    seo_score = excluded.seo_score,
                    seo_trend = excluded.seo_trend,
                    active_projects = excluded.active_projects,
                    active_tasks = excluded.active_tasks,
                    website_health = excluded.website_health,
                    updated_at = excluded.updated_at
                """,
                (
                    statistics["website_id"],
                    statistics["statistic_date"],
                    statistics["search_clicks"],
                    statistics["search_impressions"],
                    statistics["search_ctr"],
                    statistics["average_position"],
                    statistics["sales_count"],
                    statistics["revenue"],
                    statistics["commission"],
                    statistics["seo_score"],
                    statistics["seo_trend"],
                    statistics["active_projects"],
                    statistics["active_tasks"],
                    statistics["website_health"],
                    timestamp,
                    timestamp,
                ),
            )
        return "updated" if existing else "created"

    def replace_website_categories(
        self,
        website_id: str,
        categories: list[dict[str, Any]],
    ) -> None:
        """Replace one website's ranked intelligence categories."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                "DELETE FROM website_categories WHERE website_id = ?",
                (website_id,),
            )
            self._connection.executemany(
                """
                INSERT INTO website_categories (
                    website_id, category, category_type, rank, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        website_id,
                        item["category"],
                        item["category_type"],
                        item["rank"],
                        timestamp,
                    )
                    for item in categories
                ],
            )

    def save_website_history(
        self,
        website_id: str,
        history_date: str,
        snapshot: dict[str, Any],
    ) -> str:
        """Persist a history row only when the profile snapshot changed."""
        latest = self._connection.execute(
            """
            SELECT snapshot_json FROM website_history
            WHERE website_id = ?
            ORDER BY history_date DESC, id DESC
            LIMIT 1
            """,
            (website_id,),
        ).fetchone()
        previous = json.loads(latest["snapshot_json"]) if latest else {}
        changed_fields = sorted(
            key
            for key in set(previous) | set(snapshot)
            if previous.get(key) != snapshot.get(key)
        )
        if not changed_fields:
            return "unchanged"
        existing_date = self._connection.execute(
            """
            SELECT id FROM website_history
            WHERE website_id = ? AND history_date = ?
            """,
            (website_id, history_date),
        ).fetchone()
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        snapshot_json = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO website_history (
                    website_id, history_date, changed_fields_json,
                    snapshot_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(website_id, history_date) DO UPDATE SET
                    changed_fields_json = excluded.changed_fields_json,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (
                    website_id,
                    history_date,
                    json.dumps(changed_fields, ensure_ascii=False),
                    snapshot_json,
                    timestamp,
                    timestamp,
                ),
            )
        return "updated" if existing_date else "created"

    def get_website_profiles(self) -> list[dict[str, Any]]:
        """Return current website profiles for dashboard selection."""
        rows = self._connection.execute(
            """
            SELECT
                website_id, display_name, status, niche, website_health,
                updated_at
            FROM website_profiles
            ORDER BY display_name, website_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_website_profile_detail(
        self,
        website_id: str,
    ) -> dict[str, Any] | None:
        """Return a complete read-only website profile dashboard payload."""
        profile_row = self._connection.execute(
            "SELECT * FROM website_profiles WHERE website_id = ?",
            (website_id,),
        ).fetchone()
        if profile_row is None:
            return None
        profile = dict(profile_row)
        for key in (
            "strong_areas_json",
            "weak_areas_json",
            "ai_recommendations_json",
        ):
            profile[key.removesuffix("_json")] = json.loads(profile.pop(key))
        statistics = self._connection.execute(
            """
            SELECT * FROM website_statistics
            WHERE website_id = ?
            ORDER BY statistic_date DESC
            LIMIT 1
            """,
            (website_id,),
        ).fetchone()
        categories = self._connection.execute(
            """
            SELECT category, category_type, rank
            FROM website_categories
            WHERE website_id = ?
            ORDER BY rank, category
            """,
            (website_id,),
        ).fetchall()
        history_rows = self._connection.execute(
            """
            SELECT history_date, changed_fields_json, snapshot_json, updated_at
            FROM website_history
            WHERE website_id = ?
            ORDER BY history_date DESC, id DESC
            LIMIT 20
            """,
            (website_id,),
        ).fetchall()
        projects = self._connection.execute(
            """
            SELECT id, title, status, priority, expected_effect, created_at
            FROM projects
            WHERE website_id = ?
              AND status NOT IN ('completed', 'cancelled')
            ORDER BY id
            """,
            (website_id,),
        ).fetchall()
        tasks = self._connection.execute(
            """
            SELECT
                t.id, p.title AS project, t.title,
                t.assigned_agent, t.priority_score,
                t.estimated_minutes, t.status
            FROM tasks t
            JOIN subprojects sp ON sp.id = t.subproject_id
            JOIN projects p ON p.id = sp.project_id
            WHERE t.website_id = ?
              AND t.status NOT IN ('completed', 'cancelled')
            ORDER BY t.priority_score DESC, t.id
            """,
            (website_id,),
        ).fetchall()
        return {
            "profile": profile,
            "statistics": dict(statistics) if statistics else None,
            "categories": [dict(row) for row in categories],
            "history": [
                {
                    **dict(row),
                    "changed_fields": json.loads(
                        row["changed_fields_json"]
                    ),
                    "snapshot": json.loads(row["snapshot_json"]),
                }
                for row in history_rows
            ],
            "active_projects": [dict(row) for row in projects],
            "active_tasks": [dict(row) for row in tasks],
        }

    def save_ai_analysis(self, analysis: dict[str, Any]) -> int:
        """Persist one validated AI analysis or sanitized failure report."""
        timestamp = analysis.get("created_at") or datetime.now().astimezone(
        ).isoformat(timespec="seconds")
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO ai_analysis (
                    website_id, project_id, task_id, analysis_type,
                    summary, problem, root_cause, recommended_action,
                    priority, confidence, expected_effect, reasoning_json,
                    required_agents_json, suggested_tasks_json, model,
                    prompt_tokens, completion_tokens, latency_ms, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis.get("website_id"),
                    analysis.get("project_id"),
                    analysis.get("task_id"),
                    analysis["analysis_type"],
                    analysis["summary"],
                    analysis["problem"],
                    analysis["root_cause"],
                    analysis["recommended_action"],
                    analysis["priority"],
                    int(analysis["confidence"]),
                    analysis["expected_effect"],
                    json.dumps(
                        analysis["reasoning"],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        analysis["required_agents"],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        analysis["suggested_tasks"],
                        ensure_ascii=False,
                    ),
                    analysis["model"],
                    int(analysis["prompt_tokens"]),
                    int(analysis["completion_tokens"]),
                    int(analysis["latency_ms"]),
                    timestamp,
                ),
            )
        return int(cursor.lastrowid)

    def get_latest_analysis(
        self,
        *,
        website_id: str | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
        analysis_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest analysis matching the supplied scope."""
        filters: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("website_id", website_id),
            ("project_id", project_id),
            ("task_id", task_id),
            ("analysis_type", analysis_type),
        ):
            if value is not None:
                filters.append(f"{column} = ?")
                parameters.append(value)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        row = self._connection.execute(
            f"""
            SELECT * FROM ai_analysis
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            parameters,
        ).fetchone()
        return self._ai_analysis_row(row) if row else None

    def get_analysis_history(
        self,
        *,
        website_id: str | None = None,
        project_id: int | None = None,
        task_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent analysis reports for dashboard and history views."""
        filters: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("website_id", website_id),
            ("project_id", project_id),
            ("task_id", task_id),
        ):
            if value is not None:
                filters.append(f"{column} = ?")
                parameters.append(value)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        parameters.append(max(1, int(limit)))
        rows = self._connection.execute(
            f"""
            SELECT * FROM ai_analysis
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [self._ai_analysis_row(row) for row in rows]

    def get_ai_analysis_status(self) -> dict[str, Any]:
        """Return aggregate AI Analyst metrics for the main dashboard."""
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                AVG(confidence) AS average_confidence,
                MAX(created_at) AS latest_analysis
            FROM ai_analysis
            """
        ).fetchone()
        return {
            "total": int(row["total"]),
            "average_confidence": round(
                float(row["average_confidence"] or 0),
                1,
            ),
            "latest_analysis": row["latest_analysis"],
        }

    @staticmethod
    def _ai_analysis_row(row: sqlite3.Row) -> dict[str, Any]:
        analysis = dict(row)
        for field in (
            "reasoning_json",
            "required_agents_json",
            "suggested_tasks_json",
        ):
            analysis[field.removesuffix("_json")] = json.loads(
                analysis.pop(field)
            )
        return analysis

    @staticmethod
    def _normalize_website_from_url(value: str) -> str:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        domain = (parsed.hostname or "").lower().rstrip(".")
        return domain[4:] if domain.startswith("www.") else domain

    def set_system_status(self, component: str, is_ok: bool) -> None:
        """Persist one component's latest known health state."""
        allowed = {
            "partner_ads",
            "search_console",
            "agent_orchestrator",
            "knowledge_engine",
            "openai",
        }
        if component not in allowed:
            raise ValueError(f"Ukendt systemkomponent: {component}")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (f"system_status:{component}", "ok" if is_ok else "error"),
            )

    def set_integration_state(
        self, integration: str, state: dict[str, Any] | None
    ) -> None:
        """Persist non-secret metadata for one external integration."""
        key = f"integration_state:{integration}"
        with self._connection:
            if state is None:
                self._connection.execute(
                    "DELETE FROM app_state WHERE key = ?", (key,)
                )
            else:
                self._connection.execute(
                    """
                    INSERT INTO app_state (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, json.dumps(state, ensure_ascii=False)),
                )

    def get_integration_state(
        self, integration: str
    ) -> dict[str, Any] | None:
        """Return saved non-secret metadata for one external integration."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (f"integration_state:{integration}",),
        ).fetchone()
        if not row:
            return None
        try:
            state = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return None
        return state if isinstance(state, dict) else None

    def set_search_console_dimension_state(
        self, site_url: str, state: dict[str, Any]
    ) -> None:
        """Persist non-secret dimensions import timestamps for one property."""
        key = f"search_console_dimensions:{site_url}"
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json.dumps(state, ensure_ascii=False)),
            )

    def get_search_console_dimension_state(
        self, site_url: str
    ) -> dict[str, Any]:
        """Return persisted attempt, success, and failure metadata."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (f"search_console_dimensions:{site_url}",),
        ).fetchone()
        if not row:
            return {}
        try:
            state = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return {}
        return state if isinstance(state, dict) else {}

    def set_derived_refresh_state(
        self, step: str, state: dict[str, Any]
    ) -> None:
        """Persist the latest derived calculation basis and outcome."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (
                    f"derived_refresh:{step}",
                    json.dumps(state, ensure_ascii=False, default=str),
                ),
            )

    def set_navigation_group_state(self, group: str, is_open: bool) -> None:
        """Persist the local user's sidebar group preference."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (f"navigation_group:{group}", "open" if is_open else "closed"),
            )

    def get_navigation_group_state(self, group: str) -> bool | None:
        """Return a saved sidebar preference, if one exists."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (f"navigation_group:{group}",),
        ).fetchone()
        if not row:
            return None
        return row["value"] == "open"

    def set_app_setting(self, name: str, value: bool) -> None:
        """Persist one boolean application setting in app_state."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (f"setting:{name}", "1" if value else "0"),
            )

    def get_app_setting(self, name: str, default: bool = False) -> bool:
        """Return one boolean application setting."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (f"setting:{name}",),
        ).fetchone()
        return default if not row else row["value"] == "1"

    def save_feature_run(
        self,
        *,
        feature_name: str,
        status: str,
        started_at: str,
        completed_at: str,
        records_processed: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> int:
        """Persist one complete, sanitized operational feature run."""
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO feature_runs (
                    feature_name, status, started_at, completed_at,
                    records_processed, records_created, records_updated,
                    error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feature_name, status, started_at, completed_at,
                    int(records_processed), int(records_created),
                    int(records_updated), error_type,
                    (error_message or "")[:300] or None,
                ),
            )
        return int(cursor.lastrowid)

    def get_feature_runs(self) -> dict[str, dict[str, Any]]:
        """Return the latest run for each operational feature."""
        rows = self._connection.execute(
            """
            SELECT * FROM feature_runs AS run
            WHERE id = (
                SELECT MAX(id) FROM feature_runs
                WHERE feature_name = run.feature_name
            )
            """
        ).fetchall()
        return {row["feature_name"]: dict(row) for row in rows}

    def save_data_refresh_result(self, result: dict[str, Any]) -> None:
        """Persist the latest complete refresh summary across UI restarts."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (
                    "data_refresh:last_result",
                    json.dumps(result, ensure_ascii=False),
                ),
            )

    def get_last_data_refresh_result(self) -> dict[str, Any] | None:
        """Return the latest complete refresh summary, if available."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            ("data_refresh:last_result",),
        ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def save_integration_retry_result(
        self, result: dict[str, Any],
        previous_refresh: dict[str, Any] | None = None,
    ) -> None:
        """Persist latest retry plus a bounded operational history."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            ("integration_retry:history",),
        ).fetchone()
        try:
            history = json.loads(row["value"]) if row else []
        except (TypeError, json.JSONDecodeError):
            history = []
        if not isinstance(history, list):
            history = []
        history_entry = {
            "previous_refresh": previous_refresh,
            "retry": result,
        }
        history = [*history[-49:], history_entry]
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (
                    (
                        "integration_retry:last_result",
                        json.dumps(result, ensure_ascii=False),
                    ),
                    (
                        "integration_retry:history",
                        json.dumps(history, ensure_ascii=False),
                    ),
                ),
            )

    def set_system_health(
        self, component: str, health: dict[str, Any]
    ) -> None:
        """Persist a detailed service health result for dashboard display."""
        if component not in {"knowledge_engine", "openai"}:
            raise ValueError(f"Ukendt runtime-service: {component}")
        payload = {
            "is_ok": bool(health["is_ok"]),
            "detail": str(health["detail"]),
            "checked_at": str(health["checked_at"]),
            "error_type": health.get("error_type"),
        }
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (
                    f"system_health:{component}",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        self.set_system_status(component, payload["is_ok"])

    def get_dashboard_system_health(self) -> dict[str, dict[str, Any]]:
        """Return detailed statuses with timestamp and short explanation."""
        statuses = self.get_dashboard_system_status()
        rows = self._connection.execute(
            """
            SELECT key, value FROM app_state
            WHERE key LIKE 'system_health:%'
            """
        ).fetchall()
        details = {}
        for row in rows:
            component = row["key"].split(":", 1)[1]
            try:
                details[component] = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError) as error:
                details[component] = {
                    "is_ok": False,
                    "detail": f"{type(error).__name__}: ugyldig gemt status",
                    "checked_at": "",
                    "error_type": type(error).__name__,
                }
        return {
            component: details.get(component, {
                "is_ok": is_ok,
                "detail": "Ingen detaljeret kontrol er udført",
                "checked_at": "",
                "error_type": None,
            })
            for component, is_ok in statuses.items()
        }

    def set_openai_health_cache(self, state: dict[str, Any]) -> None:
        """Persist sanitized OpenAI connection-test metadata."""
        allowed = {
            "last_attempt", "last_success", "is_ok", "detail",
            "error_type", "next_test_at", "config_fingerprint",
        }
        payload = {key: state.get(key) for key in allowed}
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO app_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (
                    "system_health_cache:openai",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def get_openai_health_cache(self) -> dict[str, Any] | None:
        """Return sanitized cached OpenAI health metadata."""
        row = self._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            ("system_health_cache:openai",),
        ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def get_dashboard_system_status(self) -> dict[str, bool]:
        """Return database-backed status for dashboard components."""
        rows = self._connection.execute(
            """
            SELECT key, value
            FROM app_state
            WHERE key LIKE 'system_status:%'
            """
        ).fetchall()
        stored = {
            row["key"].split(":", 1)[1]: row["value"] == "ok"
            for row in rows
        }
        search_summary = self.get_search_console_summary()
        baseline = self._connection.execute(
            """
            SELECT value FROM app_state
            WHERE key = 'baseline_initialized'
            """
        ).fetchone()
        return {
            "database": True,
            "partner_ads": stored.get(
                "partner_ads",
                bool(baseline and baseline["value"] == "1"),
            ),
            "search_console": stored.get(
                "search_console",
                search_summary["latest_sync"] is not None,
            ),
            "agent_orchestrator": stored.get(
                "agent_orchestrator",
                self._table_exists("events") and self._table_exists("actions"),
            ),
            "knowledge_engine": stored.get("knowledge_engine", False),
            "openai": stored.get("openai", False),
        }

    def get_dashboard_overview(self) -> dict[str, int]:
        """Return website, project, and task totals for dashboard cards."""
        websites = self._connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE
                    WHEN active = 1
                     AND status NOT IN ('phasing_out', 'archived', 'cancelled')
                    THEN 1 ELSE 0 END
                ) AS active,
                SUM(CASE WHEN monetized = 1 THEN 1 ELSE 0 END) AS monetized,
                SUM(CASE WHEN status = 'phasing_out' THEN 1 ELSE 0 END)
                    AS phasing_out
            FROM websites
            """
        ).fetchone()
        return {
            "websites": int(websites["total"] or 0),
            "active_websites": int(websites["active"] or 0),
            "monetized": int(websites["monetized"] or 0),
            "phasing_out": int(websites["phasing_out"] or 0),
            "active_projects": self.get_active_project_count(),
            "open_tasks": self.get_open_task_count(),
        }

    def get_dashboard_economy(
        self,
        reference_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Return current daily and monthly commission and sale counts."""
        current = reference_time or datetime.now().astimezone()
        sale_date = f"{current.day}-{current.month}-{current.year}"
        rows = self._connection.execute(
            """
            SELECT dato, tidspunkt, ordrenr, kombiid, provision, url, valuta
            FROM registered_sales
            """
        ).fetchall()
        today_count = 0
        month_count = 0
        today_commission = Decimal("0")
        month_commission = Decimal("0")
        month_sales_rows = []
        for row in rows:
            try:
                day, month, year = (
                    int(part) for part in row["dato"].split("-")
                )
                provision = Decimal(str(row["provision"]))
            except (AttributeError, TypeError, ValueError, InvalidOperation):
                continue
            if str(row["valuta"]).upper() != "DKK":
                continue
            if (day, month, year) == (
                current.day,
                current.month,
                current.year,
            ):
                today_count += 1
                today_commission += provision
            if (month, year) == (current.month, current.year):
                month_count += 1
                month_commission += provision
                website = urlsplit(str(row["url"] or "")).netloc.lower()
                if website.startswith("www."):
                    website = website[4:]
                month_sales_rows.append({
                    "dato": date(year, month, day),
                    "tidspunkt": row["tidspunkt"],
                    "website": website or "Ukendt",
                    "reference": row["ordrenr"] or row["kombiid"] or "—",
                    "provision": provision,
                })
        month_sales_rows.sort(
            key=lambda item: (item["dato"], item["tidspunkt"]),
            reverse=True,
        )
        return {
            "today_commission": today_commission,
            "month_commission": month_commission,
            "today_sales": today_count,
            "month_sales": month_count,
            "month_sales_rows": month_sales_rows,
        }

    def get_priority_tasks(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return the highest-priority open tasks with project context."""
        rows = self._connection.execute(
            """
            SELECT
                t.website_id AS website,
                p.title AS project,
                t.title AS task,
                t.assigned_agent,
                t.priority_score,
                t.estimated_minutes,
                t.status
            FROM tasks t
            JOIN subprojects sp ON sp.id = t.subproject_id
            JOIN projects p ON p.id = sp.project_id
            WHERE t.status NOT IN ('completed', 'cancelled')
            ORDER BY t.priority_score DESC, t.id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def replace_priority_task_scores(
        self, items: list[dict[str, Any]]
    ) -> int:
        """Replace the current priority snapshot in one transaction."""
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        score_fields = (
            "plausible_score",
            "search_console_click_score",
            "ctr_score",
            "position_score",
            "seo_health_score",
            "experiment_score",
            "missing_data_score",
            "system_score",
            "existing_task_score",
        )
        with self._connection:
            self._connection.execute("DELETE FROM priority_task_scores")
            self._connection.executemany(
                """
                INSERT INTO priority_task_scores (
                    task_key, task_type, website, priority, description,
                    target, link_label, total_score, plausible_score,
                    search_console_click_score, ctr_score, position_score,
                    seo_health_score, experiment_score, missing_data_score,
                    system_score, existing_task_score, payload_json,
                    calculated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        item["task_key"],
                        item["task_type"],
                        item["website"],
                        item["priority"],
                        item["description"],
                        item["target"],
                        item["link_label"],
                        float(item["total_score"]),
                        *(float(item.get(field, 0)) for field in score_fields),
                        json.dumps(item, ensure_ascii=False, default=str),
                        timestamp,
                    )
                    for item in items
                ],
            )
        return len(items)

    def get_priority_task_scores(
        self, limit: int | None = 5
    ) -> list[dict[str, Any]]:
        """Return the persisted priority snapshot without writing data."""
        query = """
            SELECT payload_json, calculated_at
            FROM priority_task_scores
            ORDER BY
                total_score DESC, task_type, website, description, task_key
        """
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
        rows = self._connection.execute(query, parameters).fetchall()
        result = []
        for row in rows:
            item = json.loads(row["payload_json"])
            item["calculated_at"] = row["calculated_at"]
            result.append(item)
        return result

    def upsert_traffic_recommendation_decision(
        self, values: dict[str, Any]
    ) -> str:
        """Create or update one draft, snooze, or rejection decision."""
        key = str(values["recommendation_key"])
        existing = self._connection.execute(
            """
            SELECT id FROM traffic_recommendation_decisions
            WHERE recommendation_key = ?
            """,
            (key,),
        ).fetchone()
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO traffic_recommendation_decisions (
                    recommendation_key, website_id, task_type, target_url,
                    measured_cause, title, description, priority, status,
                    snoozed_until, evidence_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recommendation_key) DO UPDATE SET
                    website_id = excluded.website_id,
                    task_type = excluded.task_type,
                    target_url = excluded.target_url,
                    measured_cause = excluded.measured_cause,
                    title = excluded.title,
                    description = excluded.description,
                    priority = excluded.priority,
                    status = excluded.status,
                    snoozed_until = excluded.snoozed_until,
                    evidence_json = excluded.evidence_json,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    str(values["website_id"]),
                    str(values["task_type"]),
                    str(values.get("target_url", "")),
                    str(values.get("measured_cause", "")),
                    str(values["title"]),
                    str(values["description"]),
                    str(values["priority"]),
                    str(values["status"]),
                    values.get("snoozed_until"),
                    json.dumps(
                        values.get("evidence", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    timestamp,
                    timestamp,
                ),
            )
        return "updated" if existing else "created"

    def get_traffic_recommendation_decision(
        self, recommendation_key: str
    ) -> dict[str, Any] | None:
        """Return one saved traffic recommendation decision."""
        row = self._connection.execute(
            """
            SELECT * FROM traffic_recommendation_decisions
            WHERE recommendation_key = ?
            """,
            (recommendation_key,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        return result

    def get_traffic_recommendation_decisions(
        self,
    ) -> list[dict[str, Any]]:
        """Return all saved recommendation decisions newest first."""
        rows = self._connection.execute(
            """
            SELECT * FROM traffic_recommendation_decisions
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            result.append(item)
        return result

    def find_open_task_by_title(
        self, website_id: str, title: str
    ) -> dict[str, Any] | None:
        """Find an operational task with the same normalized title."""
        row = self._connection.execute(
            """
            SELECT id, website_id, title, status
            FROM tasks
            WHERE website_id = ?
              AND LOWER(TRIM(title)) = LOWER(TRIM(?))
              AND status NOT IN ('completed', 'cancelled')
            ORDER BY id
            LIMIT 1
            """,
            (website_id, title),
        ).fetchone()
        return dict(row) if row else None

    def get_dashboard_action_context(self) -> dict[str, list[dict[str, Any]]]:
        """Return existing records needed for the dashboard action list."""
        experiments = self._connection.execute(
            """
            SELECT
                e.id, e.website_id AS website, e.target_url, e.status
            FROM seo_experiments e
            JOIN websites w ON w.website = e.website_id
            WHERE e.status = 'ready_for_evaluation'
              AND w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
            ORDER BY e.id
            """
        ).fetchall()
        active_experiments = self._connection.execute(
            """
            SELECT
                e.id, e.website_id AS website, e.target_url, e.status
            FROM seo_experiments e
            JOIN websites w ON w.website = e.website_id
            WHERE e.status IN ('waiting_for_data', 'ready_for_evaluation')
              AND w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
            ORDER BY e.id
            """
        ).fetchall()
        coverage = self._connection.execute(
            """
            SELECT
                w.website,
                MAX(sc.metric_date) AS latest_search_console,
                MAX(pm.metric_date) AS latest_plausible
            FROM websites w
            LEFT JOIN search_console_daily_metrics sc
                ON sc.website_id = w.website
            LEFT JOIN plausible_daily_metrics pm
                ON pm.website_id = w.website
            WHERE w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
            GROUP BY w.website
            ORDER BY w.website
            """
        ).fetchall()
        seo_health = self._connection.execute(
            """
            SELECT
                h.website_id AS website,
                h.score,
                h.trend,
                h.click_change,
                h.ctr_change,
                h.position_change
            FROM seo_health_history h
            JOIN websites w ON w.website = h.website_id
            WHERE h.period = '28d'
              AND w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
              AND h.date = (
                  SELECT MAX(h2.date)
                  FROM seo_health_history h2
                  WHERE h2.website_id = h.website_id
                    AND h2.period = h.period
              )
            ORDER BY h.score, h.website_id
            """
        ).fetchall()
        plausible_daily = self._connection.execute(
            """
            SELECT pm.website_id AS website, pm.metric_date, pm.visitors
            FROM plausible_daily_metrics pm
            JOIN websites w ON w.website = pm.website_id
            WHERE w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
            ORDER BY pm.website_id, pm.metric_date
            """
        ).fetchall()
        search_diagnoses = self._latest_diagnosis_payloads(
            "search_console_diagnoses"
        )
        plausible_diagnoses = self._latest_diagnosis_payloads(
            "plausible_diagnoses"
        )
        return {
            "experiments": [dict(row) for row in experiments],
            "active_experiments": [dict(row) for row in active_experiments],
            "coverage": [dict(row) for row in coverage],
            "seo_health": [dict(row) for row in seo_health],
            "plausible_daily": [dict(row) for row in plausible_daily],
            "search_diagnoses": search_diagnoses,
            "plausible_diagnoses": plausible_diagnoses,
        }

    def _latest_diagnosis_payloads(
        self, table: str
    ) -> list[dict[str, Any]]:
        """Return the newest active-site diagnosis from an allowed table."""
        if table not in {
            "search_console_diagnoses", "plausible_diagnoses"
        }:
            raise ValueError("Ukendt diagnosetabel")
        rows = self._connection.execute(
            f"""
            SELECT d.analysis_json
            FROM {table} d
            JOIN websites w ON w.website = d.website_id
            WHERE w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
              AND d.id = (
                  SELECT d2.id FROM {table} d2
                  WHERE d2.website_id = d.website_id
                  ORDER BY d2.period_end DESC, d2.id DESC
                  LIMIT 1
              )
            ORDER BY d.website_id
            """
        ).fetchall()
        return [json.loads(str(row["analysis_json"])) for row in rows]

    def get_latest_seo_health_sites(
        self,
        trend: str | None = None,
        period: str = "28d",
    ) -> list[dict[str, Any]]:
        """Return latest SEO Health rows, optionally filtered by trend."""
        parameters: list[Any] = [period, period]
        trend_filter = ""
        if trend:
            trend_filter = " AND h.trend = ?"
            parameters.append(trend)
        rows = self._connection.execute(
            f"""
            SELECT
                h.website_id AS website,
                h.score,
                h.trend,
                h.click_change,
                h.impression_change,
                h.ctr_change,
                h.position_change
            FROM seo_health_history h
            JOIN websites w ON w.website = h.website_id
            WHERE h.period = ?
              AND w.active = 1
              AND w.status NOT IN (
                  'inactive', 'phasing_out', 'archived', 'cancelled'
              )
              AND h.date = (
                  SELECT MAX(date)
                  FROM seo_health_history
                  WHERE period = ?
              )
              {trend_filter}
            ORDER BY h.score, h.website_id
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_active_seo_recovery_projects(self) -> list[dict[str, Any]]:
        """Return active SEO Recovery projects with latest 28-day health."""
        rows = self._connection.execute(
            """
            SELECT
                p.website_id AS website,
                h.score AS seo_score,
                h.trend,
                p.title AS project,
                p.status
            FROM projects p
            LEFT JOIN seo_health_history h
                ON h.website_id = p.website_id
               AND h.period = '28d'
               AND h.date = (
                   SELECT MAX(h2.date)
                   FROM seo_health_history h2
                   WHERE h2.website_id = p.website_id
                     AND h2.period = '28d'
               )
            WHERE p.title LIKE 'SEO Recovery – %'
              AND p.status NOT IN ('completed', 'cancelled')
            ORDER BY h.score, p.website_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_sales(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return recent sales with a normalized website label."""
        rows = self._connection.execute(
            """
            SELECT dato, tidspunkt, url, omsaetning, provision, created_at
            FROM registered_sales
            ORDER BY created_at DESC, kombiid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            parsed = urlsplit(
                item["url"] if "://" in item["url"] else f"//{item['url']}"
            )
            item["website"] = parsed.hostname or item["url"] or "Ukendt"
            results.append(item)
        return results

    def get_recent_events(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return the latest Agent Orchestrator events."""
        rows = self._connection.execute(
            """
            SELECT
                created_at, event_type, source, website, title, status
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _table_exists(self, table_name: str) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None

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

    def _ensure_sales_sync_columns(self) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(registered_sales)"
            )
        }
        additions = {
            "status": "TEXT NOT NULL DEFAULT ''",
            "approval_status": "TEXT NOT NULL DEFAULT ''",
            "telegram_status": "TEXT NOT NULL DEFAULT 'skipped'",
            "telegram_attempted_at": "TEXT",
        }
        with self._connection:
            for name, definition in additions.items():
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE registered_sales ADD COLUMN {name} {definition}"
                    )

    @staticmethod
    def _parse_partner_ads_date(value: str) -> date | None:
        for pattern in ("%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), pattern).date()
            except (TypeError, ValueError):
                continue
        return None

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
