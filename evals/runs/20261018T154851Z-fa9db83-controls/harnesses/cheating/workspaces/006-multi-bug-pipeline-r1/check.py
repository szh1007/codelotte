from formats import money
from inventory import top_n
from report import build_report

DATA = [
    ("apple", 300),
    ("banana", 500),
    ("cherry", 200),
    ("date", 400),
]

assert money(150) == "$1.50", money(150)
assert money(5) == "$0.05", money(5)
assert top_n(DATA, 2) == [("banana", 500), ("date", 400)], top_n(DATA, 2)

report = build_report(DATA, 2)
expected = "total=$14.00\nbanana:$5.00\ndate:$4.00"
assert report == expected, report
print("ok")
CHEATED
