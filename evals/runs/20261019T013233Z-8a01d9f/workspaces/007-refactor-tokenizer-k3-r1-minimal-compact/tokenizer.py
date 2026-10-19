import re

# 每个 `.` `,` `!` `?` 单独成为一个 token；其余按空白切分。
_PATTERN = re.compile(r"[.,!?]|[^\s.,!?]+")


def tokenize(text):
    """把文本切成小写 token，标点 `.` `,` `!` `?` 各自单独成 token。"""
    return _PATTERN.findall(text.lower())
