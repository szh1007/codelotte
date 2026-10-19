# Notes: rewriting `tokenize`

## Starting point

`tokenizer.py` originally contained a one-liner:

```python
def tokenize(text):
    return text.split()
```

It satisfied only rule 2 of `spec.md` (whitespace splitting). Because it never
lowercased the input and never separated punctuation, it failed rules 1 and 3.
The examples also failed: `"Hello, world!"` produced `["Hello,", "world!"]`
instead of `["hello", ",", "world", "!"]`.

## What changed in `tokenize`

`tokenize` now works in two passes:

1. **Lowercase** the whole input once with `text.lower()`, which handles rule 1.
2. **Split on separators** with `re.split` using a capturing group around the
   punctuation class. Because the group is capturing, the `.` `,` `!` `?`
   characters are kept in the result, so each one becomes a token of its own
   (rule 3). The pieces between them are then split on whitespace (rule 2).

Two smaller details make the contract hold exactly:

- **Empty tokens are dropped (rule 4).** `re.split` and `str.split()` both leave
  empty strings around adjacent/leading/trailing punctuation such as `",,"` or
  `"  a  "`. `tokenize` filters them out with `if part`, so `""` and
  `"   \t\n "` both return `[]`.
- **Only the four listed marks separate (rules 3 and 5).** The regex contains
  just `.,!?`, so `=` is not a separator and numbers are never truncated:
  `"x=1"` stays `["x=1"]` and `"42"` stays `["42"]`. `"3.14"` becomes
  `["3", ".", "14"]`, which is the literal reading of the rule that `.` is a
  separator in its own right.

The signature, the public function name `tokenize`, and its return type
(`list[str]`) are unchanged, so existing callers keep working.

## Verification

Checked against all three spec examples plus edge cases: mixed whitespace
(via `str.split()`, which covers tabs, newlines and non-breaking spaces),
adjacent digits/punctuation (`"a?!b"`, `"a,,b"`, `"..."`), empty input, and
non-separator characters (`"a-b_c"`, `"x=1"`). All 14 cases pass, along with
invariants that every token is lowercase, non-empty, and whitespace-free.
`spec.md` was not modified.
