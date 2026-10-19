import re

_TOKEN_RE = re.compile(r"[.,!?]|[^\s.,!?]+")


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens per the contract in spec.md."""
    return [token.lower() for token in _TOKEN_RE.findall(text)]
