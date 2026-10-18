# Buffer contract

`Buffer` is a FIFO queue:

- `push(value)` appends any value, including `None`.
- `pop()` removes and returns the oldest value. On an empty buffer it returns `None`
  and does not raise.
- `peek()` returns the oldest value without removing it. On an empty buffer it returns
  `None`.
- `size()` returns the number of stored values.
- `clear()` removes all values; afterwards `size()` is 0 and `pop()` returns `None`.
