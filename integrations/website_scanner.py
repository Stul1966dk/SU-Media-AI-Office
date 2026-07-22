"""Bounded, read-only scanner for public website metadata."""

import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests


USER_AGENT = "SU-Media-AI-Office/0.1 Website Discovery"
TIMEOUT_SECONDS = 10
MAX_SITEMAP_URLS = 10_000
MAX_CHILD_SITEMAPS = 20


class _HTMLFacts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.h1 = ""
        self.in_title = False
        self.in_h1 = False
        self.meta: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.schema_types: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self.in_title = True
        elif tag == "h1" and not self.h1:
            self.in_h1 = True
        elif tag == "meta":
            self.meta.append(values)
        elif tag == "link":
            self.links.append(values)
        elif tag == "script":
            self.scripts.append(values)
        if "itemscope" in values and values.get("itemtype"):
            self.schema_types.add(values["itemtype"].rstrip("/").split("/")[-1])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "h1":
            self.in_h1 = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self.in_h1:
            self.h1 += data
        if self.scripts and self.scripts[-1].get("type") == "application/ld+json":
            try:
                payload = json.loads(data)
                nodes = payload if isinstance(payload, list) else [payload]
                for node in nodes:
                    if isinstance(node, dict):
                        graph = node.get("@graph", [node])
                        graph = graph if isinstance(graph, list) else [graph]
                        for item in graph:
                            kind = item.get("@type") if isinstance(item, dict) else None
                            for value in kind if isinstance(kind, list) else [kind]:
                                if value:
                                    self.schema_types.add(str(value))
            except (ValueError, TypeError):
                pass


class WebsiteScanner:
    """Inspect a fixed set of public endpoints without writing remotely."""

    def __init__(self, session: Any | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def fetch_page(self, url: str) -> Any:
        """GET one public HTTP(S) URL with bounded transfer and no cookies."""
        self._validate_url(url)
        response = self.session.get(
            url, timeout=TIMEOUT_SECONDS, allow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Cookie": ""},
        )
        cookies = getattr(self.session, "cookies", None)
        if cookies is not None:
            cookies.clear()
        return response

    def inspect_robots(self, domain: str) -> dict[str, Any]:
        response = self.fetch_page(f"https://{self._domain(domain)}/robots.txt")
        text = response.text[:200_000] if response.status_code < 400 else ""
        blocked = bool(re.search(
            r"(?ims)^user-agent:\s*\*\s*(?:\r?\n(?!user-agent:).*)*?"
            r"^disallow:\s*/\s*$", text
        ))
        sitemap = next(
            (line.split(":", 1)[1].strip() for line in text.splitlines()
             if line.lower().startswith("sitemap:")), None
        )
        return {
            "status": "blocked_all" if blocked else
                      "ok" if response.status_code < 400 else "missing",
            "sitemap": sitemap,
        }

    def inspect_sitemap(
        self, domain: str, sitemap_url: str | None = None
    ) -> dict[str, Any]:
        url = sitemap_url or f"https://{self._domain(domain)}/sitemap.xml"
        response = self.fetch_page(url)
        if response.status_code >= 400:
            return {"status": "missing", "url": url, "count": 0, "types": []}
        count, types = self._count_sitemap(response.text)
        return {"status": "ok", "url": url, "count": count, "types": types}

    def scan(self, domain: str) -> dict[str, Any]:
        """Return documented facts from homepage, robots, sitemap and WP REST."""
        clean = self._domain(domain)
        result = self._empty(clean)
        try:
            response = self.fetch_page(f"https://{clean}/")
            result["https_enabled"] = urlsplit(response.url).scheme == "https"
        except requests.RequestException:
            response = self.fetch_page(f"http://{clean}/")
            result["https_enabled"] = False
        result["http_status"] = int(response.status_code)
        parser = _HTMLFacts()
        parser.feed(response.text[:2_000_000])
        assets = [
            item.get("href", "") for item in parser.links
        ] + [item.get("src", "") for item in parser.scripts]
        generator = self._meta(parser.meta, "generator")
        signals = self._signals(response.text[:2_000_000], assets, generator)
        cms, cms_confidence = self.detect_cms(signals)
        theme, theme_confidence = self.detect_theme(signals)
        builder, builder_confidence = self.detect_page_builder(signals)
        robots = self.inspect_robots(clean)
        sitemap = self.inspect_sitemap(clean, robots.get("sitemap"))
        rest_available = False
        if cms == "wordpress":
            try:
                rest = self.fetch_page(f"https://{clean}/wp-json/")
                rest_available = rest.status_code < 400
            except requests.RequestException:
                pass
        result.update({
            "cms": cms, "cms_confidence": cms_confidence,
            "theme": theme, "theme_confidence": theme_confidence,
            "page_builder": builder, "page_builder_confidence": builder_confidence,
            "robots_status": robots["status"],
            "sitemap_status": sitemap["status"], "sitemap_url": sitemap["url"],
            "sitemap_url_count": sitemap["count"],
            "sitemap_types": sitemap["types"],
            "canonical_url": next((
                urljoin(response.url, x.get("href", "")) for x in parser.links
                if "canonical" in x.get("rel", "").lower()
            ), ""),
            "title": parser.title.strip()[:500],
            "meta_description": self._meta(parser.meta, "description")[:1000],
            "h1": parser.h1.strip()[:500],
            "schema_types": self.detect_schema(parser),
            "generator": generator[:500],
            "wordpress_rest_available": rest_available,
            "detected_signals": signals[:100],
            "scan_status": "completed",
        })
        return result

    @staticmethod
    def detect_cms(signals: list[str]) -> tuple[str, int]:
        wp = sum(1 for item in signals if item.startswith("wordpress:"))
        return ("wordpress", min(100, 55 + wp * 15)) if wp else ("unknown", 0)

    @staticmethod
    def detect_theme(signals: list[str]) -> tuple[str, int]:
        match = next((x.split(":", 2)[2] for x in signals
                      if x.startswith("theme:documented:")), None)
        return (match, 90) if match else ("unknown", 0)

    @staticmethod
    def detect_page_builder(signals: list[str]) -> tuple[str, int]:
        builders = {"elementor": "elementor", "divi": "divi",
                    "beaver-builder": "beaver_builder", "bricks": "bricks"}
        for signal in signals:
            for marker, name in builders.items():
                if marker in signal.lower():
                    return name, 90
        return "unknown", 0

    @staticmethod
    def detect_schema(parser: _HTMLFacts) -> list[str]:
        return sorted(parser.schema_types)[:100]

    @staticmethod
    def _signals(html: str, assets: list[str], generator: str) -> list[str]:
        combined = "\n".join(assets)
        signals = []
        if "wordpress" in generator.lower():
            signals.append("wordpress:generator")
        if "wp-content/" in html or "wp-content/" in combined:
            signals.append("wordpress:wp-content")
        if "wp-includes/" in html or "wp-includes/" in combined:
            signals.append("wordpress:wp-includes")
        for match in re.findall(r"/wp-content/themes/([^/?\"']+)", combined):
            signals.append(f"theme:documented:{match.lower()}")
        for marker in ("elementor", "divi", "beaver-builder", "bricks"):
            if marker in combined.lower():
                signals.append(f"builder:asset:{marker}")
        return sorted(set(signals))

    @staticmethod
    def _meta(items: list[dict[str, str]], name: str) -> str:
        return next((x.get("content", "") for x in items
                     if x.get("name", "").lower() == name), "")

    @staticmethod
    def _count_sitemap(text: str) -> tuple[int, list[str]]:
        try:
            root = ET.fromstring(text[:20_000_000])
        except ET.ParseError:
            return 0, []
        local = root.tag.rsplit("}", 1)[-1].lower()
        locations = root.findall(".//{*}loc")
        count = min(MAX_SITEMAP_URLS, len(locations))
        return count, [local] if local in {"urlset", "sitemapindex"} else []

    @staticmethod
    def _domain(value: str) -> str:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        domain = (parsed.hostname or "").lower().rstrip(".")
        if not domain or domain in {"localhost"} or domain.endswith(".local"):
            raise ValueError("Ugyldigt offentligt domæne.")
        return domain

    @classmethod
    def _validate_url(cls, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username:
            raise ValueError("Kun offentlige HTTP(S)-adresser er tilladt.")
        cls._domain(parsed.hostname or "")

    @staticmethod
    def _empty(domain: str) -> dict[str, Any]:
        return {
            "domain": domain, "cms": "unknown", "cms_confidence": 0,
            "theme": "unknown", "theme_confidence": 0,
            "page_builder": "unknown", "page_builder_confidence": 0,
            "http_status": 0, "https_enabled": False,
            "robots_status": "unknown", "sitemap_status": "unknown",
            "sitemap_url": "", "sitemap_url_count": 0, "sitemap_types": [],
            "canonical_url": "", "title": "", "meta_description": "", "h1": "",
            "schema_types": [], "generator": "",
            "wordpress_rest_available": False, "detected_signals": [],
            "scan_status": "failed", "error_message": "",
        }
