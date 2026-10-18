from collections import deque


class Buffer:
    """FIFO queue.

    ``push`` appends any value (including ``None``); ``pop``/``peek`` return
    ``None`` when the buffer is empty instead of raising.
    """

    def __init__(self):
        self._items = deque()

    def push(self, value):
        self._items.append(value)

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
