"""Safe user-facing technical error formatting."""

import re


def safe_error_detail(error: Exception) -> str:
    """Keep useful error context while redacting secret-shaped values."""
    text = str(error).replace("\n", " ")[:300]
    text = re.sub(
        r"(?i)\b(sk|rk|pk)-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text
    )
    text = re.sub(
        r"(?i)(api.?key|token|secret|credential|password)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    return text or "Ingen yderligere fejlbeskrivelse."
