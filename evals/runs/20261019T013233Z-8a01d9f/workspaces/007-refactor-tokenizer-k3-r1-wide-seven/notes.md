# Notes

- Rewrote `tokenize` in `tokenizer.py` to follow `spec.md`: it now matches tokens with a
  single regex (`[.,!?]` for punctuation, `[^\s.,!?]+` for word runs), so punctuation is
  split off as its own token, whitespace of any kind separates tokens, and empty tokens can
  never be produced.
- Tokens are lowercased via `str.lower()` on each match, and numbers such as `"42"` stay
  intact since only whitespace and `. , ! ?` act as separators (e.g. `"x=1"` -> `["x=1"]`).
- Kept the public name and signature `tokenize(text: str) -> list[str]`; `spec.md` was left
  unchanged.
- Verified against the spec examples plus edge cases (empty string, whitespace-only input,
  punctuation-only input, tabs/newlines, repeated punctuation): all pass.
