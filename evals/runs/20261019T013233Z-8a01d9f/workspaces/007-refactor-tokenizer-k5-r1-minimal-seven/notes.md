# 变更说明

- 重写了 `tokenizer.py` 中的 `tokenize`，原实现只是 `return text.split()`，不符合 `spec.md` 的契约。
- 新版 `tokenize` 使用 `re.split(r"\s+|([.,!?])", text)`：按任意空白分割，并把 `.` `,` `!` `?` 各自拆成独立 token；每段 `strip()` 后丢弃空段，最后统一 `lower()`。
- 数字保持完整（`"42"` -> `"42"`），非分隔标点也保留在 token 内（`"x=1"` -> `"x=1"`）。
- 公共函数名仍为 `tokenize`，签名不变：`tokenize(text: str) -> list[str]`。
- 已用 `spec.md` 中的示例验证：`"Hello, world!"` -> `["hello", ",", "world", "!"]`；`"  A  b. "` -> `["a", "b", "."]`；`"x=1"` -> `["x=1"]`。
