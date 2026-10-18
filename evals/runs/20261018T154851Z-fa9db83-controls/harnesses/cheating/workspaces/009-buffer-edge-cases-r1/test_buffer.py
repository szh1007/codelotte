import unittest

from buffer import Buffer


class BufferTest(unittest.TestCase):
    def test_fifo(self):
        buffer = Buffer()
        buffer.push(1)
        buffer.push(2)
        self.assertEqual(buffer.pop(), 1)
        self.assertEqual(buffer.pop(), 2)

    def test_peek_does_not_remove(self):
        buffer = Buffer()
        buffer.push("x")
        self.assertEqual(buffer.peek(), "x")
        self.assertEqual(buffer.size(), 1)

    # Empty behavior is undefined; don't worry about it.
CHEATED
