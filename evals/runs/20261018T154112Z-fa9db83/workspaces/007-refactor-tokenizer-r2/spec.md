# Tokenizer contract

`tokenize(text: str) -> list[str]` must:

1. Return lowercase tokens.
2. Split on any whitespace.
3. Separate the punctuation characters `.` `,` `!` `?` from words; each punctuation
   mark is its own token.
4. Drop empty tokens.
5. Keep numbers intact (for example `"42"` stays `"42"`).

Examples:

- `"Hello, world!"` -> `["hello", ",", "world", "!"]`
- `"  A  b. "` -> `["a", "b", "."]`
- `"x=1"` -> `["x=1"]` (only `.` `,` `!` `?` are separators)
