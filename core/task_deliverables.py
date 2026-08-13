"""Concrete, reviewable work drafts for every traffic recommendation."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit


DELIVERABLE_TYPES = {
    "title_meta", "content_update", "internal_links",
    "technical_fix", "schema", "traffic_analysis", "monetization",
}

MONETIZATION_OPPORTUNITY_TYPES = {
    "affiliate_links", "cta", "comparison_table", "product_box",
}


def generate_task_deliverable(
    recommendation: dict[str, Any],
    *,
    ai_service: Any,
    public_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ask AI for one bounded deliverable and validate its structure."""
    tools = (
        [{"type": "web_search"}]
        if recommendation.get("freshness_verification")
        else None
    )
    prompt = _prompt(recommendation, public_context or [])
    response = (
        ai_service.generate_response(prompt, tools=tools)
        if tools
        else ai_service.generate_response(prompt)
    )
    context = public_context or []
    deliverable = validate_task_deliverable(
        response.text,
        expected_target_url=str(recommendation.get("target_url") or ""),
        allowed_source_urls=[
            str(row.get("url") or "")
            for row in context
            if row.get("relation") == "mulig relateret side"
            and row.get("url")
        ],
        evidence_fallback=[
            candidate
            for candidate in (
                [
                    str(row.get("query") or "").strip()
                    for row in (recommendation.get("search_queries") or [])
                ]
                + [str(recommendation.get("target_query") or "").strip()]
            )
            if candidate
        ],
    )
    if deliverable["deliverable_type"] == "content_update":
        validate_content_novelty(
            deliverable,
            public_context=context,
        )
    return deliverable


def validate_task_deliverable(
    text: str,
    *,
    expected_target_url: str = "",
    allowed_source_urls: list[str] | None = None,
    evidence_fallback: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and normalize a model-produced work draft."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Arbejdsudkastet skal være et JSON-objekt.")
    deliverable_type = str(value.get("deliverable_type") or "")
    if deliverable_type not in DELIVERABLE_TYPES:
        raise ValueError("Arbejdsudkastet har en ukendt opgavetype.")
    required_text = ("summary", "recommended_option", "rationale")
    for field in required_text:
        if not str(value.get(field) or "").strip():
            raise ValueError(f"Arbejdsudkastet mangler {field}.")
    for field in ("alternatives", "implementation_steps", "validation_checks"):
        rows = value.get(field)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Arbejdsudkastet mangler {field}.")
        value[field] = [str(row).strip() for row in rows if str(row).strip()]
    if len(value["alternatives"]) < 2:
        raise ValueError("Arbejdsudkastet skal have mindst to alternativer.")
    value["deliverable_type"] = deliverable_type
    value["summary"] = str(value["summary"]).strip()
    value["recommended_option"] = str(value["recommended_option"]).strip()
    if deliverable_type == "title_meta":
        title, meta = split_title_meta_option(value["recommended_option"])
        if mentions_price(title) or mentions_price(meta):
            raise ValueError(
                "Title og meta må ikke omtale priser, beløb eller valuta."
            )
        value["recommended_option"] = format_title_meta_option(title, meta)
    elif deliverable_type == "content_update":
        if not str(value.get("replacement_content") or "").strip():
            value["replacement_content"] = value.get("recommended_option", "")
        evidence = value.get("evidence_queries")
        if not isinstance(evidence, list) or not any(
            str(query).strip() for query in evidence
        ):
            value["evidence_queries"] = list(evidence_fallback or [])
        validate_content_change(value)
        value["recommended_option"] = value["replacement_content"]
    elif deliverable_type == "internal_links":
        validate_internal_link(
            value,
            expected_target_url=expected_target_url,
            allowed_source_urls=allowed_source_urls,
        )
        value["recommended_option"] = value["linked_sentence"]
    elif deliverable_type == "monetization":
        validate_monetization(value)
    value["rationale"] = str(value["rationale"]).strip()
    return value


def validate_content_change(value: dict[str, Any]) -> None:
    """Require a paste-ready, grounded content change."""
    required = (
        "content_location", "current_content", "replacement_content",
        "search_intent", "content_opportunity_type", "missing_topic",
        "duplication_check",
    )
    for field in required:
        if not str(value.get(field) or "").strip():
            raise ValueError(
                f"Indholdsopdateringen mangler det konkrete felt {field}."
            )
        value[field] = str(value[field]).strip()
    if len(value["replacement_content"]) < 80:
        raise ValueError(
            "Den nye tekst er for kort til at være en færdig indholdsleverance."
        )
    placeholders = (
        "skriv selv", "tilføj relevant tekst", "indsæt tekst her",
        "udarbejd et afsnit", "2-3 korte afsnit",
    )
    normalized = value["replacement_content"].casefold()
    if any(placeholder in normalized for placeholder in placeholders):
        raise ValueError(
            "Indholdsopdateringen beder brugeren skrive teksten selv."
        )
    allowed = {
        "existing_section", "new_category", "new_article", "new_blog_post",
    }
    if value["content_opportunity_type"] not in allowed:
        raise ValueError("Indholdsleverancen har en ukendt indholdstype.")
    evidence = value.get("evidence_queries")
    if not isinstance(evidence, list) or not any(
        str(query).strip() for query in evidence
    ):
        raise ValueError(
            "Indholdsleverancen mangler Search Console-søgeord som evidens."
        )
    value["evidence_queries"] = [
        str(query).strip() for query in evidence if str(query).strip()
    ][:10]
    if value["content_opportunity_type"] != "existing_section":
        for field in ("proposed_title", "proposed_slug"):
            if not str(value.get(field) or "").strip():
                raise ValueError(
                    f"Det nye indhold mangler det konkrete felt {field}."
                )
            value[field] = str(value[field]).strip()
        outline = value.get("outline")
        if not isinstance(outline, list) or len(outline) < 3:
            raise ValueError(
                "Det nye indhold skal have en disposition med mindst tre punkter."
            )
        value["outline"] = [
            str(row).strip() for row in outline if str(row).strip()
        ]


def validate_monetization(value: dict[str, Any]) -> None:
    """Require a concrete, paste-ready monetization change for a page.

    The recommended_option is the finished element (a comparison table,
    an affiliate-link plan, a CTA or a product box) that turns existing
    traffic into commission without inventing products or prices.
    """
    required = (
        "content_location", "current_state", "opportunity_type", "evidence",
    )
    for field in required:
        if not str(value.get(field) or "").strip():
            raise ValueError(
                f"Monetiseringsforslaget mangler det konkrete felt {field}."
            )
        value[field] = str(value[field]).strip()
    if value["opportunity_type"] not in MONETIZATION_OPPORTUNITY_TYPES:
        raise ValueError(
            "Monetiseringsforslaget har en ukendt mulighedstype."
        )
    option = str(value.get("recommended_option") or "").strip()
    if len(option) < 40:
        raise ValueError(
            "Monetiseringsforslaget er for kort til at være en færdig ændring."
        )
    normalized = option.casefold()
    placeholders = (
        "skriv selv", "tilføj relevant tekst", "indsæt tekst her",
        "find selv", "indsæt link her", "udfyld selv",
    )
    if any(placeholder in normalized for placeholder in placeholders):
        raise ValueError(
            "Monetiseringsforslaget beder brugeren udfylde det selv."
        )


def validate_content_novelty(
    value: dict[str, Any],
    *,
    public_context: list[dict[str, Any]],
) -> None:
    """Reject irrelevant or substantially duplicated website copy."""
    replacement = str(value.get("replacement_content") or "")
    replacement_tokens = _content_tokens(replacement)
    topic_material = " ".join((
        str(value.get("missing_topic") or ""),
        str(value.get("search_intent") or ""),
        " ".join(str(item) for item in value.get("evidence_queries") or []),
    ))
    topic_tokens = _content_tokens(topic_material) - CONTENT_STOPWORDS
    meaningful_replacement = replacement_tokens - CONTENT_STOPWORDS
    if topic_tokens and not topic_tokens & meaningful_replacement:
        raise ValueError(
            "Den foreslåede tekst matcher ikke det dokumenterede emne eller "
            "søgeintentionen."
        )
    normalized_replacement = _normalized_content_text(replacement)
    for row in public_context:
        existing = _context_content(row)
        if not existing:
            continue
        normalized_existing = _normalized_content_text(existing)
        if (
            len(normalized_replacement) >= 80
            and normalized_replacement in normalized_existing
        ):
            raise ValueError(
                "Den foreslåede tekst findes allerede i websiteindholdet."
            )
        existing_tokens = _content_tokens(existing)
        if len(replacement_tokens) < 8 or len(existing_tokens) < 8:
            continue
        similarity = len(replacement_tokens & existing_tokens) / max(
            1, len(replacement_tokens | existing_tokens)
        )
        if similarity >= 0.82:
            raise ValueError(
                "Den foreslåede tekst ligner eksisterende websiteindhold "
                "for meget."
            )


CONTENT_STOPWORDS = {
    "alle", "anden", "andre", "at", "den", "der", "det", "din", "dit",
    "du", "eller", "en", "er", "et", "for", "fra", "har", "i", "ikke",
    "kan", "med", "og", "om", "på", "se", "sig", "som", "til", "ved",
}


def _normalized_content_text(value: str) -> str:
    return " ".join(re.findall(
        r"[0-9a-zæøå]+", str(value or "").casefold()
    ))


def _content_tokens(value: str) -> set[str]:
    return set(_normalized_content_text(value).split())


def _context_content(row: dict[str, Any]) -> str:
    sections = row.get("content_sections") or []
    section_text = " ".join(
        str(item.get("text") or "")
        for item in sections
        if isinstance(item, dict)
    )
    return " ".join((
        str(row.get("title") or ""),
        str(row.get("h1") or ""),
        str(row.get("content_excerpt") or ""),
        str(row.get("excerpt") or ""),
        section_text,
    )).strip()


def validate_internal_link(
    value: dict[str, Any],
    *,
    expected_target_url: str = "",
    allowed_source_urls: list[str] | None = None,
) -> None:
    """Require one verifiable source-to-destination internal link."""
    required = (
        "source_url", "destination_url", "anchor_text", "link_location",
        "current_sentence", "linked_sentence",
    )
    for field in required:
        if not str(value.get(field) or "").strip():
            raise ValueError(
                f"Det interne linkforslag mangler det konkrete felt {field}."
            )
        value[field] = str(value[field]).strip()
    for field in ("source_url", "destination_url"):
        parsed = urlsplit(value[field])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"Det interne linkforslag har en ugyldig URL i {field}."
            )
    source = _normalized_url(value["source_url"])
    destination = _normalized_url(value["destination_url"])
    if source == destination:
        raise ValueError("Kildesiden og destinationssiden skal være forskellige.")
    if expected_target_url and destination != _normalized_url(
        expected_target_url
    ):
        raise ValueError(
            "Destinationssiden matcher ikke opgavens dokumenterede målside."
        )
    allowed = {
        _normalized_url(url) for url in (allowed_source_urls or []) if url
    }
    if allowed and source not in allowed:
        raise ValueError(
            "Kildesiden findes ikke blandt de dokumenterede relaterede sider."
        )
    if value["anchor_text"].casefold() not in value["linked_sentence"].casefold():
        raise ValueError(
            "Ankerteksten skal fremgå ordret af den færdige linksætning."
        )


def _normalized_url(value: str) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def _natural_danish_topic(
    evidence_queries: list[str], fallback_query: str
) -> str:
    """Turn raw Search Console keywords into a readable Danish intent."""
    queries = [
        " ".join(str(query or "").strip().split())
        for query in evidence_queries
        if str(query or "").strip()
    ]
    query = max(
        queries or [str(fallback_query or "emnet").strip()],
        key=lambda value: (
            sum(
                marker in f" {value.casefold()} "
                for marker in (
                    " hvordan ", " sådan ", " hvad ", " hvorfor ",
                    " kan ", " man ", " jeg ", " du ",
                )
            ),
            len(value.split()),
        ),
    )
    query = re.sub(r"\biphone\b", "iPhone", query, flags=re.IGNORECASE)
    patterns = (
        (
            r"^hvordan\s+deler\s+man\s+(?:sin\s+)?kalender\s+på\s+iPhone$",
            "hvordan du deler en kalender på iPhone",
        ),
        (
            r"^hvordan\s+del(?:er)?\s+man\s+kalender\s+på\s+iPhone$",
            "hvordan du deler en kalender på iPhone",
        ),
        (
            r"^del\s+kalender\s+iPhone$",
            "hvordan du deler en kalender på iPhone",
        ),
    )
    for pattern, replacement in patterns:
        if re.fullmatch(pattern, query, flags=re.IGNORECASE):
            return replacement
    if query.casefold().startswith("hvordan "):
        return query[0].casefold() + query[1:]
    return f"hvordan du finder et klart svar om {query}"


def _fallback_content_copy(natural_topic: str) -> str:
    """Return complete, grammatical copy when the AI call is unavailable."""
    normalized = natural_topic.casefold()
    if "deler en kalender" in normalized and "iphone" in normalized:
        return (
            "Sådan deler du en kalender på iPhone\n\n"
            "Du kan dele en kalender på iPhone med andre, så I kan se og "
            "følge aftaler i den samme kalender. Åbn Kalenderappen, find "
            "den kalender, du vil dele, og vælg muligheden for at tilføje "
            "personer. Send invitationen til de ønskede deltagere, og "
            "kontrollér derefter, at de har adgang til den rigtige kalender."
        )
    return (
        f"Sådan får du svar på spørgsmålet om {natural_topic}\n\n"
        f"Denne sektion forklarer {natural_topic} i et naturligt dansk "
        "sprog. Følg sidens dokumenterede fremgangsmåde trin for trin, og "
        "kontrollér resultatet, før ændringen publiceres."
    )


_BOILERPLATE_MARKERS = (
    "reklamelink",
    "affiliate",
    "annoncelink",
    "kan indeholde reklame",
)


def _is_boilerplate_passage(text: str) -> bool:
    """True for affiliate disclaimers and breadcrumbs — never a real passage.

    These sit right below a heading on many pages (e.g. "Teksten kan indeholde
    reklamelinks", "Hjem › Anmeldelser › …") and must never be proposed as the
    existing text to replace.
    """
    lowered = text.casefold()
    if any(marker in lowered for marker in _BOILERPLATE_MARKERS):
        return True
    if ("›" in text or "»" in text) and lowered.startswith("hjem"):
        return True
    return False


def _select_relevant_passage(
    sections: list[dict[str, Any]], queries: list[str]
) -> tuple[str, str]:
    """Select a real passage below the heading closest to Search Console intent."""
    query_words = {
        word
        for query in queries
        for word in re.findall(r"[\wæøå]+", query.casefold())
        if len(word) > 2
        and word not in {"hvordan", "man", "sin", "den", "det", "på"}
    }
    heading_candidates = [
        (
            index,
            str(section.get("text") or "").strip(),
            (
                len(
                query_words.intersection(
                    re.findall(
                        r"[\wæøå]+",
                        str(section.get("text") or "").casefold(),
                    )
                )
                )
                + (
                    2
                    if str(section.get("text") or "").casefold().startswith(
                        "hvordan "
                    )
                    else 0
                )
                + (
                    1
                    if "fælles" in str(section.get("text") or "").casefold()
                    else 0
                )
                - (
                    2
                    if str(section.get("text") or "").casefold().startswith(
                        "faq "
                    )
                    else 0
                )
            ),
        )
        for index, section in enumerate(sections)
        if section.get("element") in {"h1", "h2", "h3"}
        and str(section.get("text") or "").strip()
    ]
    best_heading = max(
        heading_candidates,
        key=lambda value: (value[2], value[0]),
        default=(-1, "", 0),
    )
    start_index, heading, score = best_heading
    if score <= 0:
        start_index, heading = -1, ""
    passage = next(
        (
            text
            for section in sections[start_index + 1:]
            if section.get("element") in {"p", "li"}
            and len(text := str(section.get("text") or "").strip()) >= 20
            and not _is_boilerplate_passage(text)
        ),
        "",
    )
    return passage, heading


def fallback_task_deliverable(
    recommendation: dict[str, Any],
    public_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a concrete rule-based draft if the AI service is unavailable."""
    query = str(
        recommendation.get("target_query")
        or "det primære søgeord"
    ).strip()
    url = str(recommendation.get("target_url") or "den berørte side")
    deliverable_type = _deliverable_type(recommendation)
    if deliverable_type == "title_meta":
        return {
            "deliverable_type": "title_meta",
            "summary": f"Tre snippet-retninger til {query}.",
            "recommended_option": (
                f"Title: {query.capitalize()} – trin for trin | "
                f"{recommendation.get('website', '')}\n"
                f"Meta: Få en enkel trin-for-trin-guide til {query}. "
                "Se løsningen, de vigtigste valg og typiske fejl."
            ),
            "alternatives": [
                f"Title: Sådan gør du | {query.capitalize()}",
                f"Title: {query.capitalize()} | Komplet guide",
                f"Meta: Lær hvordan du håndterer {query} med en enkel guide.",
            ],
            "rationale": (
                "Forslaget matcher det målte CTR-fald og bevarer den "
                "eksisterende søgeintention."
            ),
            "implementation_steps": [
                "Sammenhold forslaget med sidens nuværende title og meta.",
                "Indsæt den godkendte title og meta manuelt i CMS'et.",
            ],
            "validation_checks": [
                "Søgeordet og søgeintentionen er bevaret.",
                "Title og meta beskriver indhold, som faktisk findes på siden.",
            ],
        }
    if deliverable_type == "content_update":
        page = next(
            (
                row for row in (public_context or [])
                if row.get("relation") == "berørt side"
            ),
            {},
        )
        sections = page.get("content_sections") or []
        evidence_queries = [
            str(row.get("query") or "").strip()
            for row in (recommendation.get("search_queries") or [])
            if row.get("query")
        ] or [query]
        passage, preceding_heading = _select_relevant_passage(
            sections, evidence_queries
        )
        current = str(
            passage
            or page.get("h1")
            or page.get("content_excerpt")
            or ""
        ).strip()[:600]
        natural_topic = _natural_danish_topic(evidence_queries, query)
        heading = str(
            preceding_heading or page.get("h1") or natural_topic
        ).strip()
        finished_copy = _fallback_content_copy(natural_topic)
        if current:
            location = (
                f"Erstat den viste passage i den første relevante sektion "
                f"under “{heading}”."
            )
            replacement = finished_copy
        else:
            current = "Ny sektion – ingen eksisterende tekst"
            location = "Placeringen kan ikke fastslås uden artikelteksten."
            replacement = finished_copy
        return {
            "deliverable_type": "content_update",
            "summary": f"Et konkret indholdsudkast til {url}.",
            "recommended_option": replacement,
            "content_location": location,
            "current_content": current,
            "replacement_content": replacement,
            "search_intent": (
                f"Brugeren søger et tydeligt og praktisk svar på, "
                f"{natural_topic}."
            ),
            "content_opportunity_type": "existing_section",
            "missing_topic": query,
            "evidence_queries": evidence_queries,
            "duplication_check": (
                "Emnet udbygger den berørte side og opretter ikke en ny URL."
            ),
            "proposed_title": "",
            "proposed_slug": "",
            "outline": [],
            "alternatives": [
                f"Tilføj en FAQ med tre spørgsmål om {query}.",
                f"Udbyg den eksisterende hovedsektion om {query}.",
                "Tilføj en kort tjekliste med de vigtigste handlinger.",
            ],
            "rationale": (
                "Et placeringsfald kræver et tydeligere og mere dækkende "
                "svar på den eksisterende søgeintention."
            ),
            "implementation_steps": [
                "Placér den anbefalede sektion efter sidens indledning.",
                "Tilpas teksten til sidens dokumenterede fakta og tone.",
                "Tilføj 2–3 relevante interne links til sektionen.",
            ],
            "validation_checks": [
                "Sektionen besvarer søgeintentionen uden fyldtekst.",
                "Alle påstande kan dokumenteres på websitet.",
            ],
        }
    if deliverable_type == "internal_links":
        related = next(
            (
                row for row in (public_context or [])
                if row.get("relation") == "mulig relateret side"
                and row.get("url")
                and _normalized_url(str(row["url"]))
                != _normalized_url(url)
            ),
            {},
        )
        source_url = str(related.get("url") or "")
        current = str(
            related.get("excerpt")
            or "Ingen sikker eksisterende passage kunne identificeres."
        ).strip()[:500]
        anchor = f"guide til {query}"
        linked = f"{current.rstrip('.')} – læs også vores {anchor}."
        return {
            "deliverable_type": "internal_links",
            "summary": f"Et konkret internt linkudkast til {url}.",
            "recommended_option": linked,
            "source_url": source_url,
            "destination_url": url,
            "anchor_text": anchor,
            "link_location": "I den viste eksisterende passage på kildesiden.",
            "current_sentence": current,
            "linked_sentence": linked,
            "alternatives": [
                f"Ankertekst: {query}",
                f"Ankertekst: guide til {query}",
                "Ankertekst: læs den relaterede vejledning",
            ],
            "rationale": "Interne links skal styrke relevans og navigation.",
            "implementation_steps": [
                "Åbn den konkrete kildeside.",
                "Find den angivne passage og erstat den med linksætningen.",
                "Link kun den angivne ankertekst til destinationssiden.",
            ],
            "validation_checks": [
                "Kildesiden og destinationssiden handler om samme emne.",
                "Ankerteksten passer grammatisk ind i teksten.",
            ],
        }
    if deliverable_type == "monetization":
        page = next(
            (
                row for row in (public_context or [])
                if row.get("relation") == "berørt side"
            ),
            {},
        )
        heading = str(page.get("h1") or "sidens overskrift").strip()
        return {
            "deliverable_type": "monetization",
            "summary": f"Et konkret monetiseringsforslag til {url}.",
            "recommended_option": (
                "Tilføj en tydelig “Se aktuel pris”-knap ved det primære "
                "produkt øverst på siden, og indsæt et affiliatelink på hver "
                "produktomtale i brødteksten. Priser og lager hentes fra "
                "forhandlerens produktfeed."
            ),
            "content_location": f"Umiddelbart under overskriften “{heading}”.",
            "current_state": (
                "Siden har målt organisk trafik, men få eller ingen "
                "affiliatelinks eller købsknapper."
            ),
            "opportunity_type": "cta",
            "evidence": (
                "Siden får dokumenteret organisk trafik uden tilsvarende "
                "provision i de gemte salgsdata."
            ),
            "rationale": (
                "Eksisterende trafik uden monetisering er den hurtigste vej "
                "til provision — uden at kræve en bedre placering."
            ),
            "alternatives": [
                "Indsæt en sammenligningstabel over de omtalte produkter.",
                "Tilføj en fremhævet produktboks til det primære produkt.",
                "Placér affiliatelinks i de eksisterende produktomtaler.",
            ],
            "implementation_steps": [
                "Find de produkter siden allerede omtaler.",
                "Hent de rigtige affiliatelinks fra forhandlerens produktfeed.",
                "Indsæt knap/links på de angivne placeringer.",
            ],
            "validation_checks": [
                "Alle links peger på produkter siden faktisk omtaler.",
                "Priser og lager kommer fra produktfeedet, ikke fra teksten.",
            ],
        }
    if deliverable_type in {"technical_fix", "schema"}:
        label = "schemaudkast" if deliverable_type == "schema" else "rettelsesplan"
        return {
            "deliverable_type": deliverable_type,
            "summary": f"En konkret teknisk {label} til {url}.",
            "recommended_option": (
                "Implementér kun den dokumenterede rettelse på den berørte "
                "URL og kontrollér siden før og efter ændringen."
            ),
            "alternatives": [
                "Ret først i et testmiljø.",
                "Bevar nuværende løsning og dokumentér begrænsningen.",
            ],
            "rationale": (
                "Tekniske ændringer skal være afgrænsede og verificerbare."
            ),
            "implementation_steps": [
                "Gem den nuværende tekniske værdi som baseline.",
                "Implementér den anbefalede rettelse manuelt.",
                "Kør den relevante validering igen.",
            ],
            "validation_checks": [
                "Rettelsen påvirker kun den tilsigtede funktion.",
                "Siden kan fortsat indlæses og indekseres.",
            ],
        }
    return {
        "deliverable_type": "traffic_analysis",
        "summary": f"Et konkret analyseudkast for {url}.",
        "recommended_option": (
            "Sammenlign de gemte perioder og prioritér det signal, der "
            "forklarer flest tabte besøg, før der ændres på siden."
        ),
        "alternatives": [
            "Undersøg den største faldende kanal.",
            "Undersøg den vigtigste faldende landingsside.",
        ],
        "rationale": (
            "Datakilderne peger ikke sikkert på én websiteændring endnu."
        ),
        "implementation_steps": [
            "Rangér kanaler eller søgeord efter absolut tab.",
            "Dokumentér én årsag og én berørt URL.",
        ],
        "validation_checks": [
            "Konklusionen bygger på samme to perioder.",
            "Der foreslås højst én efterfølgende ændring.",
        ],
    }


def format_deliverable(deliverable: dict[str, Any]) -> str:
    """Serialize the reviewed deliverable into the approved task description."""
    alternatives = "\n".join(
        f"- {item}" for item in deliverable["alternatives"]
    )
    steps = "\n".join(
        f"{index}. {item}"
        for index, item in enumerate(deliverable["implementation_steps"], 1)
    )
    checks = "\n".join(
        f"- {item}" for item in deliverable["validation_checks"]
    )
    content_sections = ""
    structured_content_fields = (
        "content_location", "current_content", "replacement_content",
        "search_intent", "content_opportunity_type", "missing_topic",
        "evidence_queries", "duplication_check",
    )
    if (
        deliverable["deliverable_type"] == "content_update"
        and all(deliverable.get(field) for field in structured_content_fields)
    ):
        content_sections = (
            f"Indholdstype:\n{deliverable['content_opportunity_type']}\n\n"
            f"Manglende emne:\n{deliverable['missing_topic']}\n\n"
            f"Search Console-evidens:\n"
            f"{', '.join(deliverable['evidence_queries'])}\n\n"
            f"Dubletkontrol:\n{deliverable['duplication_check']}\n\n"
            f"Placering:\n{deliverable['content_location']}\n\n"
            f"Nuværende tekst:\n{deliverable['current_content']}\n\n"
            f"Ny tekst:\n{deliverable['replacement_content']}\n\n"
            f"Søgeintention:\n{deliverable['search_intent']}\n\n"
        )
        if deliverable["content_opportunity_type"] != "existing_section":
            content_sections += (
                f"Foreslået titel:\n{deliverable['proposed_title']}\n\n"
                f"Foreslået URL:\n{deliverable['proposed_slug']}\n\n"
                "Disposition:\n"
                + "\n".join(
                    f"- {row}" for row in deliverable["outline"]
                )
                + "\n\n"
            )
    link_sections = ""
    structured_link_fields = (
        "source_url", "destination_url", "anchor_text", "link_location",
        "current_sentence", "linked_sentence",
    )
    if (
        deliverable["deliverable_type"] == "internal_links"
        and all(deliverable.get(field) for field in structured_link_fields)
    ):
        link_sections = (
            f"Kildeside:\n{deliverable['source_url']}\n\n"
            f"Destinationsside:\n{deliverable['destination_url']}\n\n"
            f"Ankertekst:\n{deliverable['anchor_text']}\n\n"
            f"Placering på kildesiden:\n{deliverable['link_location']}\n\n"
            f"Nuværende passage:\n{deliverable['current_sentence']}\n\n"
            f"Passage med link:\n{deliverable['linked_sentence']}\n\n"
        )
    monetization_sections = ""
    structured_monetization_fields = (
        "content_location", "current_state", "opportunity_type", "evidence",
    )
    if (
        deliverable["deliverable_type"] == "monetization"
        and all(
            deliverable.get(field) for field in structured_monetization_fields
        )
    ):
        monetization_sections = (
            f"Mulighedstype:\n{deliverable['opportunity_type']}\n\n"
            f"Placering:\n{deliverable['content_location']}\n\n"
            f"Nuværende tilstand:\n{deliverable['current_state']}\n\n"
            f"Evidens:\n{deliverable['evidence']}\n\n"
        )
    return (
        f"Leverancetype: {deliverable['deliverable_type']}\n\n"
        f"{deliverable['summary']}\n\n"
        f"Anbefalet løsning:\n{deliverable['recommended_option']}\n\n"
        f"{content_sections}"
        f"{link_sections}"
        f"{monetization_sections}"
        f"Begrundelse:\n{deliverable['rationale']}\n\n"
        f"Alternativer:\n{alternatives}\n\n"
        f"Implementering:\n{steps}\n\n"
        f"Kontrol før godkendelse:\n{checks}"
    )


def split_title_meta_option(value: str) -> tuple[str, str]:
    """Extract title and meta from either one-line or multiline AI output."""
    cleaned = " ".join(str(value or "").split())
    match = re.fullmatch(
        r"Title:\s*(.+?)\s+Meta:\s*(.+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Title/meta-udkastet skal indeholde både 'Title:' og 'Meta:'."
        )
    title = prefer_pipe_separator(match.group(1).strip())
    meta = match.group(2).strip()
    if not title or not meta:
        raise ValueError("Title/meta-udkastet mangler title eller meta.")
    return title, meta


def prefer_pipe_separator(title: str) -> str:
    """Use the product's preferred visual separator in generated titles."""
    clean = str(title or "").strip()
    if " | " not in clean and ": " in clean:
        clean = clean.replace(": ", " | ", 1)
    return clean


def format_title_meta_option(title: str, meta: str) -> str:
    return f"Title: {prefer_pipe_separator(title)}\nMeta: {str(meta).strip()}"


def mentions_price(text: str) -> bool:
    return bool(re.search(
        r"\bpris(?:er|en|erne)?\b"
        r"|\b\d+(?:[.,]\d+)?\s*(?:kr\.?|dkk|eur|usd)\b"
        r"|[€£$]",
        str(text).casefold(),
    ))


PROMPT_MAX_BODY_SECTIONS = 12
PROMPT_MAX_HEADINGS = 4
PROMPT_MAX_EXCERPT = 600
PROMPT_MAX_RELATED_EXCERPT = 300
_MARKUP_MARKERS = (
    '{"', '{ "', '"@context"', 'schema.org', 'window.', 'function(', 'gtag(',
)


def _looks_like_markup(text: str) -> bool:
    """True for JSON-LD/script/CSS fragments that are not readable prose."""
    stripped = str(text or "").strip()
    lowered = stripped.casefold()
    return (
        stripped.startswith("{")
        or stripped.startswith(".")
        or any(marker.casefold() in lowered for marker in _MARKUP_MARKERS)
    )


def _clean_prose(text: str, limit: int) -> str:
    """Drop JSON-LD/script blobs and collapse whitespace for the prompt."""
    value = str(text or "")
    for marker in _MARKUP_MARKERS:
        index = value.find(marker)
        if index != -1:
            value = value[:index]
    return " ".join(value.split())[:limit]


def _condense_sections(
    sections: list[Any], queries: list[str]
) -> list[dict[str, str]]:
    """Keep only headings and the query-relevant body passages."""
    query_tokens = _content_tokens(" ".join(queries)) - CONTENT_STOPWORDS
    headings: list[dict[str, str]] = []
    scored: list[tuple[int, int, dict[str, str]]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        element = str(section.get("element") or "")
        text = str(section.get("text") or "").strip()
        if (
            not text
            or _looks_like_markup(text)
            or _is_boilerplate_passage(text)
        ):
            continue
        if element in {"h1", "h2", "h3"}:
            if len(headings) < PROMPT_MAX_HEADINGS:
                headings.append({"element": element, "text": text[:160]})
        elif element in {"p", "li"} and len(text) >= 30:
            overlap = len(
                query_tokens & (_content_tokens(text) - CONTENT_STOPWORDS)
            )
            scored.append(
                (overlap, len(text), {"element": element, "text": text[:400]})
            )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    bodies = [row for _, _, row in scored[:PROMPT_MAX_BODY_SECTIONS]]
    return headings + bodies


def _condense_context_for_prompt(
    public_context: list[dict[str, Any]], queries: list[str]
) -> list[dict[str, Any]]:
    """Trim the public context to the smallest grounded payload for the model.

    Sends only headings and query-relevant passages instead of every raw
    section, strips JSON-LD/CSS noise from excerpts, and drops heavy fields
    the model never uses. This cuts input tokens per suggestion sharply
    without weakening the grounding.
    """
    condensed: list[dict[str, Any]] = []
    for original in public_context[:8]:
        row = dict(original)
        if row.get("content_sections"):
            row["content_sections"] = _condense_sections(
                row["content_sections"], queries
            )
        if row.get("content_excerpt"):
            row["content_excerpt"] = _clean_prose(
                row["content_excerpt"], PROMPT_MAX_EXCERPT
            )
        if row.get("excerpt"):
            row["excerpt"] = _clean_prose(
                row["excerpt"], PROMPT_MAX_RELATED_EXCERPT
            )
        for heavy in (
            "schema", "word_count", "internal_links", "canonical",
            "content_text",
        ):
            row.pop(heavy, None)
        condensed.append(row)
    return condensed


def _prompt(
    recommendation: dict[str, Any],
    public_context: list[dict[str, Any]],
) -> str:
    cause = str(recommendation.get("measured_cause") or "")
    deliverable_type = _deliverable_type(recommendation)
    prompt_queries = [
        candidate
        for candidate in (
            [str(recommendation.get("target_query") or "").strip()]
            + [
                str(row.get("query") or "").strip()
                for row in (recommendation.get("search_queries") or [])
            ]
        )
        if candidate
    ]
    payload = {
        "website": recommendation.get("website"),
        "url": recommendation.get("target_url"),
        "query": recommendation.get("target_query"),
        "measured_cause": cause,
        "recommended_action": recommendation.get("recommended_action"),
        "evidence": recommendation.get("explanation"),
        "search_queries": recommendation.get("search_queries") or [],
        "forced_content_mode": recommendation.get("forced_content_mode") or "",
        "freshness_evidence": recommendation.get("freshness_evidence") or {},
        "freshness_verification": (
            recommendation.get("freshness_verification") or {}
        ),
        "public_content_candidates": _condense_context_for_prompt(
            public_context, prompt_queries
        ),
    }
    content_requirements = ""
    content_schema = ""
    if deliverable_type == "content_update":
        content_requirements = """
Ved content_update skal du udpege en præcis placering på siden og citere den
nuværende passage fra public_content_candidates. Lever en fuldt færdig
erstatning eller tilføjelse, som kan kopieres direkte. Bed aldrig brugeren om
selv at skrive, uddybe eller finde teksten. Den nye tekst skal besvare den
klassificerede søgeintention og må ikke opfinde fakta, produkter, funktioner
eller løfter, som ikke er dokumenteret i sideindholdet. Hvis en helt ny sektion
er nødvendig, skriv "Ny sektion – ingen eksisterende tekst" som current_content.
Search Console-søgeord er kun evidens og må ikke kopieres mekanisk ind i
teksten. Omskriv dem altid til grammatisk, idiomatisk dansk. Formuleringer som
"Her får du et klart svar om [rå søgefrase]" er ikke acceptable. Ved en
eksisterende passage skal content_location entydigt sige "Erstat denne passage",
current_content skal være et ordret citat, og replacement_content skal være den
færdige erstatning. Hvis ingen passage kan dokumenteres, må du ikke foregive en:
angiv i stedet en præcis placering for en ny sektion.
replacement_content skal altid være udfyldt med den fuldstændige færdige tekst –
den samme tekst som recommended_option – og må aldrig være tom.
evidence_queries skal altid indeholde de faktiske Search Console-søgeord fra data
(query og search_queries) og må aldrig være tom.
Brug naturlig dansk retskrivning og sammenskriv danske sammensatte ord.
Undgå engelskinspirerede bindestreger som "Kalender-appen"; skriv eksempelvis
"Kalenderappen". Brug kun en bindestreg, når dansk retskrivning faktisk kræver
den.
Find først det konkrete content gap ved at sammenholde Search Console-søgeord,
den berørte side og de relaterede eksisterende sider. Vælg præcis én type:
existing_section, new_category, new_article eller new_blog_post. Brug kun en ny
side, når emnet har en selvstændig søgeintention og ikke naturligt hører hjemme
på den eksisterende side. Kontrollér eksplicit risikoen for dubletindhold og
søgeordskannibalisering. Ved nyt indhold skal du også levere titel, URL-idé,
mindst tre dispositionspunkter og færdige indledende afsnit.
"""
        forced_mode = str(
            recommendation.get("forced_content_mode") or ""
        )
        if forced_mode == "existing_section":
            content_requirements += """
Denne test skal leveres som existing_section. Opret ikke en ny side.
"""
        elif forced_mode == "content_gap":
            content_requirements += """
Denne test skal afprøve et content gap. Vælg den bedst dokumenterede type blandt
new_category, new_article og new_blog_post. Brug kun existing_section, hvis
Search Console- og sideindholdet tydeligt viser, at en ny side vil kannibalisere.
"""
        if recommendation.get("freshness_evidence"):
            content_requirements += """
Denne opgave er en aktualitetskontrol. Du må ikke erklære en oplysning forældet
alene på grund af tekstens alder eller et årstal. Peg på den konkrete eksisterende
passage. Foreslå kun en erstatning, når den kan underbygges af det viste
sideindhold og aktuelle, officielle oplysninger. Brug web search til at
genkontrollere de officielle kilder i freshness_verification. Sæt disse
kilde-URL'er i evidence_queries. Hvis det ikke kan bekræftes, skal anbefalingen
være manuel kontrol frem for en opdigtet rettelse.
"""
        content_schema = """
  "content_location": "præcis overskrift og placering på siden",
  "current_content": "ordret eksisterende passage eller markering af ny sektion",
  "replacement_content": "færdig tekst til direkte indsættelse",
  "search_intent": "kort konkret beskrivelse af brugerens intention",
  "content_opportunity_type": "existing_section|new_category|new_article|new_blog_post",
  "missing_topic": "det konkrete manglende spørgsmål eller emne",
  "evidence_queries": ["Search Console-søgeord 1", "søgeord 2"],
  "duplication_check": "hvorfor forslaget ikke dublerer eller kannibaliserer eksisterende indhold",
  "proposed_title": "titel ved nyt indhold; ellers tom tekst",
  "proposed_slug": "URL-idé ved nyt indhold; ellers tom tekst",
  "outline": ["mindst tre punkter ved nyt indhold; ellers tom liste"],
"""
    if deliverable_type == "internal_links":
        content_requirements = """
Ved internal_links skal du vælge præcis én faktisk kildeside fra rækkerne med
relationen "mulig relateret side". destination_url skal være opgavens url.
Kildeside og destination skal være forskellige. Citér den eksisterende passage
fra kildesidens excerpt, angiv den præcise placering, vælg én naturlig
ankertekst, og lever hele den færdige sætning, som brugeren kan indsætte.
Ankerteksten skal stå ordret i linked_sentence. Opfind aldrig en URL, passage
eller side, og bed ikke brugeren om selv at finde en kildeside.
"""
        content_schema = """
  "source_url": "eksisterende URL fra en mulig relateret side",
  "destination_url": "opgavens dokumenterede mål-URL",
  "anchor_text": "den præcise tekst, der skal linkes",
  "link_location": "præcis placering eller afsnit på kildesiden",
  "current_sentence": "ordret eksisterende passage fra kildesiden",
  "linked_sentence": "færdig passage med ankerteksten indarbejdet",
"""
    if deliverable_type == "monetization":
        content_requirements = """
Ved monetization er opgaven at tjene penge på trafik siden ALLEREDE har.
Dataen viser besøg men lav eller ingen provision. Foreslå én konkret,
kopiér-klar monetiseringsændring forankret i sidens FAKTISKE indhold og de
produkter/emner siden allerede omtaler. Opfind aldrig produkter, priser,
mærker eller links, der ikke er dokumenteret i sideindholdet — henvis i stedet
til de produkttyper siden allerede nævner, så redaktøren selv indsætter det
rigtige affiliatelink fra forhandlerens produktfeed (priser og lager kommer
fra feedet, ikke fra dig).
Vælg præcis én opportunity_type:
- comparison_table: for anmeldelser/guides/lister med flere produkter — lever
  en færdig sammenligningstabel i markdown med de produkter siden allerede
  omtaler og relevante kolonner (fx model, nøgleegenskab og en
  "Se pris"-kolonne, hvor redaktøren indsætter affiliatelinket). Foretræk
  denne på anmeldelses- og guidesider.
- affiliate_links: når brødteksten omtaler produkter uden links — udpeg præcist
  hvor linkene skal ind og med hvilken ankertekst.
- cta: én tydelig handlingsopfordring (fx "Se aktuel pris") placeret der, hvor
  købsintentionen er højest.
- product_box: en fremhævet produktboks til sidens primære produkt.
content_location skal entydigt sige, hvor på siden ændringen placeres.
current_state skal beskrive, hvad der er der nu (fx "prosa-anmeldelse uden
affiliatelinks"). evidence skal nævne de faktiske trafiktal fra dataen som
begrundelse. recommended_option skal være den færdige, kopiér-klare ændring.
Brug naturlig dansk retskrivning.
"""
        content_schema = """
  "content_location": "præcis placering på siden",
  "current_state": "hvad findes på siden nu",
  "opportunity_type": "comparison_table|affiliate_links|cta|product_box",
  "evidence": "de faktiske trafik-/provisionstal, der begrunder forslaget",
"""
    user_guidelines = str(
        recommendation.get("_prompt_guidelines") or ""
    ).strip()
    guideline_section = (
        "\n\nBRUGERADMINISTREREDE RETNINGSLINJER "
        "(skal overholdes):\n" + user_guidelines
        if user_guidelines else ""
    )
    return f"""
Du er arbejdsassistent i en dansk SEO-app. Producer selve arbejdsudkastet;
bed aldrig brugeren om selv at skrive forslagene eller lave den indledende
analyse. Intet må publiceres automatisk. Brug kun den givne evidens, markér
usikkerhed, og bevar sidens søgeintention.
Ved title_meta skal title og meta stå på hver sin linje som "Title: ..." og
"Meta: ...". Brug altid " | " som separator i titles; brug ikke kolon som
title-separator. Titles og metabeskrivelser må aldrig omtale priser, konkrete
beløb eller valuta, fordi oplysningerne hurtigt bliver forældede.
{content_requirements}

Opgavetype: {deliverable_type}
Data: {json.dumps(payload, ensure_ascii=False)}

Svar kun med gyldig JSON:
{{
  "deliverable_type": "{deliverable_type}",
  "summary": "kort beskrivelse af den færdige leverance",
  "recommended_option": "det konkrete forslag; ved title_meta både title og meta",
{content_schema}
  "alternatives": ["konkret alternativ 1", "konkret alternativ 2", "konkret alternativ 3"],
  "rationale": "kort databaseret begrundelse",
  "implementation_steps": ["præcis manuel handling 1", "præcis manuel handling 2"],
  "validation_checks": ["kontrolpunkt 1", "kontrolpunkt 2"]
}}
{guideline_section}
""".strip()


def _deliverable_type(recommendation: dict[str, Any]) -> str:
    """Map current and future task labels to a shared deliverable type."""
    explicit = str(
        recommendation.get("experiment_type")
        or recommendation.get("change_type")
        or ""
    )
    if explicit in DELIVERABLE_TYPES:
        return explicit
    text = " ".join(str(recommendation.get(key) or "") for key in (
        "task_type", "measured_cause", "description", "recommended_action",
    )).casefold()
    if "ctr" in text or "title" in text or "meta" in text:
        return "title_meta"
    if "intern" in text and "link" in text:
        return "internal_links"
    if "schema" in text or "strukturerede data" in text:
        return "schema"
    if "teknisk" in text or "technical" in text:
        return "technical_fix"
    if "placering" in text or "indhold" in text or "content" in text:
        return "content_update"
    return "traffic_analysis"
