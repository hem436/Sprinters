"""POST /query and POST /query/stream (contract 05): Arka's agent with Myank's search, our tools and recorder.

The agent is built once, on the first question. X-Request-Id is the query_id. The stream sends a `status`
event as each stage starts, then `citations`, `token` (the answer text) and `done` with the QueryResponse;
a failure is an `error` event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.errors import ApiError, error_body
from app.config import Config, get_config
from app.observability.outcome import OutcomeFacts
from app.observability.recorder import QueryRecorder
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)
router = APIRouter(tags=["query"])

# The web app's stage names for the stream (web/src/api/types.ts); the store keeps contract 11's names.
STREAM_STAGE = {"plan": "route", "generate": "answer"}


class Filters(BaseModel):
    category: str | None = None
    doc_key: str | None = None
    current_only: bool | None = None


class QueryRequest(BaseModel):
    question: str = Field(max_length=4000)
    session_id: str = Field(min_length=1, max_length=100)
    filters: Filters | None = None
    config_id: Literal["A", "B"] | None = None


_agent = None
_agent_lock = threading.Lock()


def build_agent(config: Config):
    """Agent(search, tools, llm, reranker) as in model/README.md."""
    from agent.llm import llm_from_env
    from agent.retrieval import FlashRankReranker
    from agent.service import Agent
    from ingestion.search import SearchService

    tools = ToolRegistry(config.paths.resolve(config.paths.business_db),
                         config.paths.resolve(config.paths.knowledge_db),
                         simulate_failure=bool(config.get("tools.simulate_failure", False)))
    return Agent(search=SearchService(), tools=tools, llm=llm_from_env(), reranker=FlashRankReranker())


def get_agent(config: Config = Depends(get_config)):
    global _agent
    with _agent_lock:
        if _agent is None:
            try:
                _agent = build_agent(config)
            except Exception as exc:                  # missing package, key or index: say so, do not crash
                log.exception("could not build the agent")
                raise ApiError(503, "LLM_UNAVAILABLE", f"The assistant is not available: {exc}") from exc
        return _agent


class _StreamingRecorder(QueryRecorder):
    """Reports each stage to the stream as it starts; everything else is the normal recorder."""

    def __init__(self, *args: Any, emit, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._emit = emit

    @contextmanager
    def stage(self, name: str, **kwargs: Any) -> Iterator[Any]:
        self._emit("status", {"stage": STREAM_STAGE.get(name, name)})
        with super().stage(name, **kwargs) as handle:
            yield handle


def _answer(agent, body: QueryRequest, recorder: QueryRecorder):
    filters = body.filters.model_dump(exclude_none=True) if body.filters else None
    try:
        return agent.answer(body.question, body.session_id, recorder, filters=filters, config_id=body.config_id)
    except Exception:
        # The agent handles model and tool failures itself; anything else is recorded as a system error.
        log.exception("the agent failed", extra={"query_id": recorder.query_id})
        recorder.finish(None, None, facts=OutcomeFacts(system_error=True), error_category="SYSTEM_ERROR",
                        http_status=500)
        raise


def _check(body: QueryRequest) -> None:
    if not body.question.strip():
        raise ApiError(422, "EMPTY_QUESTION", "Type a question first.", [{"field": "question", "problem": "empty"}])


def _config_id(agent, body: QueryRequest) -> str:
    return body.config_id or agent.cfg.config_id


@router.post("/query")
async def query(body: QueryRequest, request: Request, agent=Depends(get_agent)) -> JSONResponse:
    _check(body)
    recorder = QueryRecorder.start(body.question, body.session_id, _config_id(agent, body),
                                   correlation_id=request.state.request_id)
    response = await asyncio.to_thread(_answer, agent, body, recorder)
    return JSONResponse(response.model_dump(), headers={"X-Request-Id": response.query_id})


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/query/stream")
async def query_stream(body: QueryRequest, request: Request, agent=Depends(get_agent)) -> StreamingResponse:
    _check(body)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def emit(event: str, data: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    recorder = _StreamingRecorder(body.question, body.session_id, _config_id(agent, body),
                                  correlation_id=request.state.request_id, emit=emit)

    async def events() -> AsyncIterator[str]:
        task = asyncio.create_task(asyncio.to_thread(_answer, agent, body, recorder))
        while not task.done() or not queue.empty():
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield _sse(event, data)
            except asyncio.TimeoutError:
                continue
        try:
            response = task.result()
        except Exception:
            yield _sse("error", error_body("INTERNAL_ERROR", "Something went wrong on our side.")["error"])
            return
        payload = response.model_dump()
        yield _sse("citations", {"citations": payload["citations"]})
        yield _sse("token", {"text": payload["answer_markdown"]})
        yield _sse("done", payload)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"X-Request-Id": recorder.query_id, "Cache-Control": "no-cache"})
