"""Tokenizer implementing the contract in spec.md."""

import re

# Only these four characters act as separators (spec rule 3).
PUNCTUATION = ".!?,"

# Split while keeping the punctuation marks as their own fields.
_SPLIT_RE = re.compile(r"([.!?,])")


def tokenize(text: str) -> list[str]:
    """Split `text` into lowercase word and punctuation tokens.

    Contract (see spec.md):
      1. Tokens are lowercase.
      2. Any whitespace separates tokens.
      3. `.` `,` `!` `?` are split off words and become their own tokens.
      4. Empty tokens are dropped.
      5. Numbers are left intact ("42" -> "42").
    """
    tokens: list[str] = []
    # Rule 2: str.split() with no argument splits on runs of any whitespace.
    for chunk in text.split():
        # Rule 3: split each whitespace-delimited chunk around punctuation.
        for part in _SPLIT_RE.split(chunk):
            # Rule 1: lowercase each resulting piece.
            part = part.lower()
            # Rule 4: skip the empty strings produced by adjacent punctuation
            # or by punctuation at the edges of a chunk.
            if part:
                tokens.append(part)
    return tokens
