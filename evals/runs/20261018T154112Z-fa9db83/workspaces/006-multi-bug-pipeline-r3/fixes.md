formats.py | return f"${dollars}.{remainder}" | return f"${dollars}.{remainder:02d}"
inventory.py | return ordered[: n + 1] | return ordered[:n]
report.py | total = sum(qty for _, qty in top) | total = sum(qty for _, qty in items)
