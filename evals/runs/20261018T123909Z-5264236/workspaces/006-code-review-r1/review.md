## Bug

```python
    for i in range(n + 1):
```

## Why

The loop runs one iteration too many: `range(n + 1)` yields `0 .. n`, i.e. `n + 1` indices, but only the first `n` elements should be summed.

- When `n = 0`, it still executes `total += values[0]`, so the sum of zero elements wrongly returns `values[0]` instead of `0` (and raises `IndexError` if `values` is empty).
- When `n = len(values)`, the final iteration reads `values[n]`, which is out of bounds, so it raises `IndexError: list index out of range`.

## Fix

```python
    for i in range(n):
```
