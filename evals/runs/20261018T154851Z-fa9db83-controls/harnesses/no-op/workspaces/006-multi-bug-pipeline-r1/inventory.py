def top_n(items, n):
    """Return the n highest (name, qty) pairs, descending by qty."""
    ordered = sorted(items, key=lambda item: item[1], reverse=True)
    return ordered[: n + 1]
