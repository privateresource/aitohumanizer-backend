import re

MAX_INPUT_LENGTH = 10000

_PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|below)\s+instructions",
    r"ignore\s+(all\s+)?prior\s+directions",
    r"disregard\s+(all\s+)?(previous|above|below)",
    r"forget\s+(all\s+)?(previous|prior)\s+(instructions|prompts|context)",
    r"you\s+(are\s+)?(now|will\s+now)\s+(\w+\s+){0,5}(free|unleashed|unbounded)",
    r"new\s+instructions?\s*:",
    r"override\s+(all\s+)?(instructions|prompts|commands)",
    r"system\s+prompt\s*:",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
]

_INJECTION_REGEX = re.compile(
    "|".join(_PROMPT_INJECTION_PATTERNS),
    re.IGNORECASE,
)

_HTML_TAG_REGEX = re.compile(r"<[^>]*>")

# Markdown table: lines starting with | or containing |---|
_TABLE_LINE = re.compile(r"^\s*\|.*\|.*\|", re.MULTILINE)
_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s\-:|]+\|\s*$", re.MULTILINE)

# "**...**" labels followed by content — AI analysis signatures
_AI_LABEL = re.compile(r"^\*{2}.*?\*{2}.*?(?:\n|$)", re.MULTILINE)

# Sections starting with "Revised text", "Here is", "Changes made", etc.
_INTRO_PATTERNS = [
    r"^(?:Revised|Here\s+is|Below\s+is|The\s+(?:revised|humanized|rewritten))\s+.*?(?:\n|$)",
    r"^(?:Changes?\s+(?:made|applied)|Summary\s+of\s+changes).*?(?:\n|$)",
    r"^(?:I['']ve\s+(?:rewritten|humanized|revised|fixed)).*?(?:\n|$)",
    r"^\*{1,2}Identified.*?\*{1,2}.*?(?:\n|$)",
]
_INTRO_REGEX = re.compile("|".join(_INTRO_PATTERNS), re.IGNORECASE | re.MULTILINE)


def sanitize_input(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""

    text = text.strip()

    text = _HTML_TAG_REGEX.sub("", text)

    if len(text) > MAX_INPUT_LENGTH:
        text = text[:MAX_INPUT_LENGTH]

    return text


def clean_llm_output(text: str) -> str:
    """Strip analysis artifacts (tables, labels, audit notes) from LLM output.
    Defense-in-depth: the prompt should prevent these, but if they slip through,
    this ensures clean output for the API consumer."""
    if not text or not isinstance(text, str):
        return ""

    text = text.strip()

    text = _TABLE_SEPARATOR.sub("", text)
    text = _TABLE_LINE.sub("", text)

    text = _INTRO_REGEX.sub("", text)

    text = _AI_LABEL.sub("", text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def detect_prompt_injection(text: str) -> bool:
    if not text:
        return False
    return bool(_INJECTION_REGEX.search(text))
