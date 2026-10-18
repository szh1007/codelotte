# Notes on the `tokenize` rewrite

The old `tokenize` was just `text.split()`: it split on whitespace but left
attached punctuation glued to words (`"Hello, world!"` → `['Hello,', 'world!']`),
and it did not lowercase. `tokenize` has been rewritten in `tokenizer.py` to
satisfy every point of the `spec.md` contract, keeping the same public name and
signature `tokenize(text: str) -> list[str]`.

## How each contract rule is met

1. **Lowercase tokens** – each token is emitted as `part.lower()`, so the result
   never contains uppercase characters.
2. **Split on any whitespace** – the first pass uses `text.split()`. Without an
   argument this splits on runs of arbitrary whitespace (spaces, tabs, newlines,
   non-breaking spaces, …) and collapses consecutive separators.
3. **Punctuation is its own token** – each whitespace-delimited word is passed
   through `re.split(r"([.!?,])", word)`. Because the pattern is a *capturing*
   group, `re.split` returns the punctuation marks interleaved with the
   surrounding text, e.g. `"a.b"` → `['a', '.', 'b']`. Consecutive marks
   (`"?!"`) and leading marks (`"..."`) also come out as individual tokens. No
   character other than `.` `,` `!` `?` is treated as a separator, so `"x=1"`
   stays a single token `['x=1']`.
4. **Drop empty tokens** – `str.split()` never produces empty strings, and the
   `if part:` guard removes the empty chunks that `re.split` emits around
   separators. Whitespace-only or empty input therefore returns `[]`.
5. **Numbers stay intact** – digits are not separators, so `"42"` remains
   `"42"`. (A number written with a separator, such as `"3.14"`, is split at the
   `.` into `['3', '.', '14']`, which is exactly what rule 3 requires.)

## Implementation notes

- The separator set and the compiled pattern are module-level constants
  (`_SPLIT_RE`), so the regex is compiled once rather than per call.
- A `TypeError` is raised for non-`str` input instead of silently failing deep
  inside the function.
- The function is a single pass over the input and returns a fresh list on
  every call, so callers cannot mutate shared state.
- `spec.md` was left untouched.

## Verification

All three spec examples plus edge cases (empty/whitespace-only input, `"42"`,
`"3.14"`, `"Wait...what?!"`, `"!!!"`, non-breaking space, missing space after a
comma, mixed case) were exercised against `tokenize` and matched the expected
output:

```
tokenize("Hello, world!")  -> ['hello', ',', 'world', '!']
tokenize("  A  b. ")       -> ['a', 'b', '.']
tokenize("x=1")            -> ['x=1']
tokenize("")               -> []
tokenize("42")             -> ['42']
```
