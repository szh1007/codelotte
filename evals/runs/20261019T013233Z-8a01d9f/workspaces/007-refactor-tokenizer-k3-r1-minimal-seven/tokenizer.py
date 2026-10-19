"""Text tokenizer implementing the contract described in spec.md."""

import re

# Either a maximal run of characters that are neither whitespace nor one of the
# punctuation separators (numbers included, e.g. "42" or "x=1"), or a single
# punctuation character which becomes a token of its own.
_TOKEN_PATTERN = re.compile(r"[^\s.,!?]+|[.,!?]")


def tokenize(text: str) -> list[str]:
    """Split ``text`` into lowercase tokens.

    Rules (see spec.md):
      1. tokens are lowercased;
      2. whitespace always separates tokens;
      3. ``.`` ``,`` ``!`` ``?`` are split off as their own tokens;
      4. empty tokens are dropped;
      5. numbers stay intact.
    """
    return [match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text)]
