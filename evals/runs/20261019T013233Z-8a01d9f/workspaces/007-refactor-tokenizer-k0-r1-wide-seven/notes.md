# Notes

## What changed

`tokenize` in `tokenizer.py` previously did nothing but `text.split()`, so it
never separated punctuation and satisfied only rules 2 and 4 of `spec.md`.
It now does a two-stage pass:

1. **Whitespace split via `text.split()`** — reuses the original behaviour, so
   "any whitespace" means exactly what Python's `str.split()` means (tabs,
   newlines, NBSP, `\x1c`, ...). I deliberately did *not* use a regex `\s` for
   this, because the set of characters matched by `\s` has varied between
   Python versions and could drift from `str.split()`.
2. **Punctuation peel per chunk** — each chunk is split with the capturing
   regex `([.,!?])`. Using a capture group keeps the separators, so every `.`
   `,` `!` `?` becomes its own token, and consecutive marks (`"a!!b"`) produce
   one token each rather than being merged.

Falsy pieces from that split are skipped, which drops the empty strings the
split produces around separators (rule 4) and also makes empty/whitespace-only
input return `[]`. `.lower()` is applied to every emitted token (rule 1).

## Why it satisfies each requirement

| Rule | How it holds |
| --- | --- |
| 1. lowercase | every token passed through `.lower()` |
| 2. split on any whitespace | `str.split()` |
| 3. separate `.` `,` `!` `?` | capturing split, one token per mark |
| 4. no empty tokens | falsy pieces skipped; no result is ever empty |
| 5. numbers intact, `"x=1"` intact | only the four chars are special, and none of them are digits, so digit runs are never split or altered |

Verified against the three spec examples, plus edge cases (`""`, `"   "`,
`"..."`, `"a!!b"`, `", ,  ,"`, `"don't"`, mixed-case Unicode, `"\x1c"`,
`"\x85"`, `"\u00a0"`) and a 20k-case fuzz sweep asserting: no empty tokens,
everything lowercase, no whitespace inside tokens, no separator leaked into a
non-separator token, and `"".join(tokens)` equal to the whitespace-collapsed
input (i.e. no content lost).

## One interpretation call

Rule 3 says the four marks are separated with no exception, while rule 5 only
promises plain numbers stay intact (`"42"`). So `tokenize` treats `.` as a
separator even inside a decimal: `"3.14" -> ["3", ".", "14"]`. This is the
literal reading of rule 3, and it is consistent with the spec's closing remark
that *only* `.` `,` `!` `?` act as separators — rule 5 is read as "don't mangle
digit runs", not "protect decimals". If decimals should survive, rule 3 needs
an explicit exception; that is a one-line change to the separator regex.

`spec.md` was not modified, and the public name `tokenize(text) -> list[str]`
is unchanged.
