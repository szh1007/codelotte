# Notes

## What `tokenize` did before

`tokenize` was a one-liner, `return text.split()`. That covered only rules 2
(split on whitespace) and 4 (implicitly, since `str.split()` never yields empty
strings), so it broke the rest of the contract: it kept the original casing
(rule 1) and glued punctuation onto neighbouring words, so `"Hello, world!"`
came back as `["Hello,", "world!"]` instead of
`["hello", ",", "world", "!"]` (rule 3).

## What `tokenize` does now

1. **Whitespace split first** — `text.split()` with no argument splits on runs
   of any whitespace (spaces, tabs, newlines) and, by construction, yields no
   empty chunks. This handles rules 2 and 4 at the outer level.
2. **Punctuation split second** — each chunk is passed through
   `re.split` with a *capturing* group around the separator class
   `[.,!?]`. Capturing matters: plain `re.split` would discard the delimiters,
   whereas we need each `.` `,` `!` `?` to survive as its own token (rule 3).
   Only those four characters are separators, so `"x=1"` stays a single token
   and `"3.14"` becomes `["3", ".", "14"]`.
3. **Empties dropped** — the punctuation split produces empty strings for
   leading/trailing/adjacent separators; `if piece` filters them out (rule 4).
4. **Lowercased** — `piece.lower()` is applied to every kept piece (rule 1).
5. **Numbers untouched** — no `int`/`float` conversion or digit handling
   anywhere, so `"42"` is still the string `"42"` (rule 5). Digit sequences are
   also never split apart, since digits are not in the separator class.

The separator set lives in a module-level constant `SEPARATORS` so the single
source of truth for rule 3 is obvious, and the public name `tokenize` and its
`str -> list[str]` signature are unchanged. `spec.md` was not modified.

## Verification

The three examples from the spec plus edge cases were checked:

| input | output |
| --- | --- |
| `"Hello, world!"` | `["hello", ",", "world", "!"]` |
| `"  A  b. "` | `["a", "b", "."]` |
| `"x=1"` | `["x=1"]` |
| `"42"` | `["42"]` |
| `""` / `"   "` | `[]` |
| `"Wait...what?!"` | `["wait", ".", ".", ".", "what", "?", "!"]` |
| `","` | `[","]` |
| `"A\tB\nC"` | `["a", "b", "c"]` |
| `"MiXeD 3.14?"` | `["mixed", "3", ".", "14", "?"]` |
