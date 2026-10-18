## Bug

```python
    for i in range(n + 1):
```

## Why

The loop runs `n + 1` times (indices `0..n`) instead of `n` times (`0..n-1`).

- When `n = 0`: `range(1)` yields `i = 0`, so `values[0]` is added and the function returns `values[0]` instead of the sum of zero elements, which should be `0`.
- When `n = len(values)`: the last iteration uses `i = len(values)`, which is one past the final valid index, raising `IndexError: list index out of range`.

## Fix

```python
    for i in range(n):
```
