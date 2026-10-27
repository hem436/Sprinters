"""PII masking before anything is stored (contract 11 section 6, rule S3).

Regexes for e-mail, Indian phone, PAN, Aadhaar and card numbers. Longer patterns run
first so a card number is not half-masked as a phone. IDs such as P-104, E1042 and
EXP-20871 are not personal data and stay as they are.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_PHONE = re.compile(r"(?<![\d+])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def mask_pii(text: str | None) -> tuple[str, list[str]]:
    """Return the masked text and the kinds of PII found, for example ["EMAIL", "PHONE"]."""
    if not text:
        return text or "", []
    found: list[str] = []

    def sub(pattern: re.Pattern[str], label: str, s: str, check=None) -> str:
        def repl(m: re.Match[str]) -> str:
            if check and not check(m.group(0)):
                return m.group(0)
            if label not in found:
                found.append(label)
            return f"[{label}]"

        return pattern.sub(repl, s)

    out = sub(_EMAIL, "EMAIL", text)
    out = sub(_CARD, "CARD", out, check=lambda s: _luhn_ok(re.sub(r"\D", "", s)))
    out = sub(_AADHAAR, "AADHAAR", out)
    out = sub(_PHONE, "PHONE", out)
    out = sub(_PAN, "PAN", out)
    return out, found
