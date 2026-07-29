"""Explainable freshness checks for persisted public website content."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from core.priority_scoring import priority_label


STATUS_LABELS = {
    "current": "Aktuel",
    "review": "Bør kontrolleres",
    "partially_outdated": "Delvist forældet",
    "likely_outdated": "Sandsynligvis helt forældet",
}

STRONG_PATTERNS = (
    r"\budgået\b",
    r"\blukket ned\b",
    r"\bophørt\b",
    r"\bfindes ikke længere\b",
    r"\bunderstøttes ikke længere\b",
    r"\bkan ikke længere\b",
)
VERSION_PATTERNS = (
    r"\b(?:ios|android|windows|wordpress|woocommerce)\s*\d+(?:\.\d+)*\b",
    r"\bversion\s+\d+(?:\.\d+)*\b",
)


def audit_content(
    row: dict[str, Any], *, reference_date: date | None = None
) -> dict[str, Any]:
    """Classify one page without claiming external facts not in evidence."""
    today = reference_date or date.today()
    body = " ".join(str(row.get(key) or "") for key in (
        "excerpt", "content_text",
    )).strip()
    text = " ".join(str(row.get(key) or "") for key in (
        "title", "excerpt", "content_text",
    )).strip()
    normalized = text.casefold()
    age_years = _age_years(
        row.get("source_updated_at") or row.get("published_at"), today
    )
    score = 0
    signals: list[dict[str, str]] = []
    if age_years is not None and age_years >= 3:
        score += 2 if age_years < 5 else 3
        signals.append({
            "kind": "age",
            "label": f"Teksten er ikke opdateret i ca. {age_years} år.",
            "passage": "",
        })
    old_years = sorted({
        int(value)
        for value in re.findall(r"\b(?:19|20)\d{2}\b", text)
        if int(value) <= today.year - 2
    })
    if old_years:
        score += min(3, len(old_years))
        year = str(old_years[-1])
        signals.append({
            "kind": "year",
            "label": f"Teksten omtaler et ældre årstal: {year}.",
            "passage": _passage(text, year),
        })
    strong_match = _first_match(normalized, STRONG_PATTERNS)
    if strong_match:
        score += 4
        signals.append({
            "kind": "discontinued",
            "label": "Teksten omtaler noget, der ikke længere findes eller understøttes.",
            "passage": _passage(text, strong_match),
        })
    version_match = _first_match(normalized, VERSION_PATTERNS)
    if version_match and (age_years or 0) >= 2:
        score += 2
        signals.append({
            "kind": "version",
            "label": "En versionsspecifik vejledning kan være ændret.",
            "passage": _passage(text, version_match),
        })
    if not body or len(body.split()) < 10:
        return {
            "status": "current",
            "status_label": STATUS_LABELS["current"],
            "score": 0,
            "signals": [],
            "requires_external_verification": False,
        }
    if score >= 7 and strong_match:
        status = "likely_outdated"
    elif score >= 5:
        status = "partially_outdated"
    elif score >= 2:
        status = "review"
    else:
        status = "current"
    return {
        "status": status,
        "status_label": STATUS_LABELS[status],
        "score": score,
        "signals": signals,
        "requires_external_verification": status != "current",
    }


def build_freshness_recommendations(
    content_by_website: dict[str, list[dict[str, Any]]],
    *,
    reference_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return bounded daily candidates only for explainable freshness risks."""
    candidates = []
    for website, rows in sorted(content_by_website.items()):
        for row in rows:
            content_type = str(row.get("content_type") or "").casefold()
            status = str(row.get("status") or "").casefold()
            url = str(row.get("url") or "").strip()
            if (
                content_type not in {"post", "page"}
                or status not in {"publish", "published", "public"}
                or not url
            ):
                continue
            audit = audit_content(row, reference_date=reference_date)
            if audit["status"] == "current":
                continue
            signals = audit["signals"]
            total_score = 18.0 + float(audit["score"])
            candidates.append({
                "task_key": f"content-freshness|{website}|{url}",
                "task_type": "content_freshness",
                "daily_work_type": "content_update",
                "website": website,
                "target_url": url,
                "target_query": "",
                "search_queries": [],
                "measured_cause": "Muligt forældet indhold",
                "description": f"Kontrollér om “{row.get('title') or url}” stadig er aktuel.",
                "recommended_action": (
                    "Kontrollér den viste passage mod aktuelle, officielle "
                    "kilder. Behold teksten uændret, hvis signalet ikke kan "
                    "bekræftes; ellers lever en konkret rettelse."
                ),
                "experiment_type": "content_update",
                "forced_content_mode": "existing_section",
                "priority": priority_label(total_score),
                "total_score": total_score,
                "plausible_change": 0.0,
                "search_console_change": "Aktualitetskontrol af lagret sideindhold",
                "explanation": (
                    f"Status: {audit['status_label']}. Automatisk analyse må "
                    "ikke stå alene; oplysningerne skal verificeres."
                ),
                "confidence": "middel",
                "estimated_minutes": 25,
                "completion_criterion": (
                    "Den konkrete passage er verificeret, og en nødvendig "
                    "rettelse er godkendt eller kontrollen er afvist."
                ),
                "measurement_method": (
                    "Hvis teksten ændres, følges siden i det normale "
                    "28-dages målingsflow."
                ),
                "freshness_evidence": audit,
            })
    return sorted(
        candidates,
        key=lambda item: (
            -float(item["total_score"]), item["website"], item["target_url"]
        ),
    )


def _age_years(value: Any, today: date) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            parsed = date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return max(0, (today - parsed).days // 365)


def _first_match(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _passage(text: str, needle: str, radius: int = 140) -> str:
    position = text.casefold().find(str(needle).casefold())
    if position < 0:
        return ""
    start = max(0, position - radius)
    end = min(len(text), position + len(str(needle)) + radius)
    return " ".join(text[start:end].split())
