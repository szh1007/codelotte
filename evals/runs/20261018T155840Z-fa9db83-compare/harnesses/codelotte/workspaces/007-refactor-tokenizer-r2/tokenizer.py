"""Word tokenizer implementing the contract in ``spec.md``."""

from __future__ import annotations

import re

# The only characters treated as separators, each becoming its own token.
# Capturing the group makes re.split() keep the separators in the output.
_SEPARATORS = ".!?"
_SPLIT_RE = re.compile(r"([.!?,])")


def tokenize(text: str) -> list[str]:
    """Split ``text`` into lowercase tokens.

    Contract (see ``spec.md``):
      1. tokens are lowercase;
      2. splitting happens on any whitespace;
      3. ``.`` ``,`` ``!`` ``?`` are separated from words and each becomes its
         own token (no other character is a separator);
      4. empty tokens are dropped;
      5. numbers stay intact because digits are never separators.

    Examples:
        >>> tokenize("Hello, world!")
        ['hello', ',', 'world', '!']
        >>> tokenize("  A  b. ")
        ['a', 'b', '.']
        >>> tokenize("x=1")
        ['x=1']
    """
    if not isinstance(text, str):
        raise TypeError(f"tokenize() expects str, got {type(text).__name__}")

    tokens: list[str] = []
    # str.split() with no arguments splits on runs of any whitespace and never
    # yields empty strings, which covers contract points 2 and 4.
    for word in text.split():
        # re.split with a capturing group yields [chunk, sep, chunk, ...], so
        # every empty chunk is filtered out and separators stay as tokens.
        for part in _SPLIT_RE.split(word):
            if part:
                tokens.append(part.lower())
    return tokens
