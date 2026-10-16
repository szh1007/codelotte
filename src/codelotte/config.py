"""用户级配置文件读取（SPEC §M）：settings.json 是运行设置的唯一来源。

配置级联：命令行参数（如 `-r`）> `~/.codelotte/settings.json`。**没有任何内置默认**——
默认 provider/模型、超时缺了就直接报错并指出该去哪个文件的哪个字段补，不替用户猜。
模型参数（端点/密钥/模型清单）在 `~/.codelotte/models.json`（models.py）；
计费事实（价目/峰谷/节假日）在随包目录 src/codelotte/providers/models.json（cost.py）。

没有任何配置会从项目目录或进程环境加载（.env 文件层、settings 的 env 包层、CODELOTTE_*
环境变量均已移除，2026-10-17）；用户级目录固定为系统用户根目录下的 `.codelotte/`。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from codelotte.changelog import should_record

USER_CONFIG_DIR = ".codelotte"
SETTINGS_FILE_NAME = "settings.json"
COMMAND_TIMEOUT_MAX = 600  # 秒，与 tools/bash.py 的 MAX_TIMEOUT 对齐（有测试守卫）


class ConfigError(Exception):
    """配置缺失或无效。"""


@dataclass
class Settings:
    """~/.codelotte/settings.json 的内容（文件键与字段一一对应，直接读取）。

    权限规则在 permissions.json；模型参数在 models.json；计费规则随包（都不在这里）。
    notices 不是文件字段：加载时收集的提示（未知键等），由入口打印。
    """

    last_changelog_version: str | None = None
    default_provider: str | None = None
    default_model: str | None = None
    command_timeout: int | None = None
    notices: list[str] = field(default_factory=list)


_KNOWN_SETTINGS = {
    "lastChangelogVersion": str,
    "defaultProvider": str,
    "defaultModel": str,
    "commandTimeoutSeconds": int,
}


def _settings_path(home: Path | None) -> Path:
    home_dir = home if home is not None else Path.home()
    return home_dir / USER_CONFIG_DIR / SETTINGS_FILE_NAME


def load_settings(home: Path | None = None) -> Settings:
    """读用户级 settings.json：缺失 = 全空（缺什么由取值方报错指路）。

    坏文件/坏类型直接报错（配置错误要响）；未知键忽略并记入 notices（不静默吞）。
    """
    path = _settings_path(home)
    if not path.is_file():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        raise ConfigError(f"设置文件读不动或不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"设置文件顶层应是 JSON 对象：{path}")
    settings = Settings()
    for key, value in raw.items():
        if key not in _KNOWN_SETTINGS:
            settings.notices.append(f"settings.json 有未知键 {key!r}（已忽略）")
            continue
        if key == "lastChangelogVersion" and isinstance(value, str):
            settings.last_changelog_version = value or None
        elif key == "defaultProvider" and isinstance(value, str):
            settings.default_provider = value or None
        elif key == "defaultModel" and isinstance(value, str):
            settings.default_model = value or None
        elif key == "commandTimeoutSeconds" and isinstance(value, int) and not isinstance(
            value, bool
        ):
            if not 1 <= value <= COMMAND_TIMEOUT_MAX:
                raise ConfigError(
                    f"settings.json 的 'commandTimeoutSeconds' 要在 1–{COMMAND_TIMEOUT_MAX} "
                    f"秒之间（给了 {value}）"
                )
            settings.command_timeout = value
        else:
            expected = _KNOWN_SETTINGS[key].__name__
            raise ConfigError(
                f"settings.json 的 {key!r} 类型不对（应为 {expected}）：{value!r}"
            )
    return settings


def record_changelog_version(version: str, home: Path | None = None) -> Path | None:
    """把当前版本号写回 settings.json 的 lastChangelogVersion（读-改-写，保留其他键）。

    只更新已存在的文件（还没有配置文件说明还没起步，不凭空创建）；坏文件不动它
    （load_settings 已经会报错，这里不做第二次破坏）。返回写过的路径；没写则 None。

    写入走"临时文件 + `os.replace`"原子替换：这是唯一由程序自动改写 settings.json 的路径，
    写一半被打断（Ctrl+C/杀进程）不能留下截断文件——坏 settings.json 会让之后每次启动报错。
    """
    path = _settings_path(home)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    stored = raw.get("lastChangelogVersion")
    if not should_record(stored if isinstance(stored, str) else None, version):
        return None  # 一致/回退不写（回退时水位不能被拉低，否则再升级会重放整段更新）
    raw["lastChangelogVersion"] = version
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)  # 写不进去（只读盘等）不该拖垮一次正常启动
        return None
    return path
