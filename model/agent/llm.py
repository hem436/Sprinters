"""AI-5 and AI-4 (contract 06): one client for any OpenAI-compatible chat endpoint (Groq directly, or Portkey).

Standard library only (urllib), so the agent adds no SDK dependency. Usage numbers come from the provider's `usage`
object (11 section 4); when it is missing, tokens are estimated and labelled ESTIMATED.
"""
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request

from agent.types import LLMReply

# Every way one call can fail: network (URLError, OSError, dropped connection), time, a body that is not the
# expected JSON (ValueError, KeyError, IndexError). Each sends us to the fallback model (review #25). TypeError is
# left out on purpose: it would also hide a bug in our own code (review #25); _content() turns a wrong body shape
# into a ValueError instead.
CALL_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError,
               ValueError, KeyError, IndexError)
# Groq's free tier limits tokens per minute per model (8,000 for gpt-oss). A 429 says how long to wait: up to this
# long we wait and try the same model once more; a longer wait moves on to the next model (demo run, 27 Oct).
MAX_RATE_WAIT_S = 6.0


class LLMError(RuntimeError):
    """The model call failed on the primary and the fallback model (outcome LLM_ERROR)."""


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, fallback_model: str | None = None,
                 extra_headers: dict | None = None, timeout_s: float = 30.0, temperature: float = 0.1,
                 more_models: tuple[str, ...] = (), route_model: str | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        # an explicit User-Agent: Groq sits behind Cloudflare, which refuses Python's default "Python-urllib" (403, 1010)
        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                        "User-Agent": "eka-agent/1.0", **(extra_headers or {})}
        self.models = list(dict.fromkeys(m for m in (model, fallback_model, *more_models) if m))
        self.route_model = route_model
        self.timeout_s = timeout_s
        self.temperature = temperature

    def order(self, purpose: str) -> list[str]:
        """The models to try. The planner starts on its own model (app.yaml llm.route_model), so route and answer
        calls use two separate per-minute limits."""
        if purpose == "route" and self.route_model:
            return [self.route_model, *(m for m in self.models if m != self.route_model)]
        return self.models

    def complete(self, system: str, user: str, *, purpose: str, json_mode: bool = True) -> LLMReply:
        """Try the models in order. Groq retires models without notice (contract 06) and limits each one per minute,
        so a short 429 is waited out once and anything else moves on to the next model."""
        errors = []
        for model in self.order(purpose):
            for attempt in (1, 2):
                try:
                    return self._call(model, system, user, json_mode)
                except urllib.error.HTTPError as error:            # before CALL_ERRORS: it is also a URLError
                    body = error.read().decode(errors="replace")
                    wait = _retry_after(error, body)
                    if error.code == 429 and attempt == 1 and wait is not None and wait <= MAX_RATE_WAIT_S:
                        time.sleep(wait)
                        continue
                    errors.append(f"{model}: HTTP {error.code} {body[:200]}")
                except CALL_ERRORS as error:
                    errors.append(f"{model}: {_short(error)}")
                break
        raise LLMError("; ".join(errors))

    def _call(self, model: str, system: str, user: str, json_mode: bool) -> LLMReply:
        body = {"model": model, "temperature": self.temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=self.headers, method="POST")
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            data = json.loads(response.read())
            cache_hit = response.headers.get("x-portkey-cache-status", "").upper() == "HIT"
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _reply(_content(data), data.get("model", model), data.get("usage"), system + user, latency_ms,
                      cache_hit)


def _content(data: object) -> str:
    """The reply text. A body of another shape (a list, "choices": null) is the provider's fault: ValueError."""
    choices = data.get("choices") if isinstance(data, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("the reply has no choices[0].message")
    return message.get("content") or ""


def _reply(text: str, model: str, usage: dict | None, prompt: str, latency_ms: int, cache_hit: bool) -> LLMReply:
    if not usage:
        # 11 section 4: no provider numbers, so estimate (about 4 characters a token) and say so
        return LLMReply(text, model, len(prompt) // 4, len(text) // 4, 0, latency_ms, cache_hit, "ESTIMATED")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    return LLMReply(text, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), cached,
                    latency_ms, cache_hit, "PROVIDER")


def _retry_after(error: urllib.error.HTTPError, body: str) -> float | None:
    """Seconds to wait, from the Retry-After header or Groq's "Please try again in 1.2s" (or "850ms")."""
    header = error.headers.get("retry-after") if error.headers else None
    try:
        if header is not None:
            return float(header)
    except ValueError:
        pass
    found = re.search(r"try again in ([\d.]+)\s*(ms|s)\b", body)
    if not found:
        return None
    value = float(found.group(1))
    return value / 1000 if found.group(2) == "ms" else value


def _short(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code} {error.read()[:200].decode(errors='replace')}"
    return str(error)[:200]


def llm_from_env() -> OpenAICompatibleLLM:
    """Build the client from environment variables (names in model/.env.example). Keys never live in code."""
    headers = {}
    if os.getenv("PORTKEY_API_KEY"):
        headers["x-portkey-api-key"] = os.environ["PORTKEY_API_KEY"]
        if os.getenv("PORTKEY_CONFIG_SLUG"):
            headers["x-portkey-config"] = os.environ["PORTKEY_CONFIG_SLUG"]
    return OpenAICompatibleLLM(
        base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", "openai/gpt-oss-120b"),
        fallback_model=os.getenv("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b"),
        extra_headers=headers,
        # comma list, for example "qwen/qwen3.8-27b,openai/gpt-oss-safeguard-20b": more models, more per-minute room
        more_models=tuple(m.strip() for m in os.getenv("LLM_MORE_MODELS", "").split(",") if m.strip()),
        route_model=os.getenv("LLM_ROUTE_MODEL") or None,
    )
