"""Tokenizer implementation following the contract in ``spec.md``."""

import re

# The only characters treated as separators: each becomes its own token.
PUNCTUATION = ".,!?"
_SPLIT_RE = re.compile(r"([" + re.escape(PUNCTUATION) + r"])")


def tokenize(text: str) -> list[str]:
    """Return lowercase tokens for ``text``.

    - tokens are lowercase (1)
    - whitespace splits tokens (2)
    - ``.`` ``,`` ``!`` ``?`` are separated from words, one token each (3)
    - empty tokens are dropped (4)
    - numbers and any other characters are kept intact (5)
    """
    tokens = []
    for chunk in text.split():
        for piece in _SPLIT_RE.split(chunk):
            if piece:
                tokens.append(piece.lower())
    return tokens
