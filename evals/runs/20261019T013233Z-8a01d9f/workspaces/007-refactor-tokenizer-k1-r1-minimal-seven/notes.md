# Notes

## What changed

- Rewrote `tokenize` in `tokenizer.py` to match the contract in `spec.md`
  exactly (the previous version was just `text.split()`).
- `tokenize` now lowercases the input, splits on any whitespace, treats each
  of `.` `,` `!` `?` as its own token, drops empty tokens, and leaves all
  other characters untouched so numbers stay intact (`"42"` -> `["42"]`,
  `"x=1"` -> `["x=1"]`).
- Implementation detail: a single compiled regex
  `[.,!?]|[^.,!?\s]+` is applied to each whitespace-separated chunk, which
  handles splitting and punctuation separation in one pass.
- The public function name and signature stayed as `tokenize(text: str) ->
  list[str]`, so existing callers are unaffected.
- Verified against the spec's three examples plus extra cases (numbers, empty
  input, lone punctuation, mixed whitespace) — all pass.
