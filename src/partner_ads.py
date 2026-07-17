"""Partner-ads XML integration."""

from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import requests
from requests import RequestException


def _local_name(tag: str) -> str:
    """Return an XML tag without a namespace."""
    return tag.rsplit("}", 1)[-1]


class PartnerAdsService:
    """Fetch and parse sales from Partner-ads."""

    def __init__(self, base_url: str, key: str) -> None:
        if not base_url or not key:
            raise ValueError(
                "PARTNER_ADS_BASE_URL og PARTNER_ADS_KEY skal angives i .env."
            )

        self.base_url = base_url
        self.key = key

    def build_url(self, today: date | None = None) -> str:
        """Build a URL for the period from yesterday through today."""
        current_date = today or date.today()
        yesterday = current_date - timedelta(days=1)
        parts = urlsplit(self.base_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(
            {
                "key": self.key,
                "fra": yesterday.strftime("%y-%m-%d"),
                "til": current_date.strftime("%y-%m-%d"),
            }
        )
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    @staticmethod
    def safe_url(url: str) -> str:
        """Return a printable URL with the API key hidden."""
        parts = urlsplit(url)
        query = [
            (name, "***" if name.lower() == "key" else value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query, safe="*"),
                parts.fragment,
            )
        )

    def fetch_sales(self) -> tuple[str, list[dict[str, str]]]:
        """Fetch Partner-ads XML and return the request URL and parsed sales."""
        url = self.build_url()
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
        except RequestException as error:
            status = (
                f"HTTP {error.response.status_code}"
                if error.response is not None
                else "ingen forbindelse"
            )
            raise RuntimeError(f"Partner-ads svarer ikke ({status}).") from None

        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError:
            raise RuntimeError("Partner-ads returnerede ugyldig XML.") from None

        return url, self._parse_sales(root)

    @staticmethod
    def _parse_sales(root: ElementTree.Element) -> list[dict[str, str]]:
        """Convert sale-like XML records to simple dictionaries."""
        sale_tags = {"sale", "sales", "salg", "lead", "transaction", "order", "conversion"}
        records = [
            element
            for element in root.iter()
            if _local_name(element.tag).lower() in sale_tags
            and len(list(element)) > 0
            and any(not list(child) for child in element)
        ]

        if not records:
            records = [child for child in root if len(list(child)) > 0]

        sales: list[dict[str, str]] = []
        for record in records:
            values = {
                _local_name(field.tag): (field.text or "").strip()
                for field in record.iter()
                if field is not record and not list(field) and (field.text or "").strip()
            }
            if "kombiid" not in values and "konvid" in values:
                values["kombiid"] = values.pop("konvid")
            if values:
                sales.append(values)
        return sales

    pass
