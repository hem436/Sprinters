"""Rules R1 and R1b (contract 04, contract 14 section 7): choose documents, data, both, or small talk."""
import json
import re
from dataclasses import replace
from pathlib import Path

from agent.llm import LLMError
from agent.ports import LLMPort, ToolPort
from agent.types import LLMReply, RouteDecision, Turn

ROUTE_PROMPT_VERSION = "route-v1"
_PROMPT = (Path(__file__).parent.parent / "prompts" / "route-v1.txt").read_text(encoding="utf-8")

# R1: identifiers that only the business data holds (contract 13 schema).
_DATA_IDS = re.compile(r"\b(P-\d{3}|EXP-\d+|D-[A-Z]{2,}|LT-\d+|E\d{4})\b")
# R1: words that ask for a computed number. Policies use them too ("How many days of paid leave?", "What is the meal
# budget per day?"), so they need data only when the question also names a thing the business data holds (review #25).
_MEASURE_WORDS = re.compile(r"\b(total|how many|count|spent|spend|sum|average|overspen\w*|budgets?)\b", re.I)
# R1: the things in the business data (contract 13 schema): projects, departments, assets, employees, claims, trips,
# headcount. A department name must not match inside a document id such as POL-HR-014. "claims" is plural on purpose:
# "submit a travel claim" is a policy question (C02), "how many claims are pending" is data. No word is in both lists,
# so "How much can I spend on a hotel per night?" is not data by itself (review #25, fifth).
_DATA_THINGS = re.compile(r"(?<![\w-])(projects?|departments?|laptops?|assets?|devices?|employees?|staff|claims|"
                          r"trips?|headcount|engineering|finance|human resources|operations)(?![\w-])", re.I)
# R1b: financial-report numbers (contract 14 section 7): a metric with a period, or a comparison word.
_METRIC_WORDS = re.compile(r"\b(revenue|profit|pat|pbt|ebitda|margin|eps|income|cash flow|borrowings|segment)\b", re.I)
_PERIOD = re.compile(r"\b(FY\s?\d{2,4}(-\d{2})?|20\d{2}|Q[1-4])\b", re.I)
_COMPARE_WORDS = re.compile(r"\b(compare|comparison|growth|grew|trend|by segment|versus|vs\.?)\b", re.I)
# R1: words that ask what a document says. "approved" is left out: "approved spend" is a status in the data (S02).
_DOC_WORDS = re.compile(r"\b(policy|policies|rule|procedure|sop|guideline|says?|allowed|approv(e|es|al|als|er|ers|ing)|"
                        r"why|explain|reason|outlook|risk|require\w*)\b", re.I)
_GREETING = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))\b[\s!.?]*$", re.I)
# R1: the only questions the planner may call small talk. "Who is the CEO of Arka Fintech?" is a question about the
# company: it must search the documents and say "could not find", not greet (FR-07, FR-10).
_SMALLTALK = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok(ay)?|bye|goodbye|good (morning|afternoon|evening)|"
                        r"who are you|what can you do|how are you|what do you do|help)\b[\s\w,!.?']{0,20}$", re.I)


def rule_signals(question: str) -> tuple[bool, bool]:
    """R1 and R1b: (needs data, needs documents) from the question's words alone."""
    financial = bool(_METRIC_WORDS.search(question)) and bool(_PERIOD.search(question) or _COMPARE_WORDS.search(question))
    needs_docs = bool(_DOC_WORDS.search(question))
    measure = bool(_MEASURE_WORDS.search(question)) and bool(_DATA_THINGS.search(question))
    needs_data = bool(_DATA_IDS.search(question)) or measure or financial
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


FORCE_DATA_NOTE = ("\n\nThe question needs business data. Reply with route {route}, the one tool that fits and its "
                   "arguments, or \"tool\": null if no tool fits.")
FIX_ARGS_NOTE = ("\n\nThe tool {tool} refused these arguments: {args}. The reason: {message}. Reply with route {route}, "
                 "the same tool, and corrected tool_args that follow the tool's argument schema.")


def fix_tool_args(question: str, context: list[Turn], decision: RouteDecision, message: str, llm: LLMPort,
                  tools: ToolPort) -> tuple[RouteDecision | None, list[LLMReply]]:
    """T2 (contract 13 section 5): the tool refused the planner's arguments (ARGS_INVALID). Ask the planner once
    more, with the tool's own message ("metric: Input should be 'segment_revenue'"). Returns the corrected decision,
    or None when the planner changes nothing, picks another tool, or fails; then the first result stands."""
    catalogue = tools.list_tools()
    system = _PROMPT.replace("{tools}", json.dumps(catalogue, indent=1))
    note = FIX_ARGS_NOTE.format(tool=decision.tool, args=json.dumps(decision.tool_args), message=message[:300],
                                route=decision.route)
    try:
        reply = llm.complete(system, _planner_input(question, context) + note, purpose="route")
    except LLMError:
        return None, []
    fixed = only_approved(parse_planner(reply.text, question), {t["name"] for t in catalogue})
    if fixed.tool != decision.tool or fixed.tool_args == decision.tool_args:
        return None, [reply]
    return replace(decision, tool_args=fixed.tool_args), [reply]


def route_question(question: str, context: list[Turn], llm: LLMPort, tools: ToolPort) -> tuple[RouteDecision, list[LLMReply]]:
    """R1: greetings by rule; otherwise ask the planner, then let the rules correct the route.

    A rule override changes the route but cannot choose a tool, so the planner is asked once more for the tool
    (an extra model call only in that case). If no approved tool fits even then, the words were not about the
    business data ("How many days of paid leave do employees get?"), so the planner's own route stands, with reason
    ROUTE_NO_TOOL (review #25, fourth). A data route that still has no tool is settled by settle_tool().
    """
    if _GREETING.match(question):
        return RouteDecision("CONVERSATIONAL", question, reason="RULE_GREETING"), []
    catalogue = tools.list_tools()
    approved = {t["name"] for t in catalogue}
    system = _PROMPT.replace("{tools}", json.dumps(catalogue, indent=1))
    user = _planner_input(question, context)
    replies = [llm.complete(system, user, purpose="route")]
    planner = only_approved(parse_planner(replies[0].text, question), approved)
    decision = apply_rules(planner, question)
    if decision.reason == "RULE_OVERRIDE" and decision.tool is None:
        note = ""
        try:
            replies.append(llm.complete(system, user + FORCE_DATA_NOTE.format(route=decision.route), purpose="route"))
            second = only_approved(parse_planner(replies[-1].text, question), approved)
            decision = RouteDecision(decision.route, decision.standalone_query, second.tool, second.tool_args,
                                     "RULE_OVERRIDE")
        except LLMError as error:
            note = f"tool re-ask failed: {str(error)[:200]}"     # recorded in the plan stage, never silent
        if decision.tool is None:
            decision = _planners_route(planner, note)
    return settle_tool(only_real_smalltalk(decision, question)), replies


def only_real_smalltalk(decision: RouteDecision, question: str) -> RouteDecision:
    """R1: the planner's CONVERSATIONAL stands only for real small talk; any other question searches the documents,
    so a question we cannot answer gets the honest "could not find" (G1), never a greeting."""
    if decision.route != "CONVERSATIONAL" or _SMALLTALK.match(question):
        return decision
    return RouteDecision("DOCS", decision.standalone_query or question, reason="RULE_OVERRIDE")


def _planners_route(planner: RouteDecision, note: str) -> RouteDecision:
    """No approved tool fits the data words, so the planner's own route stands (review #25, fourth and fifth).

    A data word is never small talk, so CONVERSATIONAL becomes DOCS; the planner's own reason (ROUTE_FALLBACK after
    broken JSON) is kept, and only a normal planner answer becomes ROUTE_NO_TOOL."""
    route = planner.route if planner.route in ("DOCS", "SQL", "BOTH") else "DOCS"
    reason = "ROUTE_NO_TOOL" if planner.reason == "PLANNER" else planner.reason
    return RouteDecision(route, planner.standalone_query, planner.tool, planner.tool_args, reason, note)


def only_approved(decision: RouteDecision, approved: set[str]) -> RouteDecision:
    """13 section 4: the planner may only name a tool from the registry. Any other name means "no tool" (review #25)."""
    if decision.tool is None or decision.tool in approved:
        return decision
    return RouteDecision(decision.route, decision.standalone_query, None, {}, decision.reason)


def settle_tool(decision: RouteDecision) -> RouteDecision:
    """A data route with no tool. SQL keeps its route, so the user hears "cannot answer this from the approved data"
    (13 section 5, NO_TOOL). BOTH drops to documents only, so a document answer is not marked as a failed tool."""
    if decision.route == "BOTH" and decision.tool is None:
        return RouteDecision("DOCS", decision.standalone_query, reason="ROUTE_NO_TOOL", note=decision.note)
    return decision


def _planner_input(question: str, context: list[Turn]) -> str:
    history = "\n".join(f"{t.role}: {t.text}" for t in context)
    return f"Conversation so far:\n{history or '(none)'}\n\nLatest question: {question}"


def _strip_fences(text: str) -> str:
    """Models sometimes wrap JSON in ``` fences; remove them before parsing."""
    return re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
