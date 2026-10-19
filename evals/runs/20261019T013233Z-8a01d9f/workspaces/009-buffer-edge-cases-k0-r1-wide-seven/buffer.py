class Buffer:
    def __init__(self):
        self._items = []

    def push(self, value):
        self._items.append(value)

    def pop(self):
        if not self._items:
            return None
        return self._items.pop(0)

    def peek(self):
        if not self._items:
            return None
        return self._items[0]

    def size(self):
        return len(self._items)

    def clear(self):
        self._items.clear()
