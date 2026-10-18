import re


def tokenize(text: str) -> list[str]:
    """Split text into lowercase word and punctuation tokens."""
    return re.findall(r"[.,!?]|[^\s.,!?]+", text.lower())
