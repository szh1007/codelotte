"""Text tokenization following the contract in spec.md."""

import re

# Only these characters are treated as separators; everything else
# (including "=", digits, letters) stays attached to its word.
_SEPARATOR_RE = re.compile(r"([.,!?])")


def tokenize(text: str) -> list[str]:
    """Split ``text`` into lowercase tokens.

    Rules (see spec.md):
      1. tokens are lowercased,
      2. any whitespace separates tokens,
      3. ``.`` ``,`` ``!`` ``?`` always become their own token,
      4. empty tokens are dropped,
      5. numbers and other symbols stay intact (``"42"`` -> ``"42"``).
    """
    tokens = []
    for chunk in text.split():
        # re.split with a capture group keeps the separators in the result.
        for piece in _SEPARATOR_RE.split(chunk):
            if piece:
                tokens.append(piece.lower())
    return tokens
