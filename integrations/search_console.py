"""Read-only Google Search Console OAuth connector."""

from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SEARCH_CONSOLE_READONLY_SCOPE = (
    "https://www.googleapis.com/auth/webmasters.readonly"
)


class SearchConsoleAuthenticationError(RuntimeError):
    """Raised when Search Console authentication cannot be completed."""


class SearchConsoleConnector:
    """Authenticate a desktop app and list accessible Search Console sites."""

    def __init__(
        self,
        credentials_path: Path,
        token_path: Path,
    ) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.credentials: Credentials | None = None

    def authenticate(self) -> Credentials:
        """Authenticate with read-only OAuth, reusing a local token when valid."""
        if not self.token_path.exists():
            raise SearchConsoleAuthenticationError(
                "token.json blev ikke fundet. Gennemfør Search Console "
                "OAuth-login, før dataimporten køres."
            )

        try:
            credentials = Credentials.from_authorized_user_file(
                self.token_path,
                [SEARCH_CONSOLE_READONLY_SCOPE],
            )
        except (OSError, ValueError) as error:
            raise SearchConsoleAuthenticationError(
                "token.json kunne ikke læses. Gennemfør OAuth-login igen."
            ) from error

        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except Exception as error:
                raise SearchConsoleAuthenticationError(
                    "Search Console-tokenet kunne ikke fornyes."
                ) from error

        if not credentials.valid:
            raise SearchConsoleAuthenticationError(
                "Search Console-tokenet er ugyldigt. Gennemfør OAuth-login igen."
            )

        if credentials.expiry:
            try:
                self.token_path.write_text(
                    credentials.to_json(),
                    encoding="utf-8",
                )
            except OSError as error:
                raise SearchConsoleAuthenticationError(
                    "Det fornyede Search Console-token kunne ikke gemmes."
                ) from error
        self.credentials = credentials
        return credentials

    def start_oauth_login(self) -> Credentials:
        """Run an explicit browser login and save a fresh local token."""
        if not self.credentials_path.exists():
            raise SearchConsoleAuthenticationError(
                "credentials.json blev ikke fundet i projektets rod."
            )
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_path,
                scopes=[SEARCH_CONSOLE_READONLY_SCOPE],
            )
            credentials = flow.run_local_server(port=0, open_browser=True)
            self.token_path.write_text(
                credentials.to_json(),
                encoding="utf-8",
            )
        except Exception as error:
            raise SearchConsoleAuthenticationError(
                "OAuth-login til Search Console kunne ikke gennemføres."
            ) from error
        self.credentials = credentials
        return credentials

    def list_properties(self) -> list[dict[str, str]]:
        """Return every Search Console property available to the account."""
        credentials = self.credentials or self.authenticate()
        service = build(
            "searchconsole",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
        response: dict[str, Any] = service.sites().list().execute()
        return [
            {
                "site_url": entry.get("siteUrl", ""),
                "permission_level": entry.get("permissionLevel", ""),
            }
            for entry in response.get("siteEntry", [])
            if entry.get("siteUrl")
        ]

    def get_search_analytics(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Return daily aggregate Search Analytics metrics for one property."""
        credentials = self.credentials or self.authenticate()
        service = build(
            "searchconsole",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
        response: dict[str, Any] = (
            service.searchanalytics()
            .query(
                siteUrl=site_url,
                body={
                    "startDate": start_date,
                    "endDate": end_date,
                    "dimensions": ["date"],
                    "rowLimit": 25000,
                },
            )
            .execute()
        )
        return [
            {
                "date": row["keys"][0],
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": float(row.get("ctr", 0.0)),
                "position": float(row.get("position", 0.0)),
            }
            for row in response.get("rows", [])
            if row.get("keys")
        ]
