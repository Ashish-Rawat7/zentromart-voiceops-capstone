from __future__ import annotations
import re
import secrets
import unicodedata

def normalize_digits(value: str) -> str:
    # Convert Unicode decimal digits (including Devanagari) to ASCII.
    return "".join(str(unicodedata.digit(ch)) for ch in str(value or "") if ch.isdecimal())

def valid_session_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Fa-f0-9-]{20,80}", value or ""))

def is_phone_suffix(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", normalize_digits(value)))

def is_pincode(value: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", normalize_digits(value)))

def new_session_id() -> str:
    return secrets.token_hex(24)

def normalize_order_id(value: str) -> str:
    return normalize_digits(value)

def extract_order_id(text: str) -> str | None:
    # Require a nearby order keyword to avoid treating dates, SKUs, or arbitrary digits as order IDs.
    n = text or ""
    patterns = [
        r"(?i)(?:order\s*(?:id|number|no|#)?|ऑर्डर\s*(?:नंबर|आईडी)?)\s*(?:is|hai|है|:|#)?\s*([\d\s-]{8,18})",
    ]
    for pattern in patterns:
        m = re.search(pattern, n)
        if m:
            digits = normalize_digits(m.group(1))
            if len(digits) == 8:
                return digits
    # common phrase "my order is 12345678"
    return None

def redact_secrets(text: str) -> str:
    """Redact verification proofs before anything can be placed in a ticket or log."""
    if not text:
        return text
    patterns = [
        (r"(?i)(last\s*(?:four|4)(?:\s+digits?)?|phone suffix|registered phone|pincode|pin code|verification[_ ]value|verification code)\s*(?:are|is|:|=|of|hai|हैं|है)?\s*[:=]?\s*\d{4,6}", r"\1 [REDACTED]"),
        (r"(?i)\b(otp|password|upi pin|payment pin|pin)\s*[:=]?\s*\d{4,8}\b", r"\1 [REDACTED]"),
        (r"\b\d{6}\b", "[REDACTED_NUMBER]"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text
