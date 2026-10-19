"""Tokenizer implementing the contract in spec.md."""

import re

# The four characters that are separated from surrounding text (rule 3).
# Used as a capturing split so each separator is kept as its own token.
_SEPARATOR_RE = re.compile(r"([.,!?])")


def tokenize(text):
    """Split ``text`` into lowercase tokens, per spec.md.

    1. every returned token is lowercase
    2. whitespace is split with ``str.split()``, i.e. any whitespace run
    3. ``.`` ``,`` ``!`` ``?`` are stripped out of words and emitted as tokens
       of their own (each mark separately)
    4. empty tokens are dropped
    5. numbers are never mangled: ``"42"`` -> ``["42"]``, and only the four
       separators above have any special meaning (``"x=1"`` -> ``["x=1"]``)
    """
    tokens = []
    for chunk in text.split():
        for piece in _SEPARATOR_RE.split(chunk):
            if piece:  # rule 4: drop the empty strings between separators
                tokens.append(piece.lower())
    return tokens
