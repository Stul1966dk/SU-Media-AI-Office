"""Approval-only title and meta optimization pipeline."""

import json
import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

from core.action_logging import log_action
from core.decision_engine import DecisionEngine
from core.seo_experiment_engine import SEOExperimentEngine
from core.workflow_status import DRAFT_TRANSITIONS, validate_transition


USER_AGENT = "SU-Media-AI-Office/1.0 (public read-only analysis)"
SPAM_WORDS = {
    "garanteret", "verdens bedste", "helt fantastisk", "mirakel",
    "nummer 1", "billigst",
}


class TitleOptimizationValidationError(ValueError):
    """A sanitized model response could not become usable proposals."""

    def __init__(
        self, message: str, *, missing_fields: list[str] | None = None,
        phase: str = "validation",
    ) -> None:
        self.missing_fields = missing_fields or []
        self.phase = phase
        detail = message
        if self.missing_fields:
            detail += " Manglende felter: " + ", ".join(self.missing_fields)
        super().__init__(detail)


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.meta = ""
        self.h1 = ""
        self.canonical = ""
        self.schema: list[str] = []
        self.links: list[str] = []
        self.text: list[str] = []
        self.sections: list[dict[str, str]] = []
        self._capture = ""
        self._section_tag = ""
        self._section_text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag in {"title", "h1"}:
            self._capture = tag
        if tag in {"h1", "h2", "h3", "p", "li"}:
            self._section_tag = tag
            self._section_text = []
        elif tag == "meta" and values.get("name", "").lower() == "description":
            self.meta = values.get("content", "").strip()
        elif tag == "link" and "canonical" in values.get("rel", "").lower():
            self.canonical = urljoin(self.base_url, values.get("href", ""))
        elif tag == "a" and values.get("href"):
            self.links.append(urljoin(self.base_url, values["href"]))
        if values.get("type") == "application/ld+json":
            self.schema.append("JSON-LD")
        if values.get("itemtype"):
            self.schema.append(values["itemtype"].rstrip("/").split("/")[-1])

    def handle_endtag(self, tag: str) -> None:
        if tag == self._capture:
            self._capture = ""
        if tag == self._section_tag:
            text = " ".join(self._section_text).strip()
            if text:
                self.sections.append({"element": tag, "text": text})
            self._section_tag = ""
            self._section_text = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        self.text.append(text)
        if self._section_tag:
            self._section_text.append(text)
        if self._capture == "title":
            self.title += (" " if self.title else "") + text
        elif self._capture == "h1":
            self.h1 += (" " if self.h1 else "") + text


class TitleOptimizer:
    """Create reviewed proposals and approval-gated experiments."""

    def __init__(
        self, *, database: Any, website_registry: Any, ai_service: Any,
        session: Any | None = None, experiment_engine: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.database = database
        self.website_registry = website_registry
        self.ai_service = ai_service
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.experiments = experiment_engine or SEOExperimentEngine(database)
        self.logger = logger or logging.getLogger(__name__)
        self.decision_engine = DecisionEngine(
            database, website_registry, experiment_engine=self.experiments
        )

    def select_candidate(
        self, website_id: str | None = None
    ) -> dict[str, Any] | None:
        candidates = self.decision_engine.rank_candidates(
            self.decision_engine.collect_candidates(website_id)
        )
        eligible = [
            item for item in candidates
            if item["monetized"]
            and 3 <= item["current_position"] <= 15
            and item["current_impressions"] >= 50
            and item["current_ctr"] < .05
            and not self.experiments.is_url_locked(item["target_url"])
            and not self._has_open_title_draft(item["target_url"])
        ]
        if not eligible:
            return None
        item = eligible[0]
        return {
            "website": item["website"], "target_url": item["target_url"],
            "target_query": item["target_query"],
            "clicks": item["current_clicks"],
            "impressions": item["current_impressions"],
            "ctr": item["current_ctr"], "position": item["current_position"],
            "period": self._latest_period(
                item["website"], item["target_url"]
            ),
            "reason": item["expected_effect_reason"],
            "confidence": item["confidence"],
        }

    def analyze_current_snippet(
        self, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        """Read one public page without login, cookies, or mutation."""
        response = self.session.get(
            candidate["target_url"], timeout=15, allow_redirects=True
        )
        response.raise_for_status()
        parser = _PageParser(response.url)
        parser.feed(response.text[:2_000_000])
        domain = urlsplit(response.url).netloc.lower().removeprefix("www.")
        internal_links = sum(
            urlsplit(link).netloc.lower().removeprefix("www.") == domain
            for link in parser.links
        )
        return {
            "title": parser.title.strip(), "meta_description": parser.meta,
            "h1": parser.h1.strip(), "canonical": parser.canonical,
            "content_excerpt": " ".join(parser.text).strip()[:3000],
            "content_sections": parser.sections[:40],
            "word_count": len(re.findall(r"\b[\wæøåÆØÅ-]+\b",
                                         " ".join(parser.text))),
            "internal_links": internal_links,
            "schema": sorted(set(parser.schema)),
        }

    def analyze_competitors(
        self, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        """Return safe optional SERP evidence without prohibited scraping."""
        return {
            "competitors": [],
            "limitations": [
                "Ingen lovlig offentlig SERP-kilde er konfigureret. "
                "Forslagene er derfor lavet uden konkurrentdata."
            ],
        }

    def generate_title_proposals(
        self, candidate: dict[str, Any], page: dict[str, Any],
        competitors: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate, validate, review, and at most once repair proposals."""
        response = self.ai_service.generate_response(
            self._prompt(candidate, page, competitors)
        )
        self._log_response_structure(response.text, "initial")
        try:
            value = self._validate_json(response.text, candidate, page)
            review = self.review_proposals(value, page=page)
            if not review["approved"]:
                raise TitleOptimizationValidationError(
                    "; ".join(review["errors"]), phase="review"
                )
        except (
            TitleOptimizationValidationError, TypeError, json.JSONDecodeError
        ) as error:
            self.logger.warning(
                "Title Optimization initial validering fejlede: %s: %s",
                type(error).__name__, str(error)[:300],
            )
            repaired = self.ai_service.generate_response(
                self._repair_prompt(response.text, error, candidate, page)
            )
            self._log_response_structure(repaired.text, "repair")
            try:
                value = self._validate_json(repaired.text, candidate, page)
                review = self.review_proposals(value, page=page)
                if not review["approved"]:
                    raise TitleOptimizationValidationError(
                        "Reviewer afviste reparationsforslaget: "
                        + "; ".join(review["errors"]), phase="repair_review"
                    )
            except (
                TitleOptimizationValidationError, TypeError,
                json.JSONDecodeError
            ) as repair_error:
                self.logger.error(
                    "Title Optimization repair validering fejlede: %s: %s",
                    type(repair_error).__name__, str(repair_error)[:300],
                )
                if isinstance(
                    repair_error, TitleOptimizationValidationError
                ):
                    raise
                raise TitleOptimizationValidationError(
                    f"{type(repair_error).__name__}: "
                    f"{str(repair_error)[:200]}",
                    phase="repair",
                ) from None
        value["title_proposals"] = review["accepted_titles"]
        value["meta_proposals"] = review["accepted_metas"]
        value["recommended_title_index"] = self._adjust_recommendation(
            value["recommended_title_index"],
            review["accepted_title_indices"],
        )
        value["recommended_meta_index"] = self._adjust_recommendation(
            value["recommended_meta_index"],
            review["accepted_meta_indices"],
        )
        value["reviewer"] = review
        value["page_analysis"] = {
            **page, "search_console": {
                "clicks": candidate["clicks"],
                "impressions": candidate["impressions"],
                "ctr": candidate["ctr"],
                "position": candidate["position"],
                "period": candidate["period"],
                "reason": candidate["reason"],
            },
        }
        value["analysis"]["limitations"] = list(
            value["analysis"].get("limitations") or []
        ) + competitors["limitations"]
        return value

    def generate_meta_proposals(
        self, candidate: dict[str, Any], page: dict[str, Any],
        competitors: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Compatibility method returning the combined generation's metas."""
        return self.generate_title_proposals(
            candidate, page, competitors
        )["meta_proposals"]

    def review_proposals(
        self, value: dict[str, Any], *, page: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        accepted_titles, accepted_title_indices = [], []
        accepted_metas, accepted_meta_indices = [], []
        rejected_titles, rejected_metas = [], []
        seen_titles, seen_metas = set(), set()
        seen_meta_openings: set[str] = set()
        overview_ctas = 0
        query = value["target_query"].lower().strip()
        intent = (value.get("analysis") or {}).get("search_intent") or {}
        for index, proposal in enumerate(value["title_proposals"]):
            reviewed, reasons, corrections = self._review_one(
                proposal, kind="title", query=query
            )
            reasons.extend(self._grounding_issues(
                reviewed["text"], page or {}, intent
            ))
            normalized = reviewed["text"].casefold()
            if normalized in seen_titles:
                reasons.append("Forslaget overlapper med et tidligere titleforslag.")
            if reasons:
                rejected_titles.append({
                    "index": index, "proposal": proposal, "reasons": reasons,
                })
            else:
                seen_titles.add(normalized)
                if corrections:
                    reviewed["reviewer_corrections"] = corrections
                accepted_titles.append(reviewed)
                accepted_title_indices.append(index)
        for index, proposal in enumerate(value["meta_proposals"]):
            reviewed, reasons, corrections = self._review_one(
                proposal, kind="meta", query=""
            )
            reasons.extend(self._grounding_issues(
                reviewed["text"], page or {}, intent
            ))
            normalized = reviewed["text"].casefold()
            if normalized in seen_metas:
                reasons.append(
                    "Forslaget overlapper med en tidligere metabeskrivelse."
                )
            opening = self._meta_opening(reviewed["text"])
            if opening and opening in seen_meta_openings:
                reasons.append(
                    "Metabeskrivelsen starter som et tidligere forslag."
                )
            uses_overview = normalized.startswith("få overblik")
            if uses_overview and overview_ctas:
                reasons.append(
                    'Kun ét forslag må bruge CTA-starten "Få overblik".'
                )
            if reasons:
                rejected_metas.append({
                    "index": index, "proposal": proposal, "reasons": reasons,
                })
            else:
                seen_metas.add(normalized)
                if opening:
                    seen_meta_openings.add(opening)
                if uses_overview:
                    overview_ctas += 1
                if corrections:
                    reviewed["reviewer_corrections"] = corrections
                accepted_metas.append(reviewed)
                accepted_meta_indices.append(index)
        errors = []
        if not accepted_titles:
            errors.append("Alle titleforslag blev forkastet.")
        if not accepted_metas:
            errors.append("Alle metabeskrivelser blev forkastet.")
        approved = bool(accepted_titles and accepted_metas)
        return {
            "approved": approved, "errors": errors,
            "status": "Godkendt" if approved else "Afvist",
            "accepted_titles": accepted_titles,
            "accepted_metas": accepted_metas,
            "accepted_title_indices": accepted_title_indices,
            "accepted_meta_indices": accepted_meta_indices,
            "rejected_titles": rejected_titles,
            "rejected_metas": rejected_metas,
            "summary": (
                f"{len(accepted_titles)} titleforslag og "
                f"{len(accepted_metas)} metabeskrivelser blev godkendt. "
                f"{len(rejected_titles) + len(rejected_metas)} forslag "
                "blev forkastet."
            ),
        }

    @classmethod
    def _review_one(
        cls, proposal: dict[str, Any], *, kind: str, query: str,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        reviewed = {
            **proposal, "text": str(proposal.get("text", "")).strip()
        }
        text = reviewed["text"]
        reasons, corrections = [], []
        minimum, maximum = (25, 70) if kind == "title" else (70, 180)
        label = "Title" if kind == "title" else "Metabeskrivelsen"
        if maximum < len(text) <= maximum + 5:
            shortened = cls._shorten(text, maximum)
            if len(shortened) >= minimum:
                reviewed["text"] = text = shortened
                corrections.append(
                    f"{label} blev automatisk afkortet til {len(text)} tegn."
                )
        if len(text) < minimum:
            reasons.append(f"{label} er kortere end {minimum} tegn.")
        elif len(text) > maximum:
            reasons.append(f"{label} er længere end {maximum} tegn.")
        if cls._spam(text):
            reasons.append(f"{label} indeholder spam eller superlativer.")
        if cls._mentions_price(text):
            reasons.append(
                f"{label} må ikke omtale priser, beløb eller valuta."
            )
        if kind == "title" and query and not cls._query_relevant(text, query):
            reasons.append("Titlen matcher ikke det primære søgeord tilstrækkeligt.")
        return reviewed, reasons, corrections

    @staticmethod
    def _shorten(text: str, maximum: int) -> str:
        shortened = text[:maximum + 1].rstrip()
        if len(text) > maximum and " " in shortened:
            shortened = shortened.rsplit(" ", 1)[0].rstrip(" –:,-")
        return shortened[:maximum].rstrip(" –:,-")

    @staticmethod
    def _query_relevant(text: str, query: str) -> bool:
        words = [
            word for word in re.findall(r"[\wæøå]+", query.casefold())
            if len(word) > 2
        ]
        if not words:
            return True
        normalized = text.casefold()
        matches = sum(word in normalized for word in words)
        return matches >= max(1, (len(words) + 1) // 2)

    @staticmethod
    def _meta_opening(text: str) -> str:
        words = re.findall(r"[\wæøå]+", str(text).casefold())
        return " ".join(words[:3])

    @staticmethod
    def _grounding_issues(
        text: str,
        page: dict[str, Any],
        intent: dict[str, Any],
    ) -> list[str]:
        """Reject strong promises unsupported by page content or intent."""
        # Legacy callers may review wording without supplying the page snapshot.
        # Grounding requires evidence to compare against, so keep those reviews
        # backwards compatible instead of treating absent context as a rejection.
        if not page and not intent:
            return []
        normalized = str(text).casefold()
        page_text = " ".join(str(page.get(field) or "") for field in (
            "title", "meta_description", "h1", "content_excerpt",
        )).casefold()
        intent_type = str(intent.get("type") or "")
        issues: list[str] = []
        claims = (
            (
                ("sammenlign", "sammenligning", " vs "),
                "comparison",
                "Forslaget lover en sammenligning, som siden ikke dokumenterer.",
            ),
            (
                ("beregn", "beregner", "test dit", "tjek dit resultat"),
                "tool",
                "Forslaget lover et værktøj, som siden ikke dokumenterer.",
            ),
            (
                ("køb", "bestil", "læg i kurv", "shop"),
                "transactional",
                "Forslaget lover en købshandling, som siden ikke dokumenterer.",
            ),
        )
        for markers, required_intent, message in claims:
            if not any(marker in normalized for marker in markers):
                continue
            supported = (
                intent_type == required_intent
                or any(marker in page_text for marker in markers)
            )
            if not supported:
                issues.append(message)
        return issues

    @staticmethod
    def _adjust_recommendation(
        original_index: int, accepted_indices: list[int]
    ) -> int:
        return (
            accepted_indices.index(original_index)
            if original_index in accepted_indices else 0
        )

    def create_approval_draft(
        self, result: dict[str, Any], competitors: dict[str, Any]
    ) -> int:
        return self.database.create_title_optimization_draft(
            result, competitors["competitors"]
        )

    def run(self, website_id: str | None = None) -> int:
        candidate = self.select_candidate(website_id)
        if not candidate:
            raise ValueError("Ingen egnet URL opfylder title-kriterierne.")
        return self.run_for_candidate(candidate)

    def run_for_candidate(self, candidate: dict[str, Any]) -> int:
        """Create a draft for an explicitly selected queue candidate."""
        page = self.analyze_current_snippet(candidate)
        competitors = self.analyze_competitors(candidate)
        result = self.generate_title_proposals(candidate, page, competitors)
        return self.create_approval_draft(result, competitors)

    def approve_draft(
        self, draft_id: int, selected_title: str, selected_meta: str
    ) -> dict[str, int]:
        """Create one approval-pending task and planned experiment."""
        draft = self._draft(draft_id)
        if draft["status"] in {"converted_to_experiment", "approved"}:
            if (
                draft["selected_title"].strip() == selected_title.strip()
                and draft["selected_meta"].strip() == selected_meta.strip()
                and draft.get("project_id")
                and draft.get("task_id")
                and draft.get("experiment_id")
            ):
                return {
                    "project_id": draft["project_id"],
                    "task_id": draft["task_id"],
                    "experiment_id": draft["experiment_id"],
                }
            raise ValueError(
                "Kladde er allerede godkendt med en anden ændring."
            )
        if draft["status"] != "awaiting_approval":
            raise ValueError("Kun en kladde, der afventer godkendelse, kan godkendes.")
        if not selected_title.strip() or not selected_meta.strip():
            raise ValueError("Valgt title og metabeskrivelse må ikke være tom.")
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        project_id = self.database.create_project_record({
            "website_id": draft["website_id"],
            "title": f"Title-optimering: {draft['target_url']}",
            "description": "Godkendt forslag afventer manuel implementering.",
            "status": "planning", "priority": "high",
            "expected_effect": draft["expected_effect"],
            "created_at": timestamp,
        })
        subproject_id = self.database.create_subproject_record({
            "project_id": project_id, "title": "Afventer implementering",
            "description": "Publicér kun efter manuel handling uden for AI Office.",
            "status": "planning", "sequence": 1, "created_at": timestamp,
        })
        task_id = self.database.create_task_record({
            "subproject_id": subproject_id,
            "website_id": draft["website_id"],
            "title": f"Implementér godkendt title på {draft['target_url']}",
            "description": (
                f"Title: {selected_title}\nMeta: {selected_meta}\n"
                "Markér først som implementeret efter manuel publicering."
            ),
            "reason": "Forslaget er godkendt af brugeren.",
            "assigned_agent": "Webmaster", "estimated_minutes": 30,
            "expected_effect": draft["expected_effect"],
            "measurement_method": draft["measurement_method"],
            "priority_score": 75, "status": "planning",
            "depends_on_task_id": None, "created_at": timestamp,
        })
        decision = {
            "website": draft["website_id"], "target_url": draft["target_url"],
            "target_query": draft["target_query"],
            "experiment_type": "title_meta",
            "experiment_goal": "Øg CTR mindst 15 procent uden placeringsfald.",
            "expected_effect_reason": draft["expected_effect"],
            "task_description": (
                f"Title: {selected_title}. Meta: {selected_meta}."
            ),
            "goal_metric": "ctr", "goal_direction": "increase",
            "target_change_pct": 15, "waiting_period_days": 28,
            "confidence": draft["confidence"],
        }
        experiment_id = self.experiments.create_experiment(
            decision, project_id=project_id, task_id=task_id
        )
        baseline = self.experiments.calculate_baseline(
            draft["website_id"], draft["target_url"], draft["target_query"]
        )
        self.database.update_seo_experiment(experiment_id, baseline)
        self.database.save_approved_change({
            "website_id": draft["website_id"],
            "change_type": "title_meta",
            "target_url": draft["target_url"],
            "target_query": draft["target_query"],
            "current_title": draft["current_title"],
            "approved_title": selected_title.strip(),
            "current_meta": draft["current_meta"],
            "approved_meta": selected_meta.strip(),
            "hypothesis": decision["experiment_goal"],
            "reason": (
                (draft.get("analysis") or {}).get("reason")
                or "Forslaget er valgt og godkendt af brugeren."
            ),
            "expected_effect": draft["expected_effect"],
            "project_id": project_id, "task_id": task_id,
            "experiment_id": experiment_id,
            "source_draft_id": draft_id,
            "status": "awaiting_implementation",
            "approved_at": timestamp,
        })
        self.database.update_title_optimization_draft(draft_id, {
            "selected_title": selected_title.strip(),
            "selected_meta": selected_meta.strip(),
            "status": "converted_to_experiment",
            "project_id": project_id, "task_id": task_id,
            "experiment_id": experiment_id, "approved_at": timestamp,
        })
        log_action(
            self.logger, action="approve_title_change",
            website=draft["website_id"], target_url=draft["target_url"],
            record_ids={
                "draft_id": draft_id, "project_id": project_id,
                "task_id": task_id, "experiment_id": experiment_id,
            },
            previous_status=draft["status"],
            new_status="converted_to_experiment",
        )
        return {
            "project_id": project_id, "task_id": task_id,
            "experiment_id": experiment_id,
        }

    def reject_draft(self, draft_id: int) -> None:
        draft = self._draft(draft_id)
        if draft["status"] == "rejected":
            return
        validate_transition(
            DRAFT_TRANSITIONS, draft["status"], "rejected", "titlekladde"
        )
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.database.update_title_optimization_draft(draft_id, {
            "status": "rejected", "rejected_at": timestamp,
        })

    def mark_implemented(self, draft_id: int) -> dict[str, Any]:
        draft = self._draft(draft_id)
        if draft["status"] == "approved" and draft.get("experiment_id"):
            return self.experiments._required(draft["experiment_id"])
        if draft["status"] != "converted_to_experiment":
            raise ValueError("Kladde er ikke godkendt og klar til implementering.")
        experiment = self.experiments.start_experiment(
            draft["experiment_id"], approved=True
        )
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.database.update_title_optimization_draft(draft_id, {
            "status": "approved", "implemented_at": timestamp,
        })
        approved = self.database.get_approved_changes(
            source_draft_id=draft_id
        )
        if approved:
            self.database.update_approved_change_status(
                approved[0]["id"], "measurement_period",
                implemented_at=timestamp,
            )
        log_action(
            self.logger, action="mark_title_change_implemented",
            website=draft["website_id"], target_url=draft["target_url"],
            record_ids={
                "draft_id": draft_id,
                "experiment_id": draft["experiment_id"],
            },
            previous_status=draft["status"], new_status="approved",
        )
        return experiment

    def _has_open_title_draft(self, target_url: str) -> bool:
        return any(
            item["target_url"] == target_url
            and item["status"] in {
                "draft", "awaiting_approval", "approved",
                "converted_to_experiment",
            }
            for item in self.database.get_title_optimization_drafts()
        )

    def _latest_period(self, website_id: str, target_url: str) -> str:
        rows = self.database.get_search_console_dimensions(
            "page", website_id=website_id, page_url=target_url
        )
        latest = max(rows, key=lambda item: item["period_end"])
        return f"{latest['period_start']} – {latest['period_end']}"

    def _draft(self, draft_id: int) -> dict[str, Any]:
        draft = self.database.get_title_optimization_draft(draft_id)
        if not draft:
            raise ValueError(f"Title-kladde {draft_id} findes ikke.")
        return draft

    @staticmethod
    def _spam(text: str) -> bool:
        normalized = text.lower()
        return any(word in normalized for word in SPAM_WORDS) or (
            normalized.count("!") > 1
        )

    @staticmethod
    def _mentions_price(text: str) -> bool:
        return bool(re.search(
            r"\bpris(?:er|en|erne)?\b"
            r"|\b\d+(?:[.,]\d+)?\s*(?:kr\.?|dkk|eur|usd)\b"
            r"|[€£$]",
            str(text).casefold(),
        ))

    @staticmethod
    def _prompt(
        candidate: dict[str, Any], page: dict[str, Any],
        competitors: dict[str, Any],
    ) -> str:
        schema = {
            "website": "", "target_url": "", "target_query": "",
            "current_title": "", "current_meta": "",
            "analysis": {
                "problem": "", "evidence": [], "limitations": [],
                "search_intent": {
                    "type": "guide|comparison|tool|transactional|"
                            "navigational|informational",
                    "summary": "",
                    "evidence": [],
                    "confidence": 0,
                    "ambiguous": False,
                },
            },
            "title_proposals": [{
                "text": "", "reason": "", "strengths": [], "risks": []
            }],
            "meta_proposals": [{
                "text": "", "reason": "", "strengths": [], "risks": []
            }],
            "recommended_title_index": 0, "recommended_meta_index": 0,
            "confidence": 0, "expected_effect": "",
            "measurement_method": "",
        }
        cta_guidance = TitleOptimizer._cta_guidance(candidate, page)
        return (
            "Returnér kun gyldig JSON efter dette schema. Skriv almindeligt "
            "dansk. Returnér præcis tre forskellige title-forslag og tre "
            "forskellige metabeskrivelser. Undgå clickbait, keyword stuffing, "
            "superlativer og udokumenterede påstande. Overskriv ikke den "
            "nuværende title eller meta. Titles og metabeskrivelser må aldrig "
            "omtale priser, beløb eller valuta, fordi priser ændrer sig. "
            "Klassificér først søgeintentionen ud fra query, URL, title, H1 "
            "og sideudsnit. Forklar kort brugerens mål og den konkrete evidens. "
            "Forslagene skal bevare intentionen og må kun love indhold, "
            "sammenligninger, værktøjer eller handlinger, som sideanalysen "
            "dokumenterer. "
            "De tre metabeskrivelser skal have "
            "forskellige åbninger og handlingsord, som passer til sidens "
            "søgeintention. Brug højst 'Få overblik' i ét forslag og undgå "
            "det helt, hvis en mere præcis handling findes. CTA-retninger "
            f"til netop denne side: {', '.join(cta_guidance)}. Schema: "
            + json.dumps(schema, ensure_ascii=False)
            + "\nKandidat: " + json.dumps(candidate, ensure_ascii=False)
            + "\nOffentlig sideanalyse: " + json.dumps(page, ensure_ascii=False)
            + "\nSERP-begrænsninger: "
            + json.dumps(competitors["limitations"], ensure_ascii=False)
        )

    @staticmethod
    def _repair_prompt(
        invalid: str, error: Exception, candidate: dict[str, Any],
        page: dict[str, Any],
    ) -> str:
        return (
            "Reparer svaret én gang. Returnér kun JSON med præcis tre titles "
            "og tre meta descriptions. Bevar website, URL, query og de "
            "offentlige fakta. Metabeskrivelserne skal starte forskelligt, "
            "bruge varierede intent-baserede CTA'er og højst én må starte "
            'med "Få overblik". Fjern enhver omtale af priser, beløb og '
            "valuta. Bevar eller reparer search_intent med type, summary, "
            "evidence, confidence og ambiguous. Afvis løfter, der ikke findes "
            "i sideanalysen. Fejl: "
            f"{type(error).__name__}: {str(error)[:180]}\n"
            f"Kandidat: {json.dumps(candidate, ensure_ascii=False)}\n"
            f"Side: {json.dumps(page, ensure_ascii=False)}\n"
            "Ugyldigt svar:\n" + invalid
        )

    @staticmethod
    def _cta_guidance(
        candidate: dict[str, Any], page: dict[str, Any]
    ) -> list[str]:
        """Return varied CTA directions matched to likely search intent."""
        context = " ".join(str(value or "") for value in (
            candidate.get("target_query"),
            candidate.get("target_url"),
            page.get("title"),
            page.get("h1"),
        )).casefold()
        groups = (
            (
                ("sammenlign", "bedste", "pris", "billig", "model"),
                [
                    "Sammenlign mulighederne",
                    "Se forskellene",
                    "Find den løsning der passer",
                ],
            ),
            (
                ("beregn", "test", "tjek", "måler", "calculator"),
                [
                    "Prøv beregningen",
                    "Tjek dit resultat",
                    "Se hvad tallene betyder",
                ],
            ),
            (
                ("sådan", "guide", "hvordan", "trin", "opret"),
                [
                    "Følg guiden",
                    "Se hvordan du gør",
                    "Lær de vigtigste trin",
                ],
            ),
        )
        for keywords, directions in groups:
            if any(keyword in context for keyword in keywords):
                return directions
        directions = [
            "Læs den konkrete vejledning",
            "Find det relevante svar",
            "Se dine muligheder",
            "Bliv klogere på valget",
            "Gå direkte til anbefalingerne",
            "Få overblik over emnet",
        ]
        seed = sum(ord(character) for character in context)
        start = seed % len(directions)
        return [
            directions[(start + offset) % len(directions)]
            for offset in range(3)
        ]

    @staticmethod
    def _validate_json(
        text: str, candidate: dict[str, Any], page: dict[str, Any]
    ) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I
            )
        value = json.loads(cleaned)
        if not isinstance(value, dict):
            raise TitleOptimizationValidationError(
                "Modelsvar skal være et JSON-objekt.", phase="root"
            )
        value = TitleOptimizer._normalize_mapping(value, {
            "titles": "title_proposals",
            "title": "title_proposals",
            "seotitle": "title_proposals",
            "titleoptions": "title_proposals",
            "metas": "meta_proposals",
            "meta": "meta_proposals",
            "metadescription": "meta_proposals",
            "metadescriptions": "meta_proposals",
            "metaoptions": "meta_proposals",
            "explanation": "analysis",
            "reason": "analysis",
            "recommendedtitle": "recommended_title_index",
            "recommendedtitleindex": "recommended_title_index",
            "recommendedmeta": "recommended_meta_index",
            "recommendedmetaindex": "recommended_meta_index",
            "expectedeffect": "expected_effect",
            "measurement": "measurement_method",
            "measurementmethod": "measurement_method",
            "confidence": "confidence",
        })
        value["title_proposals"] = TitleOptimizer._proposal_list(
            value.get("title_proposals"), kind="title"
        )
        value["meta_proposals"] = TitleOptimizer._proposal_list(
            value.get("meta_proposals"), kind="meta"
        )
        critical_missing = []
        if len(value["title_proposals"]) != 3:
            critical_missing.append("title_proposals (præcis 3)")
        if len(value["meta_proposals"]) != 3:
            critical_missing.append("meta_proposals (præcis 3)")
        if critical_missing:
            raise TitleOptimizationValidationError(
                "Modelsvaret mangler kritiske forslag.",
                missing_fields=critical_missing, phase="critical_fields",
            )
        safe_defaults = {
            "analysis": {
                "problem": "Siden har dokumenterede visninger og en CTR "
                           "under den forventede mulighed.",
                "evidence": [
                    f"{candidate['impressions']} visninger, "
                    f"{candidate['clicks']} klik og "
                    f"{candidate['ctr']*100:.2f}% CTR."
                ],
                "limitations": [],
            },
            "recommended_title_index": 0,
            "recommended_meta_index": 0,
            "confidence": candidate.get("confidence", 60),
            "expected_effect": (
                "Mulighed for højere CTR uden at ændre sidens indhold."
            ),
            "measurement_method": (
                "Sammenlign klik, visninger, CTR og placering efter 28 dage."
            ),
        }
        for field, default in safe_defaults.items():
            if value.get(field) in (None, ""):
                value[field] = default
        if not isinstance(value["analysis"], dict):
            value["analysis"] = safe_defaults["analysis"]
        value["analysis"].setdefault("problem", "")
        value["analysis"].setdefault("evidence", [])
        value["analysis"].setdefault("limitations", [])
        value["analysis"]["search_intent"] = (
            TitleOptimizer._normalize_search_intent(
                value["analysis"].get("search_intent"),
                candidate,
                page,
            )
        )
        value.update({
            "website": candidate["website"],
            "target_url": candidate["target_url"],
            "target_query": candidate["target_query"],
            "current_title": page["title"],
            "current_meta": page["meta_description"],
        })
        for field in ("title_proposals", "meta_proposals"):
            for proposal in value[field]:
                if not isinstance(proposal, dict) or not proposal.get("text"):
                    raise TitleOptimizationValidationError(
                        f"{field} indeholder et forslag uden tekst.",
                        missing_fields=[f"{field}.text"],
                        phase="proposal",
                    )
                for key, default in (
                    ("reason", ""), ("strengths", []), ("risks", [])
                ):
                    proposal.setdefault(key, default)
        for field in ("recommended_title_index", "recommended_meta_index"):
            try:
                value[field] = int(value[field])
            except (TypeError, ValueError):
                value[field] = 0
            if value[field] not in {0, 1, 2}:
                value[field] = 0
        try:
            value["confidence"] = max(
                0, min(100, int(float(value["confidence"])))
            )
        except (TypeError, ValueError):
            value["confidence"] = int(candidate.get("confidence", 60))
        if isinstance(value["analysis"], str):
            value["analysis"] = {
                "problem": value["analysis"], "evidence": [],
                "limitations": [],
            }
        if not isinstance(value["analysis"], dict):
            value["analysis"] = safe_defaults["analysis"]
        value["analysis"].setdefault("problem", "")
        value["analysis"].setdefault("evidence", [])
        value["analysis"].setdefault("limitations", [])
        if isinstance(value["analysis"]["evidence"], str):
            value["analysis"]["evidence"] = [
                value["analysis"]["evidence"]
            ]
        if isinstance(value["analysis"]["limitations"], str):
            value["analysis"]["limitations"] = [
                value["analysis"]["limitations"]
            ]
        return value

    @staticmethod
    def _normalize_search_intent(
        model_value: Any,
        candidate: dict[str, Any],
        page: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = TitleOptimizer._infer_search_intent(candidate, page)
        if not isinstance(model_value, dict):
            return fallback
        allowed = {
            "guide", "comparison", "tool", "transactional",
            "navigational", "informational",
        }
        intent_type = str(model_value.get("type") or "").strip().casefold()
        if intent_type not in allowed:
            return fallback
        summary = str(model_value.get("summary") or "").strip()
        evidence = model_value.get("evidence")
        if not summary or not isinstance(evidence, list) or not evidence:
            return fallback
        try:
            confidence = max(
                0, min(100, int(float(model_value.get("confidence", 0))))
            )
        except (TypeError, ValueError):
            confidence = fallback["confidence"]
        return {
            "type": intent_type,
            "summary": summary,
            "evidence": [
                str(item).strip() for item in evidence
                if str(item).strip()
            ][:5],
            "confidence": confidence,
            "ambiguous": bool(
                model_value.get("ambiguous") or confidence < 65
            ),
        }

    @staticmethod
    def _infer_search_intent(
        candidate: dict[str, Any], page: dict[str, Any]
    ) -> dict[str, Any]:
        context = " ".join(str(value or "") for value in (
            candidate.get("target_query"),
            candidate.get("target_url"),
            page.get("title"),
            page.get("h1"),
            page.get("content_excerpt"),
        )).casefold()
        groups = (
            (
                "tool", ("beregn", "beregner", "calculator", "test din"),
                "Brugeren vil udføre en beregning eller test.",
            ),
            (
                "comparison", ("sammenlign", " vs ", "testvinder", "bedste"),
                "Brugeren vil sammenligne muligheder før et valg.",
            ),
            (
                "guide", ("hvordan", "sådan", "guide", "trin for trin"),
                "Brugeren vil have en praktisk forklaring eller vejledning.",
            ),
            (
                "transactional", ("køb", "bestil", "shop", "læg i kurv"),
                "Brugeren vil gennemføre eller forberede et køb.",
            ),
            (
                "navigational", ("login", "kontakt", "kundeservice"),
                "Brugeren vil finde en bestemt funktion eller destination.",
            ),
        )
        for intent_type, markers, summary in groups:
            matched = [marker.strip() for marker in markers if marker in context]
            if matched:
                return {
                    "type": intent_type,
                    "summary": summary,
                    "evidence": [
                        f"Query, URL eller sideindhold indeholder: "
                        f"{', '.join(matched[:3])}."
                    ],
                    "confidence": 80 if len(matched) > 1 else 70,
                    "ambiguous": False,
                }
        return {
            "type": "informational",
            "summary": "Brugeren søger viden om sidens primære emne.",
            "evidence": [
                "Der blev ikke fundet et stærkt guide-, sammenlignings-, "
                "værktøjs-, købs- eller navigationssignal."
            ],
            "confidence": 55,
            "ambiguous": True,
        }

    @staticmethod
    def _normalize_mapping(
        values: dict[str, Any], aliases: dict[str, str]
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            canonical = aliases.get(normalized, key)
            if canonical not in result or result[canonical] in (None, "", []):
                result[canonical] = value
        return result

    @staticmethod
    def _proposal_list(value: Any, *, kind: str) -> list[dict[str, Any]]:
        if value in (None, ""):
            return []
        if isinstance(value, (str, dict)):
            value = [value]
        if not isinstance(value, list):
            return []
        text_aliases = (
            {"text", "title", "seo_title", "seoTitle"}
            if kind == "title" else
            {"text", "meta", "meta_description", "metaDescription"}
        )
        result = []
        for item in value:
            if isinstance(item, str):
                result.append({
                    "text": item, "reason": "", "strengths": [], "risks": []
                })
                continue
            if not isinstance(item, dict):
                continue
            proposal = TitleOptimizer._normalize_mapping(item, {
                **{
                    re.sub(r"[^a-z0-9]", "", alias.lower()): "text"
                    for alias in text_aliases
                },
                "explanation": "reason", "reason": "reason",
                "strength": "strengths", "benefits": "strengths",
                "risk": "risks",
            })
            proposal.setdefault("reason", "")
            proposal.setdefault("strengths", [])
            proposal.setdefault("risks", [])
            if isinstance(proposal["strengths"], str):
                proposal["strengths"] = [proposal["strengths"]]
            if isinstance(proposal["risks"], str):
                proposal["risks"] = [proposal["risks"]]
            result.append(proposal)
        return result

    def _log_response_structure(self, text: str, phase: str) -> None:
        """Log only keys, container lengths, and scalar types."""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(
                    r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I
                )
            structure = self._json_structure(json.loads(cleaned))
        except Exception as error:
            structure = {"parse_error": type(error).__name__}
        self.logger.info(
            "Title Optimization modelsvarstruktur (%s): %s",
            phase, json.dumps(structure, ensure_ascii=False),
        )

    @classmethod
    def _json_structure(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): cls._json_structure(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return {
                "type": "list", "length": len(value),
                "item": cls._json_structure(value[0]) if value else None,
            }
        return type(value).__name__
