import re

# Keywords: lowercase tokens, whitespace splitting, `.` `,` `!` `?` as their own
# tokens, no empty tokens, numbers kept intact (see spec.md).
_TOKEN_RE = re.compile(r"[^\s.,!?]+|[.,!?]")


def tokenize(text):
    """Split text into lowercase tokens following the contract in spec.md."""
    return _TOKEN_RE.findall(text.lower())
