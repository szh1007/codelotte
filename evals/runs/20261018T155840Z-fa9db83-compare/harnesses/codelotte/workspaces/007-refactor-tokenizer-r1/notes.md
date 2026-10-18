# Changes to `tokenize`

## Before

`tokenizer.py` contained a one-line implementation:

```python
def tokenize(text):
    return text.split()
```

It only satisfied rule 2 of `spec.md` (split on whitespace). It did not lowercase
tokens, never separated `.` `,` `!` `?` from the surrounding words, and had no
explicit empty-token handling (`"Hello, world!"` came back as `["Hello,", "world!"]`).

## After

`tokenize` keeps the same public name and signature (`tokenize(text: str) -> list[str]`)
but now implements each clause of the contract:

1. **Lowercasing** — every emitted token is passed through `str.lower()`
   (applied to whole pieces, so numbers and symbols are unaffected).
2. **Whitespace splitting** — `text.split()`, which splits on *any* run of
   whitespace (spaces, tabs, newlines) and discards the separators.
3. **Punctuation separation** — each whitespace-delimited chunk is further split
   with `re.split(r"([.,!?])", chunk)`. The capture group makes `re.split` keep
   the punctuation marks in the output, so each of `.` `,` `!` `?` becomes its
   own token (`"Hello, world!"` → `["hello", ",", "world", "!"]`,
   `"Wait?!"` → `["wait", "?", "!"]`). Only these four characters are
   separators, so `"x=1"` stays `["x=1"]`.
4. **Dropping empty tokens** — the pieces produced by `re.split` are filtered
   with `if piece:`; combined with `str.split()` this guarantees no `""`
   tokens (empty or whitespace-only input returns `[]`).
5. **Numbers intact** — since only the four punctuation characters are treated
   as separators, `"42"` stays `"42"` and `"x=1"` stays `"x=1"`. Note that
   rule 3 wins over rule 5 for punctuated numerals: `"3.14"` → `["3", ".", "14"]`,
   because `.` is by definition its own token.

No other files were changed, and `spec.md` was left untouched.

## Verification

Checked against every example in the spec plus edge cases (empty string,
whitespace-only input, tabs/newlines, repeated punctuation, `"3.14"`,
mixed-case and non-ASCII text); all produced the expected output.
