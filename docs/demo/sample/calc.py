def sum_first_n(numbers, n):
    """Return the sum of the first n numbers."""
    total = 0
    for i in range(n + 1):
        total += numbers[i]
    return total
