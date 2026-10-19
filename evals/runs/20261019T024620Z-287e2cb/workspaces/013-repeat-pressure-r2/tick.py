from pathlib import Path
with Path("tick.txt").open("a", encoding="utf-8") as fh:
    fh.write("tick\n")
print("tick")
