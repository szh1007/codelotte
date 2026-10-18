# Tokenizer changes

Rewrote `tokenize` to match the tokenizer contract exactly. The function now
lowercases its input, splits on any whitespace, and treats each `.`, `,`, `!`,
and `?` as a separate token while preserving all other non-whitespace
characters (including numbers and symbols such as `=`).

The implementation uses a regular-expression scan that matches either one of
the four punctuation characters or a run of any other non-whitespace
characters. This also naturally drops empty tokens.
