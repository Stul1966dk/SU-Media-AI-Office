"""User-configured, read-only sitemap catalog for each website."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import requests

from integrations.website_scanner import TIMEOUT_SECONDS, USER_AGENT


MAX_SITEMAPS = 50
MAX_URLS = 20_000


class SitemapCatalog:
    def __init__(self, database: Any, *, session: Any | None = None) -> None:
        self.database = database
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get(self, website_id: str) -> dict[str, Any]:
        return self.database.get_integration_state(
            f"sitemap:{website_id}"
        ) or {}

    def sync(self, website_id: str, sitemap_url: str) -> dict[str, Any]:
        website = self._host(website_id)
        root_url = str(sitemap_url or "").strip()
        self._validate_sitemap_url(root_url, website)
        pending = [root_url]
        visited: set[str] = set()
        entries: dict[str, dict[str, str]] = {}
        while pending and len(visited) < MAX_SITEMAPS and len(entries) < MAX_URLS:
            current = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            response = self.session.get(current, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            kind = root.tag.rsplit("}", 1)[-1].casefold()
            if kind == "sitemapindex":
                for node in root.findall(".//{*}sitemap"):
                    location = self._node_text(node, "loc")
                    if location and location not in visited:
                        self._validate_sitemap_url(location, website)
                        pending.append(location)
                continue
            if kind != "urlset":
                raise ValueError("Sitemap-filen er hverken et URL-sæt eller indeks.")
            inferred_type = self._content_type(current)
            for node in root.findall(".//{*}url"):
                location = self._node_text(node, "loc")
                if not location or self._host(location) != website:
                    continue
                entries[location] = {
                    "url": location,
                    "last_modified": self._node_text(node, "lastmod"),
                    "content_type": inferred_type,
                    "source_sitemap": current,
                }
                if len(entries) >= MAX_URLS:
                    break
        state = {
            "website_id": website_id,
            "sitemap_url": root_url,
            "synced_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "sitemaps_read": len(visited),
            "url_count": len(entries),
            "urls": list(entries.values()),
        }
        self.database.set_integration_state(f"sitemap:{website_id}", state)
        return state

    @staticmethod
    def _node_text(node: ET.Element, name: str) -> str:
        child = node.find(f"{{*}}{name}")
        return str(child.text or "").strip() if child is not None else ""

    @classmethod
    def _validate_sitemap_url(cls, value: str, website: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or cls._host(value) != website:
            raise ValueError(
                "Sitemap-adressen skal være en offentlig URL på det valgte website."
            )

    @staticmethod
    def _host(value: str) -> str:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        host = (parsed.hostname or "").casefold().rstrip(".")
        return host[4:] if host.startswith("www.") else host

    @staticmethod
    def _content_type(sitemap_url: str) -> str:
        path = urlsplit(sitemap_url).path.casefold()
        if "categor" in path:
            return "category"
        if "tag" in path:
            return "tag"
        if "post" in path:
            return "post"
        if "page" in path:
            return "page"
        return "url"
