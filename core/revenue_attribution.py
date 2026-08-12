"""Per-page and per-product commission attribution.

Single source of truth for the normalisation that turns a Partner-ads sale
(website ``url`` + page ``uid`` + product ``uid2``) into stable page and product
keys. ``core.goal_overview`` renders these keys in the overview, and the
prioritisation in ``core.decision_engine`` maps a candidate URL to the very same
page key so a page's earned commission can weigh into what to work on next.

Only DKK sales count, mirroring the overview. Junk attribution — unfilled
Partner-ads templates (``[UID]``) and base64 feed blobs (``eyJ…``) — is dropped.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Iterator
from urllib.parse import urlsplit


def domain(url: str) -> str:
    """Return the source website domain without a scheme or ``www.``."""
    netloc = urlsplit(url).netloc.lower()
    if not netloc:
        netloc = urlsplit(f"//{url}").netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or "Ukendt"


def page_key(domain_value: str, uid: str) -> str:
    """Combine the source domain and the page path into a page identifier.

    Unfilled Partner-ads link templates (e.g. ``[UID]``) are treated as missing.
    """
    path = (uid or "").strip()
    if not path or "[" in path or "]" in path:
        return ""
    if domain_value and domain_value != "Ukendt":
        return f"{domain_value}{path}"
    return path


def clean_product(uid2: str) -> str:
    """Return a human product name, or "" for encoded/placeholder junk.

    Some sales carry a base64-encoded feed blob (``eyJ…``) instead of a name.
    """
    product = (uid2 or "").strip()
    if not product or "[" in product or "]" in product:
        return ""
    if product.startswith("eyJ"):
        return ""
    return product


def page_key_for_url(url: str) -> str:
    """Return the page key a sale on ``url`` would attribute commission to."""
    parts = urlsplit(url if "//" in url else f"//{url}")
    return page_key(domain(url), parts.path)


def _dkk_sales(
    records: list[dict[str, Any]],
) -> Iterator[tuple[float, str, str, str]]:
    """Yield ``(provision, url, uid, uid2)`` for every valid DKK sale."""
    for record in records:
        if str(record.get("valuta", "DKK") or "DKK").upper() != "DKK":
            continue
        try:
            provision = float(Decimal(str(record["provision"])))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            continue
        yield (
            provision,
            str(record.get("url", "") or ""),
            str(record.get("uid", "") or ""),
            str(record.get("uid2", "") or ""),
        )


def revenue_by_page(records: list[dict[str, Any]]) -> dict[str, float]:
    """Sum DKK commission per page key across the supplied sale records."""
    totals: dict[str, float] = {}
    for provision, url, uid, _ in _dkk_sales(records):
        key = page_key(domain(url), uid)
        if key:
            totals[key] = totals.get(key, 0.0) + provision
    return totals


def revenue_by_product(records: list[dict[str, Any]]) -> dict[str, float]:
    """Sum DKK commission per product across the supplied sale records."""
    totals: dict[str, float] = {}
    for provision, _, _, uid2 in _dkk_sales(records):
        product = clean_product(uid2)
        if product:
            totals[product] = totals.get(product, 0.0) + provision
    return totals
