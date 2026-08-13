"""Shared lifecycle management for the Google Search Console integration."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from google.auth.transport.requests import AuthorizedSession

from core.search_console_service import SearchConsoleService
from core.website_registry import WebsiteRegistry
from integrations.search_console import (
    SearchConsoleAuthenticationError,
    SearchConsoleConnector,
)


class SearchConsoleIntegration:
    """Own OAuth, status, and connector creation for the whole application."""

    NAME = "search_console"
    USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, project_root: Path, database: Any) -> None:
        self.project_root = project_root
        self.database = database
        self.credentials_path = project_root / "credentials.json"
        self.token_path = project_root / "token.json"

    def connector(self) -> SearchConsoleConnector:
        return SearchConsoleConnector(self.credentials_path, self.token_path)

    def search_service(self) -> SearchConsoleService:
        return SearchConsoleService(
            connector=self.connector(),
            database=self.database,
            website_registry=WebsiteRegistry(self.database),
        )

    def status(self, *, validate: bool = False) -> dict[str, Any]:
        metadata = self._get_state() or {}
        result = {
            "connected": self.token_path.exists(),
            "valid": None,
            "account": metadata.get("account"),
            "connected_at": metadata.get("connected_at"),
            "last_error": metadata.get("last_error"),
            "latest_sync": self.database.get_search_console_summary().get(
                "latest_sync"
            ),
        }
        if not result["connected"]:
            result["valid"] = False
            return result
        if validate:
            try:
                self.connector().authenticate()
            except SearchConsoleAuthenticationError as error:
                result["valid"] = False
                result["last_error"] = str(error)
                self.record_authentication_error(error)
            else:
                result["valid"] = True
                result["last_error"] = None
                self.database.set_system_status(self.NAME, True)
        return result

    def connect(self) -> dict[str, Any]:
        credentials = self.connector().start_oauth_login()
        account = self._account_email(credentials)
        state = {
            "account": account,
            "connected_at": datetime.now().astimezone().isoformat(),
            "last_error": None,
        }
        self._set_state(state)
        self.database.set_system_status(self.NAME, True)
        return state

    def reconnect(self) -> dict[str, Any]:
        return self.connect()

    def disconnect(self) -> None:
        try:
            self.token_path.unlink(missing_ok=True)
        except OSError as error:
            raise SearchConsoleAuthenticationError(
                "Search Console-tokenet kunne ikke fjernes."
            ) from error
        self._set_state(None)
        self.database.set_system_status(self.NAME, False)

    def test_active_websites(self) -> dict[str, Any]:
        """Check OAuth and property access for every active website."""
        websites = [
            item["website"] for item in self.database.get_all_websites()
            if item.get("active") and item.get("status") not in
            {"phasing_out", "archived", "cancelled"}
        ]
        connector = self.connector()
        try:
            connector.authenticate()
            properties = connector.list_properties()
        except SearchConsoleAuthenticationError as error:
            self.record_authentication_error(error)
            return {
                "ok": False, "tested": len(websites),
                "failed": len(websites),
                "results": [
                    {
                        "website": website, "ok": False,
                        "message": "Google-forbindelsen skal fornyes.",
                    }
                    for website in websites
                ],
            }
        except Exception as error:
            return {
                "ok": False, "tested": len(websites),
                "failed": len(websites),
                "results": [
                    {
                        "website": website, "ok": False,
                        "message": (
                            "Search Console kunne ikke kontrollere "
                            f"adgangen ({type(error).__name__})."
                        ),
                    }
                    for website in websites
                ],
            }
        accessible = {
            self._property_domain(item.get("site_url", ""))
            for item in properties
        }
        results = [
            {
                "website": website,
                "ok": website.lower() in accessible,
                "message": (
                    "Adgang OK"
                    if website.lower() in accessible
                    else "Ingen tilgængelig Search Console-property."
                ),
            }
            for website in websites
        ]
        self.database.set_system_status(
            self.NAME, bool(results) and all(item["ok"] for item in results)
        )
        return {
            "ok": bool(results) and all(item["ok"] for item in results),
            "tested": len(results),
            "failed": sum(not item["ok"] for item in results),
            "results": results,
        }

    def record_authentication_error(self, error: Exception) -> None:
        state = self._get_state() or {}
        state["last_error"] = str(error)
        state["error_at"] = datetime.now().astimezone().isoformat()
        self._set_state(state)
        self.database.set_system_status(self.NAME, False)

    def clear_authentication_error(self) -> None:
        """Drop a stored auth error after a successful authentication."""
        state = self._get_state() or {}
        if state.get("last_error") or state.get("error_at"):
            state["last_error"] = None
            state.pop("error_at", None)
            self._set_state(state)
        self.database.set_system_status(self.NAME, True)

    def authentication_warning(self) -> str | None:
        """Return a user-facing warning when the stored login has failed.

        Reads persisted state only (no network), so it is safe to call on
        every page render. Returns None while the login is healthy.
        """
        state = self._get_state() or {}
        if state.get("last_error"):
            return (
                "Search Console-login er udløbet eller afvist, så nye "
                "søgedata ikke kan hentes. Gå til Integrationer og klik "
                "“Forbind igen” for at forny adgangen."
            )
        return None

    def _account_email(self, credentials: Any) -> str | None:
        try:
            response = AuthorizedSession(credentials).get(
                self.USERINFO_URL, timeout=30
            )
            response.raise_for_status()
            email = response.json().get("email")
        except Exception:
            return None
        return str(email) if email else None

    @staticmethod
    def _property_domain(site_url: str) -> str:
        value = site_url.strip().lower()
        if value.startswith("sc-domain:"):
            return value.removeprefix("sc-domain:").rstrip(".")
        parsed = urlsplit(value)
        domain = parsed.hostname or ""
        return (
            domain[4:] if domain.startswith("www.") else domain
        ).rstrip(".")

    def _get_state(self) -> dict[str, Any] | None:
        """Read metadata, including during a Streamlit hot reload."""
        getter = getattr(self.database, "get_integration_state", None)
        if getter:
            return getter(self.NAME)
        row = self.database._connection.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (f"integration_state:{self.NAME}",),
        ).fetchone()
        if not row:
            return None
        try:
            state = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return None
        return state if isinstance(state, dict) else None

    def _set_state(self, state: dict[str, Any] | None) -> None:
        """Write metadata, including during a Streamlit hot reload."""
        setter = getattr(self.database, "set_integration_state", None)
        if setter:
            setter(self.NAME, state)
            return
        key = f"integration_state:{self.NAME}"
        with self.database._connection:
            if state is None:
                self.database._connection.execute(
                    "DELETE FROM app_state WHERE key = ?", (key,)
                )
            else:
                self.database._connection.execute(
                    """
                    INSERT INTO app_state (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, json.dumps(state, ensure_ascii=False)),
                )
