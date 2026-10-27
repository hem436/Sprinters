"""Rule S2 at ingest (contract 04): chunks that try to give the model instructions get `injection_suspect = true`.
They stay usable as evidence for facts; the agent treats their use as a safety event.

The patterns are the same list as Arka's model/agent/safety.py (INJECTION_PATTERNS), plus the "system prompt" and
hidden-text tricks that contract 04 S2 names for ingest. Keep the two lists in step.
"""
import re

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (all |the )?(previous|prior|above|system) (instructions|rules|prompt)",
    r"you are now\b",
    r"\b(reveal|show|print|repeat) (me )?(your |the )?(system|hidden) prompt",
    r"\bdeveloper mode\b",
    r"\bjailbreak\b",
    r"act as (an? )?(unrestricted|unfiltered)",
    # ingest only (S2): text aimed at a model reading the document
    r"\bsystem prompt\b",
    r"\b(assistant|ai|llm|chatbot)s?\b[^.\n]{0,40}\b(must|should|always) (say|answer|reply|respond)",
]
_INJECTION = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

# characters used to hide text from a human reader: zero-width spaces and joiners, bidi controls
_HIDDEN = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")

_PII = [
    re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"),                 # card
    re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)"),              # Aadhaar
    re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)"),     # Indian mobile
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),                              # PAN
    re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),                    # e-mail
]


def injection_suspect(text: str) -> bool:
    return bool(_HIDDEN.search(text)) or any(p.search(text) for p in _INJECTION)


def pii_found(text: str) -> bool:
    return any(p.search(text) for p in _PII)
