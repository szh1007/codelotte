# Tokenizer changes

Rewrote `tokenize` in `tokenizer.py` to match the contract. It now lowercases the input, splits on arbitrary whitespace, emits each `.`, `,`, `!`, and `?` as a separate token, preserves all other characters (including digits and other punctuation), and drops empty tokens. The implementation uses `re.findall` with a pattern for either a non-separator character run or one of the specified punctuation marks.
