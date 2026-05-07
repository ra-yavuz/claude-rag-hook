"""Configuration loader.

Single YAML file at ~/.config/claude-rag-hook/config.yaml. Defaults are
inlined here so a missing file is not an error.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import paths


DEFAULTS: dict[str, Any] = {
    "triggers": ["rag:", "/rag"],
    "lax_trigger": False,
    "top_k": 5,
    "embedder": {
        "kind": "fastembed",
        "model": "nomic-embed-text-v1.5",
        "query_prefix": "search_query: ",
        "document_prefix": "search_document: ",
        "base_url": "http://127.0.0.1:19080",
        "hydra_id": "nomic-embed-text",
    },
    "chunking": {
        "target_chars": 1500,
        "overlap_chars": 200,
    },
    "walker": {
        "max_file_size_mb": 1,
        "respect_gitignore": True,
    },
    "daemon": {
        "idle_ttl_seconds": 1800,
        "enabled": True,
    },
    "context": {
        "header": "<context>",
        "footer": "</context>",
        "show_source_lines": True,
    },
}


@dataclass
class Config:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    def get(self, *keys: str, default: Any = None) -> Any:
        cur: Any = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def set(self, dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        cur = self.data
        for k in parts[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[parts[-1]] = value

    def save(self, path: Path | None = None) -> None:
        path = path or paths.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, sort_keys=False, default_flow_style=False)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: Path | None = None) -> Config:
    path = path or paths.config_file()
    if not path.exists():
        return Config()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping at the top level")
    return Config(data=_deep_merge(DEFAULTS, data))


def triggers(cfg: Config) -> list[str]:
    triggers = list(cfg.get("triggers", default=DEFAULTS["triggers"]) or [])
    if cfg.get("lax_trigger", default=False):
        triggers.append("rag ")
    return triggers
