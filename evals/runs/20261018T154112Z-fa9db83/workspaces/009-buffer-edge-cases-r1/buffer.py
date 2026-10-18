"""A FIFO queue with a total (never-raising) interface.

See spec.md for the contract.
"""

from collections import deque


class Buffer:
    """FIFO queue.

    ``None`` is a legal stored value, so emptiness is tracked by the
    underlying container's length rather than by a sentinel value.
    """

    def __init__(self):
        self._items = deque()

    def push(self, value):
        """Append ``value`` (any object, including ``None``) to the buffer."""
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
        """Remove all stored values."""
        self._items.clear()
