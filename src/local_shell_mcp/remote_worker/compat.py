"""Remote-worker-only compatibility layer."""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import sys
import types
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_MISSING = object()


class _FieldInfo:
    def __init__(
        self, default: Any = _MISSING, *, default_factory: Any = _MISSING
    ) -> None:
        self.default = default
        self.default_factory = default_factory

    def value(self) -> Any:
        if self.default_factory is not _MISSING:
            return self.default_factory()
        if self.default is not _MISSING:
            return self.default
        return None


def _jsonable(value: Any, *, exclude_none: bool = False) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).decode(errors="replace")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, enum.Enum):
        return _jsonable(value.value, exclude_none=exclude_none)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json", exclude_none=exclude_none)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value), exclude_none=exclude_none)
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item, exclude_none=exclude_none)
            for key, item in value.items()
            if not (exclude_none and item is None)
        }
    if isinstance(value, Sequence) and not isinstance(
        value, str | bytes | bytearray
    ):
        return [_jsonable(item, exclude_none=exclude_none) for item in value]
    if isinstance(value, set | frozenset):
        return [_jsonable(item, exclude_none=exclude_none) for item in value]
    return value


def _all_annotations(cls: type[Any]) -> dict[str, Any]:
    annotations: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        annotations.update(getattr(base, "__annotations__", {}))
    annotations.pop("model_config", None)
    return annotations


def _validator_marker(obj: Any) -> Any:
    if isinstance(obj, classmethod | staticmethod):
        return obj.__func__
    return obj


def _convert_env_value(field_name: str, raw: str, default: Any) -> Any:
    if isinstance(default, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    if isinstance(default, Path) or field_name in {
        "workspace_root",
        "state_dir",
    }:
        return Path(
            os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
        )
    if isinstance(default, list):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


class _BaseModel:
    model_fields: dict[str, Any] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.model_fields = _all_annotations(cls)

    def __init__(self, **data: Any) -> None:
        cls = type(self)
        for name in cls.model_fields:
            if name in data:
                value = data.pop(name)
            else:
                default = getattr(cls, name, _MISSING)
                if isinstance(default, _FieldInfo):
                    value = default.value()
                elif default is _MISSING:
                    value = None
                else:
                    value = default
            value = self._run_field_validators(name, value)
            setattr(self, name, value)
        for name, value in data.items():
            setattr(self, name, value)
        self._run_model_validators()

    @classmethod
    def _run_field_validators(cls, field_name: str, value: Any) -> Any:
        for base in reversed(cls.__mro__):
            for attr in base.__dict__.values():
                marker = _validator_marker(attr)
                fields = getattr(
                    marker, "__remote_worker_field_validator_fields__", ()
                )
                mode = getattr(
                    marker, "__remote_worker_field_validator_mode__", None
                )
                if field_name in fields and mode in {"before", None}:
                    method = (
                        attr.__get__(None, cls)
                        if isinstance(attr, classmethod)
                        else attr
                    )
                    value = method(value)
        return value

    def _run_model_validators(self) -> None:
        cls = type(self)
        for base in reversed(cls.__mro__):
            for name, attr in base.__dict__.items():
                marker = _validator_marker(attr)
                if (
                    getattr(
                        marker, "__remote_worker_model_validator_mode__", None
                    )
                    == "after"
                ):
                    result = getattr(self, name)()
                    if result is not None and result is not self:
                        self.__dict__.update(getattr(result, "__dict__", {}))

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        exclude_none = bool(kwargs.get("exclude_none", False))
        return {
            key: _jsonable(value, exclude_none=exclude_none)
            for key, value in self.__dict__.items()
            if not (exclude_none and value is None)
        }

    @classmethod
    def model_validate(cls, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(**dict(value))
        return cls(root=value)


class _RootModel(_BaseModel):
    def __init__(self, root: Any = None, **data: Any) -> None:
        self.root = data if data and root is None else root

    def model_dump(self, *args: Any, **kwargs: Any) -> Any:
        return _jsonable(
            self.root, exclude_none=bool(kwargs.get("exclude_none", False))
        )


class _BaseSettings(_BaseModel):
    def __init__(self, **data: Any) -> None:
        config = getattr(type(self), "model_config", {}) or {}
        env_prefix = str(config.get("env_prefix") or "")
        for name in type(self).model_fields:
            env_name = f"{env_prefix}{name.upper()}"
            if name not in data and env_name in os.environ:
                default = getattr(type(self), name, None)
                if isinstance(default, _FieldInfo):
                    default = default.value()
                data[name] = _convert_env_value(
                    name, os.environ[env_name], default
                )
        super().__init__(**data)


class _ValidationError(ValueError):
    pass


class _TypeAdapter:
    def __init__(self, annotation: Any) -> None:
        self.annotation = annotation

    def validate_python(self, value: Any) -> Any:
        return value


class _StringConstraints:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _NoDecode:
    pass


def _Field(default: Any = _MISSING, **kwargs: Any) -> Any:
    if "default_factory" in kwargs:
        return _FieldInfo(default, default_factory=kwargs["default_factory"])
    if default is _MISSING:
        return _FieldInfo()
    return _FieldInfo(default)


def _ConfigDict(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


def _SettingsConfigDict(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


def _field_validator(
    *fields: str, mode: str | None = None, **kwargs: Any
) -> Any:
    def decorate(func: Any) -> Any:
        marker = _validator_marker(func)
        marker.__remote_worker_field_validator_fields__ = fields
        marker.__remote_worker_field_validator_mode__ = mode
        return func

    return decorate


def _model_validator(*, mode: str | None = None, **kwargs: Any) -> Any:
    def decorate(func: Any) -> Any:
        marker = _validator_marker(func)
        marker.__remote_worker_model_validator_mode__ = mode
        return func

    return decorate


def _computed_field(func: Any = None, **kwargs: Any) -> Any:
    if func is None:
        return lambda wrapped: property(wrapped)
    return property(func)


def _PrivateAttr(default: Any = None, default_factory: Any = None) -> Any:
    if default_factory is not None:
        return default_factory()
    return default


def _install_pydantic_shim() -> None:
    if "pydantic" not in sys.modules:
        module = types.ModuleType("pydantic")
        module.__dict__.update(
            {
                "BaseModel": _BaseModel,
                "RootModel": _RootModel,
                "Field": _Field,
                "ConfigDict": _ConfigDict,
                "ValidationError": _ValidationError,
                "TypeAdapter": _TypeAdapter,
                "StringConstraints": _StringConstraints,
                "field_validator": _field_validator,
                "model_validator": _model_validator,
                "computed_field": _computed_field,
                "PrivateAttr": _PrivateAttr,
            }
        )
        sys.modules["pydantic"] = module
    if "pydantic_settings" not in sys.modules:
        module = types.ModuleType("pydantic_settings")
        module.__dict__.update(
            {
                "BaseSettings": _BaseSettings,
                "NoDecode": _NoDecode,
                "SettingsConfigDict": _SettingsConfigDict,
            }
        )
        sys.modules["pydantic_settings"] = module


def _install_yaml_shim() -> None:
    if "yaml" in sys.modules:
        return
    module = types.ModuleType("yaml")

    def safe_load(text: str) -> Any:
        stripped = text.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            data: dict[str, Any] = {}
            for line in stripped.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                value = value.strip().strip("'\"")
                if value.lower() in {"true", "false"}:
                    data[key.strip()] = value.lower() == "true"
                else:
                    data[key.strip()] = value
            return data

    module.__dict__["safe_load"] = safe_load
    sys.modules["yaml"] = module


def _install_pathspec_shim() -> None:
    if "pathspec" in sys.modules:
        return
    module = types.ModuleType("pathspec")

    class PathSpec:
        @classmethod
        def from_lines(cls, pattern_factory: str, lines: Any) -> PathSpec:
            return cls()

        def match_file(self, path: str) -> bool:
            return False

    module.__dict__["PathSpec"] = PathSpec
    sys.modules["pathspec"] = module


def _install_remote_session_stub() -> None:
    name = "local_shell_mcp.ops.utils.remote_session"
    if name in sys.modules:
        return
    module = types.ModuleType(name)

    async def call_remote_session_tool(
        *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        raise RuntimeError(
            "nested remote session dispatch is not available inside a remote worker"
        )

    async def start_worker_session(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            "remote worker cannot create nested remote worker sessions"
        )

    module.__dict__.update(
        {
            "call_remote_session_tool": call_remote_session_tool,
            "start_worker_session": start_worker_session,
        }
    )
    sys.modules[name] = module


def install() -> None:
    """Install all remote-worker import shims and dispatch patches."""
    _install_pydantic_shim()
    _install_yaml_shim()
    _install_pathspec_shim()
    _install_remote_session_stub()

    from local_shell_mcp.remote_worker import worker
    from local_shell_mcp.remote_worker.dispatch import execute_worker_tool

    worker.execute_worker_tool = execute_worker_tool


def main(argv: list[str] | None = None) -> None:
    """Run the shared remote worker loop with worker-only shims installed."""
    install()
    from local_shell_mcp.remote_worker.worker import run_worker_cli

    run_worker_cli(sys.argv[1:] if argv is None else argv)
