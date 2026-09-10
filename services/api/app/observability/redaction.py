import re


def sanitize_message(message: str, api_key: str | None = None) -> str:
    sanitized = message
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    sanitized = re.sub(
        r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        sanitized,
    )
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", sanitized)
    return sanitized[:500]
