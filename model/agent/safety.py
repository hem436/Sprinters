"""Safety rules S1, S2, S3 (contract 04) and the output check V4. Pure functions: text in, result out."""
import re

# S1 and S2: phrases that try to take control of the model. Used on questions (S1) and on evidence (S2).
INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (all |the )?(previous|prior|above|system) (instructions|rules|prompt)",
    r"you are now\b",
    r"\b(reveal|show|print|repeat) (me )?(your |the )?(system|hidden) prompt",
    r"\bdeveloper mode\b",
    r"\bjailbreak\b",
    r"act as (an? )?(unrestricted|unfiltered)",
]
_INJECTION = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

# S3: personal data. Order matters: the 16-digit card must be masked before the 12-digit Aadhaar and the phone.
# A number glued to a word or a dash is part of an id, not personal data: "EXP-9876543210" stays (review #25).
_PII = [
    ("[CARD]", re.compile(r"(?<![\w-])(?:\d{4}[ -]?){3}\d{4}(?![\w-])")),
    ("[AADHAAR]", re.compile(r"(?<![\w-])\d{4}[ -]?\d{4}[ -]?\d{4}(?![\w-])")),
    # Indian mobile: 10 digits starting 6 to 9, optional +91, optional space after 5 digits ("98765 43210").
    ("[PHONE]", re.compile(r"(?<![\w-])(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?![\w-])")),
    ("[PAN]", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("[EMAIL]", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
]

# V4: a marker placed in the answer prompt. If it ever appears in an answer, the model leaked its instructions.
PROMPT_CANARY = "EKA-CANARY-7F3A"


def looks_like_injection(text: str) -> bool:
    """04 S2: True when the text tries to give the model instructions."""
    return any(p.search(text) for p in _INJECTION)


def guard_question(question: str) -> tuple[bool, str | None]:
    """04 S1: block a question that tries to take control of the assistant. Returns (blocked, reason)."""
    if not question.strip():
        return True, "EMPTY_QUESTION"
    if looks_like_injection(question):
        return True, "JAILBREAK"
    return False, None


def mask_pii(text: str) -> tuple[str, list[str]]:
    """04 S3: replace personal data with a label. Returns the masked text and the kinds found."""
    found = []
    for label, pattern in _PII:
        text, count = pattern.subn(lambda m, label=label: m.group(0) if _only_years(m.group(0)) else label, text)
        if count and label in text:
            found.append(label.strip("[]"))
    return text, found


_YEAR = re.compile(r"(?:19|20)\d\d")
PII_LABELS = re.compile(r"\[(?:CARD|AADHAAR|PHONE|PAN|EMAIL)\]")


def _only_years(digits: str) -> bool:
    """"2022 2023 2024" is three years in a financial question, not an Aadhaar number (review #25)."""
    groups = re.split(r"[ -]", digits)
    return len(groups) > 1 and all(_YEAR.fullmatch(g) for g in groups)


def check_output(answer: str, suspect_texts: list[str]) -> tuple[str, list[str]]:
    """04 V4: clean an answer before the user sees it. Returns the cleaned answer and the safety flags raised.

    suspect_texts are evidence chunks flagged `injection_suspect` that this query used.
    """
    flags = []
    if PROMPT_CANARY in answer:
        answer = answer.replace(PROMPT_CANARY, "")
        flags.append("PROMPT_LEAK")
    for sentence in _injection_sentences(suspect_texts):
        if sentence.lower() in answer.lower():
            answer = re.sub(re.escape(sentence), "", answer, flags=re.IGNORECASE)
            flags.append("INJECTION_ECHO")
    answer, pii = mask_pii(answer)
    if pii:
        flags.append("PII_IN_ANSWER")
    return answer.strip(), flags


def _injection_sentences(texts: list[str]) -> list[str]:
    """The sentences of suspect chunks that carry the injected instruction."""
    sentences = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if looks_like_injection(sentence) and len(sentence) >= 20:
                sentences.append(sentence.strip())
    return sentences
