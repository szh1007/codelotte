import re

# Only these characters are separators; everything else (e.g. "=") stays in the token.
_PUNCT_SPLIT = re.compile(r"([.,!?])")


def tokenize(text):
    tokens = []
    for chunk in text.lower().split():
        for part in _PUNCT_SPLIT.split(chunk):
            if part:
                tokens.append(part)
    return tokens
