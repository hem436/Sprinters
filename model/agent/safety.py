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
_PII = [
    ("[CARD]", re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")),
    ("[AADHAAR]", re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")),
    # Indian mobile: 10 digits starting 6 to 9, optional +91, optional space after 5 digits ("98765 43210").
    ("[PHONE]", re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)")),
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
        text, count = pattern.subn(label, text)
        if count:
            found.append(label.strip("[]"))
    return text, found


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
