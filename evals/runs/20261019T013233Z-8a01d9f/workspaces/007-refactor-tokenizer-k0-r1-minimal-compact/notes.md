# Tokenizer rewrite notes

`tokenizer.py` previously contained a one-line implementation, `return text.split()`,
which only satisfied rules 1 (partially — it did not lowercase) and 2 of `spec.md`.
It never lowercased, never separated `.` `,` `!` `?`, and so failed the spec examples
(`"Hello, world!"` returned `["Hello,", "world!"]`).

## What changed in `tokenize`

`tokenize` keeps its name and signature (`tokenize(text: str) -> list[str]`) and is now
built in two stages that map directly onto the contract:

1. **Whitespace split (rule 2):** `text.split()` breaks the input on any run of
   whitespace, including tabs and newlines, and already discards the empty strings
   that leading/trailing/doubled whitespace would otherwise produce.
2. **Punctuation split (rule 3):** each whitespace chunk is passed through
   `re.split(r"([.,!?])", chunk)`. Because the character class is a *capturing*
   group, the separators themselves are kept in the output, so every `.` `,` `!` `?`
   becomes its own token. Note that `re.split` is used on a fixed character class
   rather than on `\W`/`[^\w\s]`, so characters such as `=`, `:`, `;`, `-` stay inside
   the token — that is what keeps `"x=1"` as a single token.
3. **Lowercasing (rule 1):** `piece.lower()` is applied to every surviving token.
4. **Dropping empties (rule 4):** `re.split` returns `""` between adjacent
   punctuation marks and at the edges of a chunk; the `if piece:` guard removes them,
   so `"a!"` yields `["a", "!"]` and not `["a", "!", ""]`.

Rule 5 (numbers stay intact) needs no special casing: digits are not separators, so
`"42"` is a single chunk with no punctuation in it and survives verbatim. Only the four
listed characters split, so `"3.14"` becomes `["3", ".", "14"]` — the literal reading
of rule 3 — while a bare `"42"` stays `"42"`.

The separator set lives in the module-level constant `PUNCTUATION`, and the compiled
pattern `_SPLIT_RE` is built once at import time instead of being recompiled per call.

## Verification

All three examples in `spec.md` pass, along with edge cases: empty/whitespace-only
input returning `[]`, runs of punctuation (`"Wait... what?!"`), mixed case, embedded
newlines, and tokens containing other non-alphanumeric characters (`"x:y;z"`).

`spec.md` was not modified.
