# Notes on the `tokenize` rewrite

## What was wrong before

The previous implementation was a one-liner:

```python
def tokenize(text):
    return text.split()
```

`str.split()` alone only satisfies rule 2 of `spec.md`. It failed:

- **Rule 1 (lowercase):** `"Hello"` came back as `"Hello"`.
- **Rule 3 (punctuation):** punctuation stayed glued to words — `"Hello, world!"`
  produced `["Hello,", "world!"]` instead of `["hello", ",", "world", "!"]`.

## How the new `tokenize` works

Two splitting stages, mirroring the two ways the contract wants text separated:

1. `text.split()` first divides the input on runs of whitespace (rule 2).
   Because it uses no argument, it treats *any* whitespace as a separator —
   spaces, tabs, newlines, non-breaking spaces — and silently discards the
   surrounding empty fields.
2. Inside each remaining chunk, `re.split(r"([.!?,])", chunk)` splits around the
   four punctuation characters. The capture group makes `re.split` keep the
   delimiters in the output, so each `.` `,` `!` `?` becomes its own token
   (rule 3).
3. Each resulting piece is lowercased (rule 1), and empty pieces are skipped
   (rule 4). Empty pieces are common: they appear before/after punctuation at
   the edges of a chunk (`",leading"` → `["", ",", "leading"]`) and between
   adjacent marks (`"a!!"` → `["a", "!", "", "!"]`).

Rule 5 — numbers stay intact — is satisfied by construction: the only
characters that ever act as separators are the four punctuation marks, so
digits are never split apart. `"42"` returns `["42"]`. Note that this means
`"3.14"` returns `["3", ".", "14"]`, since `.` is explicitly a separator under
rule 3; the "keep numbers intact" rule is not an exception to that.

## Verification

The three examples from `spec.md` all match:

| input | output |
| --- | --- |
| `"Hello, world!"` | `["hello", ",", "world", "!"]` |
| `"  A  b. "` | `["a", "b", "."]` |
| `"x=1"` | `["x=1"]` |

Edge cases checked as well: empty string and whitespace-only input return `[]`;
`"Wait... what?!"` yields repeated punctuation tokens and no empty tokens;
`"Hello,World"` splits on the comma with no space needed; mixed tabs, newlines
and non-breaking spaces all split correctly; the public name `tokenize` and its
`str -> list[str]` signature are unchanged, and `spec.md` was not modified.
