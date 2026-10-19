from formats import money
from inventory import top_n


def build_report(items, n):
    top = top_n(items, n)
    total = sum(qty for _, qty in items)
    lines = [f"total={money(total)}"]
    for name, qty in top:
        lines.append(f"{name}:{money(qty)}")
    return "\n".join(lines)
