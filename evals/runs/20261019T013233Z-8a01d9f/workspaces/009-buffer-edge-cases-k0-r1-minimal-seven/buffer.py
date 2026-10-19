class Buffer:
    """A FIFO queue.

    Any value may be stored, including ``None``. Every read operation is safe
    on an empty buffer: ``pop()`` and ``peek()`` return ``None`` instead of
    raising.
    """

    def __init__(self):
        self._items = []

    def push(self, value):
        """Append ``value`` to the buffer. ``None`` is a valid value."""
        self._items.append(value)

    def pop(self):
        """Remove and return the oldest value, or ``None`` if empty."""
        if not self._items:
            return None
        return self._items.pop(0)

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
