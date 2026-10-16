"""用户级 models.json：**运行参数的唯一来源**（SPEC §M）。

加载模型需要的一切——端点、密钥、模型清单——只从这里读。随包目录
（src/codelotte/providers/models.json）只提供计费事实与展示/上限默认值，规则：

- 模型 id 必须在随包目录里**已适配**（codelotte 只支持自己适配过的模型，配了未适配的报错）；
- `contextWindow` / `maxTokens` 可省（随包默认），写了必须**不超过**随包默认值（官方上限，
  只能下调不能上调）；
- `name` 用户写了用用户的，没写用随包的；`reasoning_effort` 同理（默认随包的 `high`），
  它**直接进请求体**：`none` 关闭思考（不产生思考内容、不展示、不花这笔 token），
  其余档位开启思考并控制强度——展示总是跟随开关，没有单独的展示配置；
- 用户多写的字段（含计费字段）一律忽略——钱的事以随包文件为准，用户只配自己能改的。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codelotte.config import USER_CONFIG_DIR, ConfigError, Settings
from codelotte.cost import REASONING_EFFORTS, Catalog

MODELS_FILE_NAME = "models.json"


@dataclass(frozen=True)
class ModelSpec:
    """一次运行最终采用的模型参数（用户文件 ⊕ 随包默认值，已校验）。

    provider 名不在此：它只用于解析期的报错指路，装配链上不需要（请求只认端点/密钥/模型 id）。
    """

    id: str
    name: str
    context_window: int
    max_output_tokens: int
    reasoning_effort: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class _Entry:
    id: str
    name: str
    context_window: int
    max_output_tokens: int
    reasoning_effort: str


@dataclass(frozen=True)
class _Provider:
    base_url: str
    api_key: str
    models: tuple[_Entry, ...]


def _models_path(home: Path | None) -> Path:
    home_dir = home if home is not None else Path.home()
    return home_dir / USER_CONFIG_DIR / MODELS_FILE_NAME


def _read_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(
            f"未找到模型参数文件：请创建 {path}"
            '（格式：{"providers": {"<名字>": {"baseUrl": …, "apiKey": …, "models": [{"id": …}]}}}，'
            "见 docs/tech/configuration.md）"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except OSError as exc:
        raise ConfigError(f"模型参数文件读不动：{path}（{exc}）") from exc
    except ValueError as exc:
        raise ConfigError(f"模型参数文件不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"模型参数文件顶层应是 JSON 对象：{path}")
    return raw


def _bounded(value: Any, limit: int, field: str, where: str) -> int:
    """上限字段（contextWindow / maxTokens）：可省（用随包默认），写了必须 ≤ 随包值。"""
    if value is None:
        return limit
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{where} 的 {field} 要正整数（给了 {value!r}）")
    if value > limit:
        raise ConfigError(
            f"{where} 的 {field}={value} 超过上限 {limit}"
            "（随包目录里的官方值，只能下调不能上调）"
        )
    return value


def _entry(spec: Any, provider: str, path: Path, catalog: Catalog) -> _Entry:
    if not isinstance(spec, dict):
        raise ConfigError(f"{path} 的 providers.{provider}.models 里应是对象（给了 {spec!r}）")
    model_id = spec.get("id")
    if not isinstance(model_id, str) or not model_id:
        raise ConfigError(f"{path} 的 providers.{provider} 有模型条目缺少 id")
    info = catalog.models.get(model_id)
    if info is None:
        raise ConfigError(
            f"providers.{provider} 配置了未适配的模型 {model_id!r}："
            f"codelotte 只支持随包目录里已适配的模型 {sorted(catalog.models)}"
        )
    where = f"{provider}/{model_id}"
    name = spec.get("name")
    if name is not None and (not isinstance(name, str) or not name):
        raise ConfigError(f"{where} 的 name 要是非空字符串（给了 {name!r}）")
    if "reasoning" in spec:
        # 旧键（boolean 展示开关）已改名：静默忽略会让"写了 false 以为关了思考"的人继续白花 token
        raise ConfigError(
            f"{where} 的 reasoning 已改名 reasoning_effort（none 关闭思考，其余档位开启并控制强度）"
        )
    effort = spec.get("reasoning_effort", info.reasoning_effort)
    if not isinstance(effort, str) or effort not in REASONING_EFFORTS:
        raise ConfigError(
            f"{where} 的 reasoning_effort 要是 {'/'.join(REASONING_EFFORTS)} 之一（给了 {effort!r}）"
        )
    return _Entry(
        id=model_id,
        name=name or info.name,  # 展示名：用户写了用用户的，没写用随包的默认
        context_window=_bounded(spec.get("contextWindow"), info.context_window, "contextWindow", where),
        max_output_tokens=_bounded(spec.get("maxTokens"), info.max_output_tokens, "maxTokens", where),
        reasoning_effort=effort,  # 没写用随包默认档（none 关闭思考；展示总是跟随）
    )


def _providers(raw: dict[str, Any], path: Path, catalog: Catalog) -> dict[str, _Provider]:
    values = raw.get("providers")
    if not isinstance(values, dict) or not values:
        raise ConfigError(f"{path} 缺少 providers（至少配一个 provider：baseUrl / apiKey / models）")
    providers: dict[str, _Provider] = {}
    for provider_name, spec in values.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{path} 的 providers.{provider_name} 应是对象（给了 {spec!r}）")
        base_url = spec.get("baseUrl")
        if not isinstance(base_url, str) or not base_url:
            hint = catalog.base_urls.get(str(provider_name))
            suffix = f"（官方端点：{hint}）" if hint else ""
            raise ConfigError(f"providers.{provider_name} 缺少 baseUrl{suffix}：请在 {path} 补上")
        api_key = spec.get("apiKey")
        if not isinstance(api_key, str) or not api_key:
            raise ConfigError(f"providers.{provider_name} 缺少 apiKey：请在 {path} 补上")
        entries = spec.get("models")
        if not isinstance(entries, list) or not entries:
            raise ConfigError(f"providers.{provider_name} 的 models 不能为空（列出要用的模型 id）")
        providers[str(provider_name)] = _Provider(
            base_url=base_url,
            api_key=api_key,
            models=tuple(_entry(entry, str(provider_name), path, catalog) for entry in entries),
        )
    return providers


def resolve(settings: Settings, catalog: Catalog, *, home: Path | None = None) -> ModelSpec:
    """settings 的选择（defaultProvider/defaultModel）⊕ 用户文件 ⊕ 随包默认值 → 最终运行参数。

    用户文件整体校验（所有 provider、所有模型条目）——配置错误要响，一次列全。
    """
    path = _models_path(home)
    providers = _providers(_read_file(path), path, catalog)
    provider_name = settings.default_provider
    if not provider_name:
        raise ConfigError(
            '未配置默认 provider：请在 ~/.codelotte/settings.json 设置 "defaultProvider"'
            f"（{path} 里可选：{sorted(providers)}）"
        )
    provider = providers.get(provider_name)
    if provider is None:
        raise ConfigError(
            f"未知 provider {provider_name!r}：{path} 里配置的是 {sorted(providers)}"
        )
    available = [entry.id for entry in provider.models]
    model_id = settings.default_model
    if not model_id:
        raise ConfigError(
            '未配置默认模型：请在 ~/.codelotte/settings.json 设置 "defaultModel"'
            f"（providers.{provider_name} 里可选：{available}）"
        )
    for entry in provider.models:
        if entry.id == model_id:
            return ModelSpec(
                id=entry.id,
                name=entry.name,
                context_window=entry.context_window,
                max_output_tokens=entry.max_output_tokens,
                reasoning_effort=entry.reasoning_effort,
                base_url=provider.base_url,
                api_key=provider.api_key,
            )
    raise ConfigError(f"未知模型 {model_id!r}：providers.{provider_name} 里配置的是 {available}")
