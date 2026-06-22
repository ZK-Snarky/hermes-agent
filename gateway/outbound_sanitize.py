"""Shared outbound text sanitization helpers.

Secret redaction must run on any text that can leave the gateway, regardless
of which platform sends it. Keeping the primitives in this small module (rather
than inside ``gateway/run.py``) lets platform plugins reuse them in their
``PlatformEntry.outbound_sanitize_fn`` hooks without importing the heavy gateway
runtime.
"""
from __future__ import annotations

import re

# Best-effort provider/token secret shapes. Conservative on length so normal
# prose ("sk-" abbreviations, short bearer words) is not falsely redacted.
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._\-]{20,}\b"),
)


def redact_user_facing_secrets(text: str) -> str:
    """Best-effort secret redaction before text can leave the gateway."""
    redacted = str(text or "")
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(
            lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]",
            redacted,
        )
    return redacted
