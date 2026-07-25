"""Read-only connector for Plausible's Stats API."""

import os
from datetime import date, timedelta
from typing import Any

import requests


class PlausibleConnectorError(RuntimeError):
    """Safe, user-facing Plausible connection error."""


class PlausibleConnector:
    """Query aggregate visitor counts without storing or changing data."""

    def __init__(
        self, *, api_token: str | None = None, site_id: str | None = None,
        base_url: str | None = None, session: Any | None = None,
        timeout: int = 15,
    ) -> None:
        configured_token = (
            os.getenv("PLAUSIBLE_API_KEY", "")
            or os.getenv("PLAUSIBLE_API_TOKEN", "")
        )
        self.api_token = (
            api_token if api_token is not None else configured_token
        ).strip()
        self.site_id = (
            site_id if site_id is not None
            else os.getenv("PLAUSIBLE_SITE_ID", "")
        ).strip()
        self.base_url = (
            base_url or os.getenv("PLAUSIBLE_BASE_URL", "https://plausible.io")
        ).rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def test_connection(self) -> bool:
        """Verify Stats API access using yesterday's visitor count."""
        if not self.site_id:
            raise PlausibleConnectorError(
                "Vælg et Plausible-website før forbindelsen testes."
            )
        self.get_daily_visitors(self.site_id, date.today() - timedelta(days=1))
        return True

    def get_daily_visitors(self, site: str, metric_date: date | str) -> int:
        """Return unique visitors for one site and one calendar date."""
        day = self._normalize_date(metric_date)
        return self.get_daily_visitors_range(site, day, day)[day]

    def get_daily_visitors_range(
        self, site: str, start_date: date | str, end_date: date | str
    ) -> dict[str, int]:
        """Return one visitor count per day using a single Stats API query."""
        site_id = str(site).strip()
        if not self.api_token:
            raise PlausibleConnectorError(
                "Plausible API-token mangler i konfigurationen."
            )
        if not site_id:
            raise PlausibleConnectorError("Plausible-websitet mangler.")
        start = self._normalize_date(start_date)
        end = self._normalize_date(end_date)
        if start > end:
            raise PlausibleConnectorError("Datointervallet er ugyldigt.")
        payload = self._query({
            "site_id": site_id,
            "metrics": ["visitors"],
            "date_range": [start, end],
            "dimensions": ["time:day"],
        })
        results = payload.get("results")
        if not isinstance(results, list):
            raise PlausibleConnectorError(
                "Plausible-svaret mangler gyldige resultater."
            )
        current = date.fromisoformat(start)
        last = date.fromisoformat(end)
        daily = {}
        while current <= last:
            daily[current.isoformat()] = 0
            current += timedelta(days=1)
        for row in results:
            dimensions = row.get("dimensions")
            metrics = row.get("metrics")
            if (
                not isinstance(dimensions, list) or not dimensions
                or not isinstance(metrics, list) or not metrics
            ):
                raise PlausibleConnectorError(
                    "Plausible-svaret mangler dag eller besøgstal."
                )
            day = str(dimensions[0])[:10]
            if day not in daily:
                continue
            try:
                daily[day] = int(metrics[0] or 0)
            except (TypeError, ValueError) as error:
                raise PlausibleConnectorError(
                    "Plausible returnerede et ugyldigt besøgstal."
                ) from error
        return daily

    @staticmethod
    def _normalize_date(value: date | str) -> str:
        try:
            return (
                value if isinstance(value, date)
                else date.fromisoformat(str(value))
            ).isoformat()
        except ValueError as error:
            raise PlausibleConnectorError("Datoen er ugyldig.") from error

    def _query(self, query: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/query",
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json=query,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise PlausibleConnectorError(
                "Plausible kunne ikke kontaktes. Prøv igen senere."
            ) from error
        if response.status_code == 401:
            raise PlausibleConnectorError("Plausible afviste API-tokenet.")
        if response.status_code == 403:
            raise PlausibleConnectorError(
                "API-tokenet har ikke adgang til Plausible Stats API."
            )
        if response.status_code in {400, 404, 422}:
            raise PlausibleConnectorError(
                "Plausible kunne ikke finde statistik for det valgte website."
            )
        if response.status_code >= 400:
            raise PlausibleConnectorError(
                f"Plausible svarede med HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except (ValueError, TypeError) as error:
            raise PlausibleConnectorError(
                "Plausible returnerede et ugyldigt svar."
            ) from error
        if not isinstance(payload, dict):
            raise PlausibleConnectorError(
                "Plausible returnerede et ugyldigt svar."
            )
        return payload
