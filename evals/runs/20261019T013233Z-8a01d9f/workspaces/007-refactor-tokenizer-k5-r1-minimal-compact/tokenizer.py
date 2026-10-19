import re

# 分隔符：只把 . , ! ? 从单词中切出来，其余字符（包括 = 和数字）保持完整。
_SPLIT_RE = re.compile(r"[.,!?]|[^\s.,!?]+")


def tokenize(text: str) -> list[str]:
    """按 spec.md 契约把文本切成小写 token 列表。

    - 按任意空白切分；
    - 每个 . , ! ? 独立成 token；
    - 丢弃空 token；
    - 数字及其他字符（如 "x=1"）保持完整。
    """
    return _SPLIT_RE.findall(text.lower())
