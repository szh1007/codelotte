import re

# A token is either a single punctuation separator or a run of non-whitespace,
# non-separator characters. Whitespace never matches, so empty tokens cannot
# appear; numbers stay intact because digits are ordinary word characters here.
_TOKEN_RE = re.compile(r"[.,!?]|[^\s.,!?]+")


def tokenize(text):
    """Split ``text`` into lowercase tokens per the contract in spec.md."""
    return [token.lower() for token in _TOKEN_RE.findall(text)]
