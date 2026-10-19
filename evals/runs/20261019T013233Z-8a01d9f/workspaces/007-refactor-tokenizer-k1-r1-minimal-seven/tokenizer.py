"""Tokenizer implementing the contract in ``spec.md``."""

import re

# Whitespace splits tokens apart; each of these marks is a token of its own.
_SPLIT_RE = re.compile(r"[.,!?]|[^.,!?\s]+")


def tokenize(text: str) -> list[str]:
    """Split ``text`` into lowercase tokens.

    Tokens are separated by any whitespace and by the punctuation marks
    ``.`` ``,`` ``!`` ``?``, each of which becomes its own token. Everything
    else (including digits) is preserved verbatim, apart from lowercasing.

    >>> tokenize("Hello, world!")
    ['hello', ',', 'world', '!']
    >>> tokenize("  A  b. ")
    ['a', 'b', '.']
    >>> tokenize("x=1")
    ['x=1']
    """
    tokens = []
    for chunk in text.split():
        tokens.extend(_SPLIT_RE.findall(chunk.lower()))
    return [token for token in tokens if token]
