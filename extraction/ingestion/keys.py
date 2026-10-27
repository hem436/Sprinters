"""Primary and fallback Gemini keys (kept from the chatbot repo's gemini_keys.py).

The free tier counts its daily quota per Google Cloud project, so a second key on another project doubles the
ceiling. Rotation is process-wide and sticky: after a quota error we stay on the next key.
"""
import logging
import os
import threading

log = logging.getLogger(__name__)
_lock = threading.Lock()
_index = 0


def all_keys() -> list[str]:
    return [k for k in (os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_FALLBACK_KEY")) if k]


def current() -> str | None:
    keys = all_keys()
    if not keys:
        return None
    with _lock:
        return keys[min(_index, len(keys) - 1)]


def rotate() -> str | None:
    """Move to the next key. None means every key is used up: the caller must stop and report it."""
    global _index
    keys = all_keys()
    with _lock:
        if _index + 1 >= len(keys):
            return None
        _index += 1
        key = keys[_index]
    log.warning("Gemini key out of quota; switched to fallback key #%s.", _index)
    return key


def reset() -> None:
    global _index
    with _lock:
        _index = 0


def is_quota_error(exc: Exception) -> bool:
    """Matched on text, because the REST and gRPC clients raise different types for the same 429."""
    text = str(exc).lower()
    return any(m in text for m in ("429", "resource_exhausted", "quota", "rate limit", "ratelimit"))


def is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(m in text for m in ("503", "504", "unavailable", "timeout", "timed out", "deadline", "overloaded",
                                   "500"))


def is_daily_cap(exc: Exception) -> bool:
    """A per-day quota (GenerateRequestsPerDayPerProjectPerModel...): only a new key or another model helps."""
    text = str(exc).lower()
    return is_quota_error(exc) and ("perday" in text or "per day" in text or "daily" in text)
