import re

# Matches either a whitespace run, or one of the separator punctuation marks.
# The punctuation is captured so that re.split keeps it in the output.
_SPLIT_RE = re.compile(r"\s+|([.,!?])")


def tokenize(text):
    """Split text into lowercase tokens.

    Whitespace separates tokens, and each of the punctuation marks
    ".", ",", "!", "?" becomes its own token. Empty tokens are dropped.
    Digits and any other characters (e.g. "=") stay part of their token.
    """
    tokens = []
    for part in _SPLIT_RE.split(text):
        if part is None:
            continue
        part = part.strip()
        if not part:
            continue
        tokens.append(part.lower())
    return tokens
