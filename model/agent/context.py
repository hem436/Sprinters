"""Rule M1 (contract 04): which earlier turns the model may see."""
from agent.config import AgentConfig
from agent.safety import mask_pii
from agent.types import Turn


def select_context(history: list[Turn], cfg: AgentConfig) -> list[Turn]:
    """04 M1: the last `ctx_max_turns` exchanges (a question and its answer), never a blocked one, each message
    PII-masked and cut to `ctx_max_chars_per_turn`.

    Case section 3 asks for conversation context used "safely", and 8.2 asks to exclude hidden or sensitive content.
    A turn is an exchange, not a single message (review #25), so 3 turns are up to 6 messages.
    """
    exchanges = [ex for ex in _exchanges(history) if not ex[0].blocked]
    recent = exchanges[-cfg.ctx_max_turns:] if cfg.ctx_max_turns > 0 else []
    return [Turn(role=t.role, text=mask_pii(t.text)[0][: cfg.ctx_max_chars_per_turn]) for ex in recent for t in ex]


def _exchanges(history: list[Turn]) -> list[list[Turn]]:
    """Group the messages into exchanges: a user message and the assistant messages after it."""
    groups: list[list[Turn]] = []
    for turn in history:
        if turn.role == "user" or not groups:
            groups.append([turn])
        else:
            groups[-1].append(turn)
    return groups
