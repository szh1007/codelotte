from collections import deque


class Buffer:
    """A FIFO queue.

    Per the contract in spec.md:

    - ``push(value)`` appends any value, including ``None``.
    - ``pop()`` removes and returns the oldest value, or ``None`` when empty
      (it never raises).
    - ``peek()`` returns the oldest value without removing it, or ``None``
      when empty.
    - ``size()`` returns the number of stored values.
    - ``clear()`` removes all values.
    """

    def __init__(self):
        self._items = deque()

    def push(self, value):
        self._items.append(value)
        return None

    def pop(self):
        if not self._items:
            return None
        return self._items.popleft()

    def peek(self):
        if not self._items:
            return None
        return self._items[0]

    def size(self):
        return len(self._items)

    def clear(self):
        self._items.clear()
        return None
