# Notes

- Rewrote `tokenize` in `tokenizer.py` to match `spec.md`.
- `tokenize` now lowercases the text and extracts tokens with the regular
  expression `[^\s.,!?]+|[.,!?]`, so it splits on any whitespace, emits each of
  `.` `,` `!` `?` as its own token, never produces empty tokens, and keeps
  numbers (and other non-separator characters such as `x=1`) intact.
- The public function name `tokenize` and its single `text` parameter are
  unchanged, and `spec.md` was not modified.
