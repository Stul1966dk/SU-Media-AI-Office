"""Read-only WordPress connector with public HTML fallback."""

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

from core.agent_orchestrator import Event
from core.database import Database
from integrations.website_scanner import TIMEOUT_SECONDS, USER_AGENT

from .base_connector import BaseConnector


MAX_ITEMS_PER_TYPE = 500


class _PublicHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self.language = ""
        self.generator = ""
        self.in_title = False
        self.links: list[str] = []
        self.images: list[dict[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "html":
            self.language = values.get("lang", "")
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = values.get("name", "").lower()
            if name == "description":
                self.description = values.get("content", "")
            elif name == "generator":
                self.generator = values.get("content", "")
        elif tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif tag == "img" and values.get("src"):
            self.images.append({
                "url": values["src"], "alt": values.get("alt", ""),
            })

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data


class _ContentSections(HTMLParser):
    """Preserve public headings and passages for grounded SEO suggestions."""

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[dict[str, str]] = []
        self._tag = ""
        self._text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"h1", "h2", "h3", "p", "li"}:
            self._tag = tag
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag != self._tag:
            return
        text = " ".join(self._text).strip()
        if text:
            self.sections.append({"element": tag, "text": text})
        self._tag = ""
        self._text = []

    def handle_data(self, data: str) -> None:
        text = unescape(data).strip()
        if self._tag and text:
            self._text.append(text)


class WordPressConnector(BaseConnector):
    """Fetch public WordPress content; never authenticate or write remotely."""

    def __init__(
        self, *, website_id: str, database: Database,
        session: Any | None = None, agent_orchestrator: Any | None = None,
    ) -> None:
        self.website_id = website_id
        self.domain = website_id.lower()
        self.database = database
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.agent_orchestrator = agent_orchestrator
        self.mode: str | None = None
        self.site_url = f"https://{self.domain}"

    def connect(self) -> bool:
        """Choose public REST when available, otherwise public HTML."""
        try:
            response = self._get(f"{self.site_url}/wp-json/")
            self.mode = "rest" if response.status_code < 400 else "html"
        except requests.RequestException:
            self.mode = "html"
        return self.test_connection()

    def test_connection(self) -> bool:
        try:
            if self.mode == "rest":
                return self._get(f"{self.site_url}/wp-json/").status_code < 400
            return self._get(f"{self.site_url}/").status_code < 400
        except requests.RequestException:
            return False

    def get_site_information(self) -> dict[str, Any]:
        self._ensure_connected()
        if self.mode == "rest":
            data = self._json(self._get(f"{self.site_url}/wp-json/"))
            return {
                "name": data.get("name", ""), "description": data.get("description", ""),
                "language": data.get("language", ""), "timezone": data.get("timezone_string", ""),
                "wordpress_version": "",
            }
        response = self._get(f"{self.site_url}/")
        parsed = self._parse_html(response.text)
        version = next(iter(re.findall(
            r"WordPress\s+([\d.]+)", parsed.generator, flags=re.I
        )), "")
        return {
            "name": parsed.title.strip(), "description": parsed.description,
            "language": parsed.language, "timezone": "",
            "wordpress_version": version,
        }

    def get_posts(self) -> list[dict[str, Any]]:
        return self._content("posts", "post")

    def get_pages(self) -> list[dict[str, Any]]:
        return self._content("pages", "page")

    def get_categories(self) -> list[dict[str, Any]]:
        return self._taxonomy("categories")

    def get_tags(self) -> list[dict[str, Any]]:
        return self._taxonomy("tags")

    def get_media(self) -> list[dict[str, Any]]:
        self._ensure_connected()
        if self.mode != "rest":
            parsed = self._parse_html(self._get(f"{self.site_url}/").text)
            return [
                {
                    "id": self._hash(item["url"]), "title": "", "slug": "",
                    "url": urljoin(self.site_url, item["url"]), "status": "public",
                    "published_at": "", "updated_at": "", "categories": [],
                    "tags": [], "excerpt": "", "word_count": 0,
                    "featured_image": urljoin(self.site_url, item["url"]),
                    "internal_link_count": 0, "external_link_count": 0,
                    "alt_text": item["alt"], "file_type": self._file_type(item["url"]),
                }
                for item in parsed.images[:MAX_ITEMS_PER_TYPE]
            ]
        return [
            {
                "id": item.get("id"), "title": self._rendered(item.get("title")),
                "slug": item.get("slug", ""), "url": item.get("source_url", ""),
                "status": item.get("status", ""), "published_at": item.get("date", ""),
                "updated_at": item.get("modified", ""), "categories": [], "tags": [],
                "excerpt": "", "word_count": 0,
                "featured_image": item.get("source_url", ""),
                "internal_link_count": 0, "external_link_count": 0,
                "alt_text": item.get("alt_text", ""),
                "file_type": item.get("mime_type", ""),
            }
            for item in self._rest_collection("media")
        ]

    def disconnect(self) -> None:
        cookies = getattr(self.session, "cookies", None)
        if cookies is not None:
            cookies.clear()
        self.mode = None

    def import_content(self) -> dict[str, int]:
        """Persist public content and emit one event after >20 changed items."""
        groups = {
            "post": self.get_posts(), "page": self.get_pages(),
            "category": self.get_categories(), "tag": self.get_tags(),
            "media": self.get_media(),
        }
        changed = 0
        changed_pages = 0
        total = 0
        for content_type, items in groups.items():
            for item in items:
                result = self.database.save_content({
                    **item, "website_id": self.website_id,
                    "content_type": content_type,
                    "content_id": str(item.get("id", "")),
                    "raw_hash": self._content_hash(item),
                })
                total += 1
                item_changed = result in {"created", "updated"}
                changed += item_changed
                if content_type == "page":
                    changed_pages += item_changed
        if changed_pages > 20 and self.agent_orchestrator is not None:
            self.agent_orchestrator.submit_event(Event(
                event_type="website_content_updated",
                source="WordPress Connector", website=self.website_id,
                title="Omfattende websiteindhold ændret",
                description=f"{changed_pages} sider er nye eller ændrede.",
                priority=60, data={"changed_pages": changed_pages},
            ))
        return {"total": total, "changed": changed}

    def _content(self, endpoint: str, content_type: str) -> list[dict[str, Any]]:
        self._ensure_connected()
        if self.mode != "rest":
            if content_type == "post":
                return []
            return self._html_pages()
        return [self._normalize_content(item) for item in self._rest_collection(endpoint)]

    def _taxonomy(self, endpoint: str) -> list[dict[str, Any]]:
        self._ensure_connected()
        if self.mode != "rest":
            return []
        return [
            {
                "id": item.get("id"), "title": item.get("name", ""),
                "slug": item.get("slug", ""), "url": item.get("link", ""),
                "status": "public", "published_at": "", "updated_at": "",
                "categories": [], "tags": [], "excerpt": item.get("description", ""),
                "word_count": 0, "featured_image": "",
                "internal_link_count": 0, "external_link_count": 0,
            }
            for item in self._rest_collection(endpoint)
        ]

    def _rest_collection(self, endpoint: str) -> list[dict[str, Any]]:
        base = f"{self.site_url}/wp-json/wp/v2/{endpoint}?per_page=100&_embed=1"
        response = self._get(base)
        data = self._json(response)
        items = list(data) if isinstance(data, list) else []
        headers = getattr(response, "headers", {})
        total_pages = min(5, int(headers.get("X-WP-TotalPages", 1) or 1))
        for page in range(2, total_pages + 1):
            payload = self._json(self._get(f"{base}&page={page}"))
            if isinstance(payload, list):
                items.extend(payload)
            if len(items) >= MAX_ITEMS_PER_TYPE:
                break
        return items[:MAX_ITEMS_PER_TYPE]

    def _normalize_content(self, item: dict[str, Any]) -> dict[str, Any]:
        html = self._rendered(item.get("content"))
        links = re.findall(r"""href=["']([^"']+)""", html, flags=re.I)
        internal = sum(self.domain in urlsplit(urljoin(self.site_url, link)).netloc
                       for link in links)
        text = self._plain_text(html)
        section_parser = _ContentSections()
        section_parser.feed(html[:2_000_000])
        embedded = item.get("_embedded", {})
        terms = embedded.get("wp:term", []) if isinstance(embedded, dict) else []
        categories, tags = [], []
        for group in terms:
            for term in group if isinstance(group, list) else []:
                target = categories if term.get("taxonomy") == "category" else tags
                target.append(term.get("name", ""))
        media = embedded.get("wp:featuredmedia", []) if isinstance(embedded, dict) else []
        return {
            "id": item.get("id"), "title": self._rendered(item.get("title")),
            "slug": item.get("slug", ""), "url": item.get("link", ""),
            "status": item.get("status", ""), "published_at": item.get("date", ""),
            "updated_at": item.get("modified", ""), "categories": categories,
            "tags": tags, "excerpt": self._plain_text(
                self._rendered(item.get("excerpt"))
            ),
            "content_text": text[:200_000],
            "content_sections": section_parser.sections[:250],
            "word_count": len(text.split()),
            "featured_image": media[0].get("source_url", "") if media else "",
            "internal_link_count": internal,
            "external_link_count": max(0, len(links) - internal),
        }

    def _html_pages(self) -> list[dict[str, Any]]:
        response = self._get(f"{self.site_url}/")
        parsed = self._parse_html(response.text)
        links = [urljoin(response.url, link) for link in parsed.links]
        internal = sorted({
            link.split("#", 1)[0] for link in links
            if urlsplit(link).netloc == self.domain
        })[:MAX_ITEMS_PER_TYPE]
        return [{
            "id": self._hash(url), "title": "", "slug": urlsplit(url).path.strip("/"),
            "url": url, "status": "public", "published_at": "", "updated_at": "",
            "categories": [], "tags": [], "excerpt": "", "word_count": 0,
            "featured_image": "", "internal_link_count": 0,
            "external_link_count": 0,
        } for url in internal]

    def _get(self, url: str) -> Any:
        response = self.session.get(
            url, timeout=TIMEOUT_SECONDS, allow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Cookie": ""},
        )
        cookies = getattr(self.session, "cookies", None)
        if cookies is not None:
            cookies.clear()
        return response

    def _ensure_connected(self) -> None:
        if self.mode is None and not self.connect():
            raise ConnectionError("Offentlig websiteforbindelse kunne ikke oprettes.")

    @staticmethod
    def _json(response: Any) -> Any:
        try:
            return response.json()
        except (ValueError, AttributeError):
            return {}

    @staticmethod
    def _rendered(value: Any) -> str:
        return unescape(value.get("rendered", "") if isinstance(value, dict) else "")

    @staticmethod
    def _plain_text(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()

    @staticmethod
    def _parse_html(value: str) -> _PublicHTML:
        parser = _PublicHTML()
        parser.feed(value[:2_000_000])
        return parser

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:24]

    @staticmethod
    def _content_hash(item: dict[str, Any]) -> str:
        stable = repr(sorted((key, value) for key, value in item.items()))
        return hashlib.sha256(stable.encode()).hexdigest()

    @staticmethod
    def _file_type(url: str) -> str:
        return urlsplit(url).path.rsplit(".", 1)[-1].lower() if "." in urlsplit(url).path else ""
