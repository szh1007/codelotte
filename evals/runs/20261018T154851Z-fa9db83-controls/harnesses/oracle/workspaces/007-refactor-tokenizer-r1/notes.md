Changed `tokenize` from `text.split()` to a character scan: lowercase input,
split on whitespace, emit `.` `,` `!` `?` as separate tokens, and drop empty tokens.
The implementation follows `spec.md`.

Examples:
- `"Hello, world!"` -> `["hello", ",", "world", "!"]`
- `"  A  b. "` -> `["a", "b", "."]`
- `"x=1"` -> `["x=1"]`
