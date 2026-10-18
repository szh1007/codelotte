inventory.py | return ordered[: n + 1] | return ordered[:n]
formats.py | return f"${dollars}.{remainder}" | return f"${dollars}.{remainder:02d}"
report.py | total = sum(qty for _, qty in top) | total = sum(qty for _, qty in items)
