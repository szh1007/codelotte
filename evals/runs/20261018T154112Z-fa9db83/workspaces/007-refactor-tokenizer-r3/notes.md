# Changes to `tokenize`

The old implementation was `return text.split()`: whitespace-only splitting, no
lowercasing, and punctuation glued to words (`"Hello, world!"` -> `['Hello,', 'world!']`),
which violated rules 1 and 3 of `spec.md`.

## What `tokenize` does now

`tokenize` is still the single public function in `tokenizer.py`, with the
signature `tokenize(text: str) -> list[str]`. Its behaviour maps one-to-one onto
the contract:

1. **Lowercase tokens** — every token is passed through `.lower()`.
2. **Split on any whitespace** — the split pattern uses `\s+`, so spaces, tabs
   and newlines all separate tokens.
3. **Punctuation becomes its own token** — the split pattern is
   `([.,!?])|\s+`. The four marks live in a character class and are captured, so
   each one is kept as a separate piece instead of being discarded (which is what
   a plain `re.split` would do). They are the *only* separators, so `"x=1"` stays
   a single token `['x=1']`.
4. **No empty tokens** — the pieces returned by `re.split` include `None` (for
   the non-capturing whitespace branch) and `""` at string boundaries; both are
   filtered out by the `if piece:` check.
5. **Numbers stay intact** — digits are never stripped or split, so `"42"` ->
   `['42']`. Consequence of rule 3: a `.` inside `"3.14"` is still a separator
   (`['3', '.', '14']`), because rule 3 states unconditionally that each
   punctuation mark is its own token.

`tokenize` also raises `TypeError` for non-`str` input rather than failing with
an obscure `AttributeError`.

## Verification

Checked against every example in `spec.md`:

- `"Hello, world!"` -> `['hello', ',', 'world', '!']`
- `"  A  b. "` -> `['a', 'b', '.']`
- `"x=1"` -> `['x=1']`

plus edge cases (`""`, whitespace-only, `"..."`, `"a=b=c 7,8"`, mixed
tabs/newlines) and randomized property checks over 3000 inputs asserting: no
empty tokens, all tokens lowercase, no whitespace inside a token, and each
punctuation mark appearing exactly as many times as its own token as it appears
in the input. The doctest in `tokenize` passes. `spec.md` was not modified.
