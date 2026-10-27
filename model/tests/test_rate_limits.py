"""Groq's per-minute limits (demo run, 27 Oct): a short 429 is waited out once; the planner starts on its own model."""
import email.message
import io
import urllib.error

from agent.llm import OpenAICompatibleLLM
from agent.types import LLMReply


def _http_429(retry_after: str | None, body: str = "") -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return urllib.error.HTTPError("https://x", 429, "Too Many Requests", headers, io.BytesIO(body.encode()))


def _client(script, **kw):
    llm = OpenAICompatibleLLM("https://x", "k", "big", "small", **kw)
    calls = []

    def fake_call(model, system, user, json_mode):
        calls.append(model)
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return LLMReply("{}", model)

    llm._call = fake_call
    return llm, calls


def test_a_short_429_is_waited_out_on_the_same_model():
    llm, calls = _client([_http_429("0"), "ok"])
    assert llm.complete("s", "u", purpose="answer").model == "big" and calls == ["big", "big"]


def test_a_long_429_moves_to_the_next_model():
    llm, calls = _client([_http_429(None, "Please try again in 42.5s."), "ok"])
    assert llm.complete("s", "u", purpose="answer").model == "small" and calls == ["big", "small"]


def test_the_planner_starts_on_its_own_model():
    llm, calls = _client(["ok", "ok"], route_model="small", more_models=("third",))
    llm.complete("s", "u", purpose="route")
    llm.complete("s", "u", purpose="answer")
    assert calls == ["small", "big"] and llm.order("route") == ["small", "big", "third"]
