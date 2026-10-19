"""Word/punctuation tokenizer.

Public API: tokenize(text) -> list[str]
The behaviour is specified in spec.md.
"""

import re

# The only characters treated as separators (spec rule 3).
PUNCTUATION = ".,!?"

# Split while *keeping* the delimiters, so each mark becomes its own token.
_SPLIT_RE = re.compile("([" + re.escape(PUNCTUATION) + "])")


def tokenize(text: str) -> list[str]:
    """Split ``text`` into lowercase tokens.

    - output is lowercased
    - whitespace is always a separator
    - each of ``. , ! ?`` is emitted as its own token
    - empty tokens are dropped
    - numbers and other characters (e.g. ``=``) are left intact
    """
    tokens: list[str] = []

    # re.split with a capturing group yields the text pieces interleaved
    # with the punctuation marks themselves.
    for chunk in _SPLIT_RE.split(text.lower()):
        # Whitespace splitting happens per chunk; punctuation chunks have no
        # whitespace, so they survive whole. Any empty piece is dropped here.
        tokens.extend(part for part in chunk.split() if part)

    return tokens
