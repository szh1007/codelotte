from collections import deque


class Buffer:
    """A FIFO queue that tolerates storing any value, including ``None``."""

    def __init__(self):
        self._items = deque()

    def push(self, value):
        """Append ``value`` (any value, including ``None``) to the buffer."""
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
        """Return the number of stored values."""
        return len(self._items)

    def clear(self):
        """Remove all values."""
        self._items.clear()
