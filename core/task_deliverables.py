"""Concrete, reviewable work drafts for every traffic recommendation."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit


DELIVERABLE_TYPES = {
    "title_meta", "content_update", "internal_links",
    "technical_fix", "schema", "traffic_analysis",
}


def generate_task_deliverable(
    recommendation: dict[str, Any],
    *,
    ai_service: Any,
    public_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ask AI for one bounded deliverable and validate its structure."""
    response = ai_service.generate_response(
        _prompt(recommendation, public_context or [])
    )
    context = public_context or []
    return validate_task_deliverable(
        response.text,
        expected_target_url=str(recommendation.get("target_url") or ""),
        allowed_source_urls=[
            str(row.get("url") or "")
            for row in context
            if row.get("relation") == "mulig relateret side"
            and row.get("url")
        ],
    )


def validate_task_deliverable(
    text: str,
    *,
    expected_target_url: str = "",
    allowed_source_urls: list[str] | None = None,
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
        validate_content_change(value)
        value["recommended_option"] = value["replacement_content"]
    elif deliverable_type == "internal_links":
        validate_internal_link(
            value,
            expected_target_url=expected_target_url,
            allowed_source_urls=allowed_source_urls,
        )
        value["recommended_option"] = value["linked_sentence"]
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
        current = str(
            (sections[0].get("text") if sections else "")
            or page.get("h1")
            or page.get("content_excerpt")
            or "Ingen sikker eksisterende passage kunne identificeres."
        ).strip()[:600]
        heading = str(page.get("h1") or query).strip()
        replacement = (
            f"{heading}\n\n"
            f"Her får du et klart svar om {query}. "
            f"{current}"
        ).strip()
        evidence_queries = [
            str(row.get("query") or "").strip()
            for row in (recommendation.get("search_queries") or [])
            if row.get("query")
        ] or [query]
        return {
            "deliverable_type": "content_update",
            "summary": f"Et konkret indholdsudkast til {url}.",
            "recommended_option": replacement,
            "content_location": (
                f"Erstat eller udbyg den første hovedsektion under “{heading}”."
            ),
            "current_content": current,
            "replacement_content": replacement,
            "search_intent": (
                f"Brugeren søger et tydeligt og praktisk svar om {query}."
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
    return (
        f"Leverancetype: {deliverable['deliverable_type']}\n\n"
        f"{deliverable['summary']}\n\n"
        f"Anbefalet løsning:\n{deliverable['recommended_option']}\n\n"
        f"{content_sections}"
        f"{link_sections}"
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


def _prompt(
    recommendation: dict[str, Any],
    public_context: list[dict[str, Any]],
) -> str:
    cause = str(recommendation.get("measured_cause") or "")
    deliverable_type = _deliverable_type(recommendation)
    payload = {
        "website": recommendation.get("website"),
        "url": recommendation.get("target_url"),
        "query": recommendation.get("target_query"),
        "measured_cause": cause,
        "recommended_action": recommendation.get("recommended_action"),
        "evidence": recommendation.get("explanation"),
        "search_queries": recommendation.get("search_queries") or [],
        "public_content_candidates": public_context[:8],
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
Find først det konkrete content gap ved at sammenholde Search Console-søgeord,
den berørte side og de relaterede eksisterende sider. Vælg præcis én type:
existing_section, new_category, new_article eller new_blog_post. Brug kun en ny
side, når emnet har en selvstændig søgeintention og ikke naturligt hører hjemme
på den eksisterende side. Kontrollér eksplicit risikoen for dubletindhold og
søgeordskannibalisering. Ved nyt indhold skal du også levere titel, URL-idé,
mindst tre dispositionspunkter og færdige indledende afsnit.
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
