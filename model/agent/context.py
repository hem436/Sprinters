"""Rule M1 (contract 04): which earlier turns the model may see."""
from agent.config import AgentConfig
from agent.safety import mask_pii
from agent.types import Turn


def select_context(history: list[Turn], cfg: AgentConfig) -> list[Turn]:
    """04 M1: the last `ctx_max_turns` turns, never a blocked one, each PII-masked and cut to `ctx_max_chars_per_turn`.

    Case section 3 asks for conversation context used "safely", and 8.2 asks to exclude hidden or sensitive content.
    """
    allowed = [t for t in history if not t.blocked]
    recent = allowed[-cfg.ctx_max_turns:] if cfg.ctx_max_turns > 0 else []
    selected = []
    for turn in recent:
        masked, _ = mask_pii(turn.text)
        selected.append(Turn(role=turn.role, text=masked[: cfg.ctx_max_chars_per_turn]))
    return selected
