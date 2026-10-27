"""Token usage from the provider's response, or an estimate when the provider gives none.

Handles the OpenAI-style `usage` (Groq through Portkey) and Gemini's `usage_metadata`,
as objects or dicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

UsageSource = Literal["PROVIDER", "ESTIMATED"]


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    source: UsageSource = "PROVIDER"


def _get(obj: Any, *names: str) -> Any:
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return None


def normalize_usage(usage: Any) -> Usage | None:
    """None when the provider sent no usage; the caller then estimates."""
    if usage is None:
        return None
    if isinstance(usage, Usage):
        return usage
    tokens_in = _get(usage, "prompt_tokens", "input_tokens", "prompt_token_count")
    tokens_out = _get(usage, "completion_tokens", "output_tokens", "candidates_token_count")
    cached = _get(usage, "cached_content_token_count", "cached_tokens")
    if cached is None:
        details = _get(usage, "prompt_tokens_details", "input_tokens_details")
        cached = _get(details, "cached_tokens") if details is not None else None
    if tokens_in is None and tokens_out is None:
        return None
    return Usage(int(tokens_in or 0), int(tokens_out or 0), int(cached or 0), "PROVIDER")


def estimate_tokens(text: str | None) -> int:
    """Rough count (about 4 characters a token) for when the stream carries no usage."""
    return math.ceil(len(text or "") / 4)


def estimated_usage(prompt_text: str, output_text: str) -> Usage:
    return Usage(estimate_tokens(prompt_text), estimate_tokens(output_text), 0, "ESTIMATED")
