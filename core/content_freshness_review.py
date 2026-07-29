"""Background AI verification of possible outdated public content."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.ai_service import AIService
from core.content_freshness import audit_content


MAX_REVIEWS_PER_RUN = 3


class ContentFreshnessReviewService:
    """Verify heuristic signals with web search before creating work."""

    def __init__(self, database: Any, ai_service: Any | None = None) -> None:
        self.database = database
        self.ai_service = ai_service or AIService()

    def run(self, website_ids: list[str] | None = None) -> dict[str, Any]:
        selected = website_ids or self.database.get_active_website_ids()
        reviews = self.database.get_content_freshness_reviews()
        pending: list[dict[str, Any]] = []
        for website_id in selected:
            for row in self.database.get_content(website_id):
                audit = audit_content(row)
                url = str(row.get("url") or "").strip()
                key = _normalize_url(url)
                cached = reviews.get(key, {})
                if (
                    not url
                    or audit["status"] == "current"
                    or cached.get("content_hash")
                    == str(row.get("raw_hash") or "")
                ):
                    continue
                pending.append({**row, "website_id": website_id, "audit": audit})
        pending.sort(
            key=lambda row: (
                -int(row["audit"]["score"]),
                str(row.get("website_id") or ""),
                str(row.get("url") or ""),
            )
        )
        checked = 0
        confirmed = 0
        for row in pending[:MAX_REVIEWS_PER_RUN]:
            review = self._review(row)
            reviews[_normalize_url(row["url"])] = review
            checked += 1
            confirmed += review["status"] == "outdated"
        if checked:
            self.database.save_content_freshness_reviews(reviews)
        return {
            "status": "success",
            "records_processed": checked,
            "records_updated": confirmed,
            "pending": max(0, len(pending) - checked),
        }

    def _review(self, row: dict[str, Any]) -> dict[str, Any]:
        prompt = _review_prompt(row)
        response = self.ai_service.generate_response(
            prompt, tools=[{"type": "web_search"}]
        )
        value = _parse_json(response.text)
        official_sources = [
            str(source).strip()
            for source in value.get("official_sources", [])
            if str(source).strip().startswith(("https://", "http://"))
        ][:5]
        status = (
            "outdated"
            if value.get("is_outdated") is True
            and str(value.get("confidence") or "").casefold() == "high"
            and official_sources
            else "not_confirmed"
        )
        return {
            "status": status,
            "confidence": (
                "high" if status == "outdated"
                else str(value.get("confidence") or "low").casefold()
            ),
            "reason": str(value.get("reason") or "").strip(),
            "official_sources": official_sources,
            "content_hash": str(row.get("raw_hash") or ""),
            "checked_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        }


def _review_prompt(row: dict[str, Any]) -> str:
    text = str(row.get("content_text") or row.get("excerpt") or "")[:6000]
    signals = json.dumps(
        row.get("audit", {}).get("signals", []), ensure_ascii=False
    )
    return f"""
Kontrollér i baggrunden, om denne danske webtekst rent faktisk indeholder en
faktuelt uaktuel oplysning. Brug web search og prioritér officielle kilder fra
produktets, tjenestens eller myndighedens eget website. Tekstens alder eller et
gammelt årstal er ikke i sig selv bevis. Svar kun med gyldig JSON:
{{
  "is_outdated": true eller false,
  "confidence": "high", "medium" eller "low",
  "reason": "kort konkret begrundelse",
  "official_sources": ["https://..."]
}}
Sæt kun is_outdated=true, når en konkret påstand i teksten modsiges af en
aktuel officiel kilde. Ved tvivl skal svaret være false.

URL: {row.get("url")}
Titel: {row.get("title")}
Automatiske signaler: {signals}
Tekst:
{text}
""".strip()


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Aktualitetskontrollen returnerede ikke et objekt.")
    return value


def _normalize_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/").casefold()
