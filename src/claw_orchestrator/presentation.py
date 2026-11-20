"""Customer-facing narrative projection; never use for canonical review data."""

import re
from collections.abc import Mapping

_PRODUCT = re.compile(r"open[\s_-]*claw", re.IGNORECASE)
_RUNTIME = re.compile(r"(?:nemo[\s_-]*claw|open[\s_-]*shell)", re.IGNORECASE)
_INTERNAL_BRAND = re.compile(r"(?:open[\s_-]*claw|nemo[\s_-]*claw|open[\s_-]*shell)", re.IGNORECASE)
# Match credentials before applying the output limit, so truncation cannot expose
# a prefix of a secret that would otherwise have matched the complete pattern.
_CREDENTIALS = (
    re.compile(r"\bsk-lm-[A-Za-z0-9_-]+:[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:sk|pk)-(?:[A-Za-z0-9]+-)*[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?P<label>[\"']?(?:[A-Za-z][A-Za-z0-9_]*_)?"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"gateway[_-]?token|password|authorization)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|"
    r"(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+|[^\s,;}]+)",
    re.IGNORECASE,
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----.*?"
    r"(?:-----END (?:[A-Z ]* )?PRIVATE KEY-----|$)",
    re.DOTALL,
)
_RUNTIME_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|/|\./|~/)?"
    r"[^\s\"'<>`]*"
    r"(?:\.(?:openclaw|nemoclaw|openshell)(?:[/\\][^\s\"'<>`]*)?|"
    r"\.state[/\\](?:gateway-devices|instances|openshell-gateway[^/\\\s]*)"
    r"(?:[/\\][^\s\"'<>`]*)?|"
    r"(?:openclaw|nemoclaw|openshell)\.(?:json|ya?ml|toml)|"
    r"co-orch-[A-Za-z0-9_-]+[/\\][^\s\"'<>`]+)",
    re.IGNORECASE,
)
_UNTRUSTED_START = re.compile(
    r"(?:SECURITY NOTICE: The following content is from an EXTERNAL, UNTRUSTED source.*?)?"
    r"<<<EXTERNAL_UNTRUSTED_CONTENT[^\n>]*>>>\s*(?:Source:[^\n]*\n---\n)?",
    re.DOTALL,
)
_SECURITY_NOTICE_ONLY = re.compile(
    r"SECURITY NOTICE: The following content is from an EXTERNAL, UNTRUSTED source.*?(?=\n\n|\Z)",
    re.DOTALL,
)
_UNTRUSTED_END = re.compile(r"\n?<<<END_EXTERNAL_UNTRUSTED_CONTENT[^\n>]*>>>")


def public_text(value: str, limit: int = 500000) -> str:
    """Return a bounded, neutral narrative copy without changing its source.

    This is defense in depth for the curated text projection, not a substitute
    for allowlisting fields or authorization. Inputs, stored data, commands and
    exact approval presentations must retain their original canonical values.
    """
    if not isinstance(value, str):
        return ""
    text = _UNTRUSTED_START.sub("", value)
    text = _SECURITY_NOTICE_ONLY.sub("", text)
    text = _UNTRUSTED_END.sub("", text)
    text = _PRIVATE_KEY.sub("[private credential]", text)
    # LM Studio tokens contain a colon, which assignment parsers may split.
    text = _CREDENTIALS[0].sub("[private credential]", text)
    text = _SECRET_ASSIGNMENT.sub(r"\g<label>[private credential]", text)
    for pattern in _CREDENTIALS:
        text = pattern.sub("[private credential]", text)
    text = _RUNTIME_PATH.sub("[private workspace configuration]", text)
    text = _PRODUCT.sub("Morrow", text)
    text = _RUNTIME.sub("workspace runtime", text)
    return text[: max(0, limit)]


def has_internal_brand(value: object) -> bool:
    """Check exact proposals recursively so unsupported reviews fail closed."""
    if isinstance(value, str):
        return _INTERNAL_BRAND.search(value) is not None
    if isinstance(value, Mapping):
        return any(has_internal_brand(k) or has_internal_brand(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(has_internal_brand(item) for item in value)
    return False
