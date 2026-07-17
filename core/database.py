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
        self._create_or_migrate_websites_table()
        self._create_work_tables()
        self._create_orchestrator_tables()
        self._create_search_console_table()
        self._create_search_console_daily_metrics_table()
        self._create_seo_health_history_table()
        self._create_seo_recommendations_table()
        self._create_website_intelligence_tables()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

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
            SELECT id
            FROM search_console_daily_metrics
            WHERE website_id = ? AND metric_date = ?
            """,
            (website_id, metric_date),
        ).fetchone()
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
            SELECT id FROM seo_health_history
            WHERE website_id = ? AND date = ? AND period = ?
            """,
            (website_id, analysis_date, period),
        ).fetchone()
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
            SELECT trend, COUNT(*) AS total
            FROM seo_health_history
            WHERE period = ?
              AND date = (
                  SELECT MAX(date)
                  FROM seo_health_history
                  WHERE period = ?
              )
            GROUP BY trend
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
            SELECT website_id, date, period, score, trend
            FROM seo_health_history
            WHERE period = ?
              AND date = (
                  SELECT MAX(date)
                  FROM seo_health_history
                  WHERE period = ?
              )
            ORDER BY score ASC, website_id
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
            SELECT id FROM website_statistics
            WHERE website_id = ? AND statistic_date = ?
            """,
            (statistics["website_id"], statistics["statistic_date"]),
        ).fetchone()
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
            "SELECT dato, provision FROM registered_sales"
        ).fetchall()
        today_count = 0
        month_count = 0
        today_commission = Decimal("0")
        month_commission = Decimal("0")
        for row in rows:
            try:
                day, month, year = (
                    int(part) for part in row["dato"].split("-")
                )
                provision = Decimal(str(row["provision"]))
            except (AttributeError, TypeError, ValueError, InvalidOperation):
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
        return {
            "today_commission": today_commission,
            "month_commission": month_commission,
            "today_sales": today_count,
            "month_sales": month_count,
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
            WHERE h.period = ?
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
