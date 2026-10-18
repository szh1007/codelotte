import re

# Only these characters act as separators (see spec.md); everything else,
# including digits and characters such as "=", is part of an ordinary token.
SEPARATORS = ".,!?"

_SPLIT_RE = re.compile(r"([%s])" % re.escape(SEPARATORS))


def tokenize(text: str) -> list[str]:
    """Split *text* into lowercase tokens.

    Whitespace separates tokens, each of the punctuation marks in
    ``SEPARATORS`` becomes a token of its own, and empty tokens are dropped.
    Numbers (e.g. ``"42"``) are left intact.
    """
    tokens = []
    for chunk in text.split():
        # re.split with a capturing group keeps the punctuation marks.
        for piece in _SPLIT_RE.split(chunk):
            if piece:
                tokens.append(piece.lower())
    return tokens
