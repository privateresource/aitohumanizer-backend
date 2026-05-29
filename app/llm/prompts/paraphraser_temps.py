# Per-mode temperature settings for the paraphraser tool.
# Edit this file to change temperatures at any time.

PARAPHRASE_TEMPS = {
    "standard": 0.8,
    "fluency": 0.9,
    "formal": 0.7,
    "casual": 1.0,
    "shorten": 0.7,
    "expand": 0.9,
    "creative": 1.0,
    "academic": 0.6,
    "professional": 0.7,
}


def get_paraphrase_temperature(mode: str) -> float:
    return PARAPHRASE_TEMPS.get(mode, 0.8)
