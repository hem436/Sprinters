"""AI-5 and AI-4 (contract 06): one client for any OpenAI-compatible chat endpoint (Groq directly, or Portkey).

Standard library only (urllib), so the agent adds no SDK dependency. Usage numbers come from the provider's `usage`
object (11 section 4); when it is missing, tokens are estimated and labelled ESTIMATED.
"""
import http.client
import json
import math
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
# Contract 06: AI-4 (route) 10 s, AI-5 (answer) 30 s, for all models and waits of one call together (review #25)
DEADLINE_S = {"route": 10.0, "answer": 30.0, "repair": 30.0}
DEFAULT_ROUTE_MODEL = "openai/gpt-oss-20b"      # backend/config/app.yaml llm.route_model


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
        """The models to try. The planner starts on its own model (app.yaml llm.route_model); answers try that model
        last, so route and answer calls use separate per-minute limits as long as the others work (review #25)."""
        others = [m for m in self.models if m != self.route_model]
        if not self.route_model:
            return self.models
        return [self.route_model, *others] if purpose == "route" else [*others, self.route_model]

    def complete(self, system: str, user: str, *, purpose: str, json_mode: bool = True) -> LLMReply:
        """Try the models in order. Groq retires models without notice (contract 06) and limits each one per minute,
        so a short 429 is waited out once and anything else moves on to the next model. The whole call keeps to the
        deadline of contract 06 (DEADLINE_S); what is left of it is also each request's timeout."""
        errors, deadline = [], time.monotonic() + DEADLINE_S.get(purpose, self.timeout_s)
        for model in self.order(purpose):
            for attempt in (1, 2):
                left = deadline - time.monotonic()
                if left <= 0:
                    errors.append(f"{model}: not tried, the {purpose} deadline passed")
                    raise LLMError("; ".join(errors))
                try:
                    return self._call(model, system, user, json_mode, timeout_s=min(self.timeout_s, left))
                except urllib.error.HTTPError as error:            # before CALL_ERRORS: it is also a URLError
                    body = _error_body(error)
                    wait = _retry_after(error, body)
                    if (error.code == 429 and attempt == 1 and wait is not None and wait <= MAX_RATE_WAIT_S
                            and wait < deadline - time.monotonic()):
                        time.sleep(wait)
                        continue
                    errors.append(f"{model}: HTTP {error.code} {body[:200]}")
                except CALL_ERRORS as error:
                    errors.append(f"{model}: {str(error)[:200]}")
                break
        raise LLMError("; ".join(errors))

    def _call(self, model: str, system: str, user: str, json_mode: bool, timeout_s: float | None = None) -> LLMReply:
        body = {"model": model, "temperature": self.temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=self.headers, method="POST")
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=timeout_s or self.timeout_s) as response:
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


def _error_body(error: urllib.error.HTTPError) -> str:
    """The provider's error text; "" when the socket drops while it is read (review #25)."""
    try:
        return error.read().decode(errors="replace")
    except CALL_ERRORS:
        return ""


def _retry_after(error: urllib.error.HTTPError, body: str) -> float | None:
    """Seconds to wait, from the Retry-After header or Groq's "Please try again in 1.2s" (or "850ms"). Only a finite
    value of 0 or more counts: "-1", "inf" or "1.2.3s" mean no wait (review #25)."""
    value = None
    header = error.headers.get("retry-after") if error.headers else None
    if header is not None:
        try:
            value = float(header)
        except ValueError:
            value = None
    if value is None:
        found = re.search(r"try again in (\d+(?:\.\d+)?)\s*(ms|s)\b", body)
        if found:
            value = float(found.group(1)) / (1000 if found.group(2) == "ms" else 1)
    return value if value is not None and math.isfinite(value) and value >= 0 else None


def llm_from_env(route_model: str | None = None) -> OpenAICompatibleLLM:
    """Build the client from environment variables (names in model/.env.example). Keys never live in code.

    The planner model: LLM_ROUTE_MODEL if set, else the caller's value (the back end passes app.yaml llm.route_model),
    else DEFAULT_ROUTE_MODEL (review #25)."""
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
        route_model=os.getenv("LLM_ROUTE_MODEL") or route_model or DEFAULT_ROUTE_MODEL,
    )
