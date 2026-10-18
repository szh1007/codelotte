"""Tokenizer implementing the contract in spec.md.

Rules applied (in order of the contract):
  1. tokens are lowercased
  2. tokens are split on any whitespace
  3. `.` `,` `!` `?` are separators and each one becomes its own token
  4. empty tokens are dropped
  5. digits are never stripped or split, so numbers such as "42" stay intact
"""

import re

# Rule 3: these four characters -- and only these -- are punctuation separators.
# Everything else (digits, letters, "=", "-", ...) stays inside its token.
PUNCTUATION = ".,!?"

# Split on whitespace *or* on a punctuation mark, capturing the mark so that it
# survives as its own piece instead of being discarded by re.split().
_SPLIT_RE = re.compile(r"([%s])|\s+" % re.escape(PUNCTUATION))


def tokenize(text: str) -> list[str]:
    """Split ``text`` into lowercase tokens as described in ``spec.md``.

    Example:
        >>> tokenize("Hello, world!")
        ['hello', ',', 'world', '!']
    """
    if not isinstance(text, str):
        raise TypeError(f"tokenize() expects str, got {type(text).__name__}")

    tokens = []
    for piece in _SPLIT_RE.split(text):
        # re.split() with a capturing group yields None for the non-capturing
        # alternative (\s+), and "" at the boundaries; both are dropped by rule 4.
        if piece:
            tokens.append(piece.lower())
    return tokens
