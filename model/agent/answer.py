"""Rules A1 to A4 and G1 (contract 04): evidence, the answer prompt, the answer JSON, the fixed fallback texts."""
import html
import json
import re
from pathlib import Path

from pydantic import ValidationError

from agent.retrieval import Conflict
from agent.safety import PROMPT_CANARY
from agent.types import AnswerJSON, Evidence, ScoredChunk, ToolResult, Turn

ANSWER_PROMPT_VERSION = "answer-v1"
_SYSTEM = (Path(__file__).parent.parent / "prompts" / "answer-v1.txt").read_text(encoding="utf-8")

# 04 G1, 13 section 5: fixed texts, never written by the model
NO_EVIDENCE_TEXT = "I could not find this in the approved documents or data."
NO_TOOL_TEXT = "I cannot answer this from the approved data."
TOOL_UNAVAILABLE_TEXT = "The business data is not available right now, so I cannot give those numbers."
BLOCKED_TEXT = "I can only answer questions about the company's approved documents and data."


def estimate_tokens(text: str) -> int:
    """About 4 characters per token for English; used only for the evidence budget (A4), not for cost."""
    return len(text) // 4 + 1


def build_evidence(ranked: list[ScoredChunk], conflicts: list[Conflict], tools: list[ToolResult],
                   max_tokens: int) -> list[Evidence]:
    """04 A1 and A4: number the evidence, tool results first (T1...), then chunks by rank (E1...).

    Each chunk is followed at once by its other versions found by rule C1, so a conflict is never cut in half by the
    budget (review #25). Chunks are dropped from the lowest rank once the budget is used.
    """
    items = [Evidence(f"T{i}", "tool", _tool_text(t), tool=t) for i, t in enumerate(tools, start=1)]
    used = sum(estimate_tokens(e.text) for e in items)
    versions = {(c.doc_key, c.section): c.versions for c in conflicts}
    chunks = [v for s in ranked for v in [s.chunk, *versions.get((s.chunk.doc_key, s.chunk.section), [])]]
    seen = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        cost = estimate_tokens(chunk.text)
        if used + cost > max_tokens:
            break
        seen.add(chunk.chunk_id)
        used += cost
        items.append(Evidence(f"E{len(seen)}", "document", chunk.text, chunk=chunk))
    return items


def build_prompt(question: str, context: list[Turn], evidence: list[Evidence]) -> tuple[str, str]:
    """04 A1: evidence goes inside tags with its source, so the model can cite it and treats it as data."""
    system = _SYSTEM.replace("{canary}", PROMPT_CANARY)
    tags = [_evidence_tag(e) for e in evidence]
    history = "\n".join(f"{t.role}: {t.text}" for t in context) or "(none)"
    user = f"Evidence:\n" + "\n".join(tags) + f"\n\nConversation so far:\n{history}\n\nQuestion: {question}"
    return system, user


def parse_answer(text: str) -> AnswerJSON:
    """04 A2 and V3: the reply must be the answer JSON. Raises ValueError otherwise (the caller repairs once)."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        return AnswerJSON.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValueError(f"answer is not valid JSON: {error}") from error


REPAIR_INSTRUCTION = ("Your last reply was not valid JSON for the required shape. Reply again with ONE JSON object: "
                      '{"answer_markdown": "...", "claims": [{"text": "...", "citations": ["E1"]}], '
                      '"insufficient_evidence": false, "conflict": false}')


def _evidence_tag(e: Evidence) -> str:
    """Escaped, so a document cannot close its own tag and pretend to be other evidence (review #25)."""
    if e.kind == "tool":
        return (f'<tool_result id="{e.id}" tool="{_attr(e.tool.tool)}" status="{e.tool.status}">'
                f'{_text(e.text)}</tool_result>')
    c = e.chunk
    return (f'<evidence id="{e.id}" doc="{_attr(c.title)}" version="{_attr(c.version)}" '
            f'effective="{_attr(c.effective_date)}" page="{c.page}" section="{_attr(c.section)}">'
            f'{_text(e.text)}</evidence>')


def _attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _text(value: str) -> str:
    """Only the angle brackets: the text keeps its own "&" and quotes, so numbers and names reach the model as printed."""
    return value.replace("<", "&lt;").replace(">", "&gt;")


def _tool_text(result: ToolResult) -> str:
    """13 section 5: the tool's own summary carries the exact numbers; the model only quotes them."""
    if result.status in ("OK", "EMPTY"):
        return result.summary
    return f"The tool {result.tool} did not return data ({result.status}). {result.message}".strip()
