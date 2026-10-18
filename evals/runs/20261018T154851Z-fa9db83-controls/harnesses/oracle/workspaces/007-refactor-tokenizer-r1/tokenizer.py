_PUNCTUATION = ".,!?"


def tokenize(text):
    tokens = []
    current = []
    for char in text.lower():
        if char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        elif char in _PUNCTUATION:
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(char)
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens
