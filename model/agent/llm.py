"""AI-5 and AI-4 (contract 06): one client for any OpenAI-compatible chat endpoint (Groq directly, or Portkey).

Standard library only (urllib), so the agent adds no SDK dependency. Usage numbers come from the provider's `usage`
object (11 section 4); when it is missing, tokens are estimated and labelled ESTIMATED.
"""
import http.client
import json
import os
import time
import urllib.error
import urllib.request

from agent.types import LLMReply

# Every way one call can fail: network (URLError, OSError, dropped connection), time, a body that is not the
# expected JSON (ValueError, KeyError, IndexError, TypeError). Each sends us to the fallback model (review #25).
CALL_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError,
               ValueError, KeyError, IndexError, TypeError)


class LLMError(RuntimeError):
    """The model call failed on the primary and the fallback model (outcome LLM_ERROR)."""


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, fallback_model: str | None = None,
                 extra_headers: dict | None = None, timeout_s: float = 30.0, temperature: float = 0.1):
        self.url = base_url.rstrip("/") + "/chat/completions"
        # an explicit User-Agent: Groq sits behind Cloudflare, which refuses Python's default "Python-urllib" (403, 1010)
        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                        "User-Agent": "eka-agent/1.0", **(extra_headers or {})}
        self.models = [m for m in (model, fallback_model) if m]
        self.timeout_s = timeout_s
        self.temperature = temperature

    def complete(self, system: str, user: str, *, purpose: str, json_mode: bool = True) -> LLMReply:
        """Try the primary model, then the fallback once. Groq retires models without notice (contract 06)."""
        errors = []
        for model in self.models:
            try:
                return self._call(model, system, user, json_mode)
            except CALL_ERRORS as error:
                errors.append(f"{model}: {_short(error)}")
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
        text = data["choices"][0]["message"]["content"] or ""
        return _reply(text, data.get("model", model), data.get("usage"), system + user, latency_ms, cache_hit)


def _reply(text: str, model: str, usage: dict | None, prompt: str, latency_ms: int, cache_hit: bool) -> LLMReply:
    if not usage:
        # 11 section 4: no provider numbers, so estimate (about 4 characters a token) and say so
        return LLMReply(text, model, len(prompt) // 4, len(text) // 4, 0, latency_ms, cache_hit, "ESTIMATED")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    return LLMReply(text, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), cached,
                    latency_ms, cache_hit, "PROVIDER")


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
    )
