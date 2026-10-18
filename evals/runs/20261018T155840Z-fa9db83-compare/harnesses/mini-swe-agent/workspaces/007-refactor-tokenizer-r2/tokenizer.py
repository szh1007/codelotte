import re


def tokenize(text: str) -> list[str]:
    """Return lowercase tokens split on whitespace and .,!? punctuation."""
    return re.findall(r"[^\s.,!?]+|[.,!?]", text.lower())
