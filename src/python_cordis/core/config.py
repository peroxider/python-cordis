"""F4: config assembly on top of OmegaConf.

- ``load``    : parse YAML (string or file path) into a structured config.
- ``overlay`` : merge several configs; a later config wins on the same key
                and may insert entries the earlier ones do not have.
- ``dump``    : serialize the merged config back to YAML.
- ``resolve`` : resolve interpolations (``${other.key}``), detecting cycles.

This module deliberately provides no arbitrary code execution: cordis's
``with(ctx){eval}`` ``!!js`` expressions are replaced by OmegaConf
interpolations for safety.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from omegaconf import DictConfig, ListConfig, OmegaConf

__all__ = ["load", "overlay", "dump", "resolve", "load_file", "load_str"]


def load_str(source: str) -> DictConfig:
    """Parse a YAML string into a ``DictConfig``."""
    return cast(DictConfig, OmegaConf.create(source))


def load_file(path: str | os.PathLike[str]) -> DictConfig:
    """Load a YAML file into a ``DictConfig``."""
    return cast(DictConfig, OmegaConf.load(Path(path)))


def load(source: str | os.PathLike[str] | DictConfig) -> DictConfig:
    """Load a config from a YAML string, a file path, or an existing config."""
    if isinstance(source, (DictConfig,)):
        return source
    text = Path(source)
    if text.exists():
        return load_file(text)
    return load_str(str(source))


def overlay(*configs: DictConfig | ListConfig | dict[str, Any]) -> DictConfig:
    """Merge configs left to right; later wins on the same key.

    Supports nesting and inserting new entries. The result is a fresh
    ``DictConfig`` that never aliases an input.
    """
    result: DictConfig = OmegaConf.create()
    for cfg in configs:
        result = cast(DictConfig, OmegaConf.merge(result, cfg))
    return result


def dump(cfg: DictConfig | ListConfig | dict[str, Any]) -> str:
    """Serialize a config to YAML."""
    return OmegaConf.to_yaml(cfg)


def resolve(cfg: DictConfig | ListConfig) -> DictConfig | ListConfig:
    """Resolve every interpolation in-place; raises on cycles/unknown refs."""
    OmegaConf.resolve(cfg)
    return cfg
