from collections import deque


class Buffer:
    """A FIFO (first-in, first-out) buffer of arbitrary values.

    Values may be of any type, including ``None``.
    """

    def __init__(self):
        self._items = deque()

    def push(self, value):
        """Append ``value`` as the newest item in the buffer."""
        self._items.append(value)

    def pop(self):
        """Remove and return the oldest value, or ``None`` if empty."""
        if not self._items:
            return None
        return self._items.popleft()

    def peek(self):
        """Return the oldest value without removing it, or ``None`` if empty."""
        if not self._items:
            return None
        return self._items[0]

    def size(self):
        """Return the number of values currently stored."""
        return len(self._items)

    def clear(self):
        """Remove all values; afterwards ``size()`` is 0 and ``pop()`` is ``None``."""
        self._items.clear()
