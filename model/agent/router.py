"""Rules R1 and R1b (contract 04, contract 14 section 7): choose documents, data, both, or small talk."""
import json
import re
from pathlib import Path

from agent.ports import LLMPort, ToolPort
from agent.types import LLMReply, RouteDecision, Turn

ROUTE_PROMPT_VERSION = "route-v1"
_PROMPT = (Path(__file__).parent.parent / "prompts" / "route-v1.txt").read_text(encoding="utf-8")

# R1: identifiers that only the business data holds (contract 13 schema).
_DATA_IDS = re.compile(r"\b(P-\d{3}|EXP-\d+|D-[A-Z]{2,}|LT-\d+|E\d{4})\b")
# R1: words that ask for a computed number.
_DATA_WORDS = re.compile(r"\b(total|how many|count|spent|spend|budget|headcount|sum|average|overspen\w*|over budget)\b", re.I)
# R1b: financial-report numbers (contract 14 section 7): a metric with a period, or a comparison word.
_METRIC_WORDS = re.compile(r"\b(revenue|profit|pat|pbt|ebitda|margin|eps|income|cash flow|borrowings|segment)\b", re.I)
_PERIOD = re.compile(r"\b(FY\s?\d{2,4}(-\d{2})?|20\d{2}|Q[1-4])\b", re.I)
_COMPARE_WORDS = re.compile(r"\b(compare|comparison|growth|grew|trend|by segment|versus|vs\.?)\b", re.I)
# R1: words that ask what a document says.
_DOC_WORDS = re.compile(r"\b(policy|policies|rule|procedure|sop|guideline|says?|allowed|approv\w*|why|explain|reason|outlook|risk|require\w*)\b", re.I)
_GREETING = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))\b[\s!.?]*$", re.I)


def rule_signals(question: str) -> tuple[bool, bool]:
    """R1 and R1b: (needs data, needs documents) from the question's words alone."""
    financial = bool(_METRIC_WORDS.search(question)) and bool(_PERIOD.search(question) or _COMPARE_WORDS.search(question))
    needs_data = bool(_DATA_IDS.search(question) or _DATA_WORDS.search(question)) or financial
    needs_docs = bool(_DOC_WORDS.search(question))
    return needs_data, needs_docs


def apply_rules(planner: RouteDecision, question: str) -> RouteDecision:
    """R1: the rules override the planner's route when the words clearly need data.

    SQL when the question has no document words, BOTH when it also asks about a policy, rule or procedure.
    """
    needs_data, needs_docs = rule_signals(question)
    if not needs_data:
        return planner
    route = "BOTH" if needs_docs else "SQL"
    if route == planner.route:
        return planner
    return RouteDecision(route, planner.standalone_query, planner.tool, planner.tool_args, reason="RULE_OVERRIDE")


def parse_planner(text: str, question: str) -> RouteDecision:
    """Read the planner's JSON. Anything invalid falls back to DOCS with reason ROUTE_FALLBACK (04 R1)."""
    try:
        data = json.loads(_strip_fences(text))
        route = data["route"]
        if route not in ("DOCS", "SQL", "BOTH", "CONVERSATIONAL"):
            raise ValueError(route)
        query = str(data.get("standalone_query") or question)
        args = data.get("tool_args") or {}
        if not isinstance(args, dict):
            raise ValueError("tool_args")
        return RouteDecision(route, query, data.get("tool") or None, args)
    except (ValueError, KeyError, TypeError):
        return RouteDecision("DOCS", question, reason="ROUTE_FALLBACK")


def route_question(question: str, context: list[Turn], llm: LLMPort, tools: ToolPort) -> tuple[RouteDecision, LLMReply | None]:
    """R1: greetings by rule; otherwise ask the planner, then let the rules correct the route."""
    if _GREETING.match(question):
        return RouteDecision("CONVERSATIONAL", question, reason="RULE_GREETING"), None
    system = _PROMPT.replace("{tools}", json.dumps(tools.list_tools(), indent=1))
    reply = llm.complete(system, _planner_input(question, context), purpose="route")
    return apply_rules(parse_planner(reply.text, question), question), reply


def _planner_input(question: str, context: list[Turn]) -> str:
    history = "\n".join(f"{t.role}: {t.text}" for t in context)
    return f"Conversation so far:\n{history or '(none)'}\n\nLatest question: {question}"


def _strip_fences(text: str) -> str:
    """Models sometimes wrap JSON in ``` fences; remove them before parsing."""
    return re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
