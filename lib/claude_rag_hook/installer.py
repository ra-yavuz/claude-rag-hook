"""Wire claude-rag-hook into Claude Code's ~/.claude/settings.json.

We modify settings.json automatically with a clear backup. The user can
revert at any time with `claude-rag-hook uninstall`.

Schema (per Claude Code docs):

    {
      "hooks": {
        "UserPromptSubmit": [
          { "command": "claude-rag-hook hook" }
        ]
      }
    }

We tag our entry with `"name": "claude-rag-hook"` so uninstall finds it.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

from . import paths


HOOK_ENTRY: dict[str, Any] = {
    "name": "claude-rag-hook",
    "command": "claude-rag-hook hook",
    "description": "Keyword-triggered local RAG: 'rag: <q>' prepends retrieved chunks.",
}


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, bak)
    return bak


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        return {}
    return json.loads(text)


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def install(dry_run: bool = False, settings_path: Path | None = None) -> tuple[Path, Path | None, bool]:
    settings_path = settings_path or paths.claude_settings_file()
    data = _load(settings_path)
    hooks = data.setdefault("hooks", {})
    arr = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(arr, list):
        raise RuntimeError(
            f"{settings_path}: hooks.UserPromptSubmit is not an array; refusing to modify"
        )

    # Already installed?
    for entry in arr:
        if isinstance(entry, dict) and entry.get("name") == "claude-rag-hook":
            return settings_path, None, False

    arr.append(dict(HOOK_ENTRY))
    if dry_run:
        return settings_path, None, True

    bak = _backup(settings_path)
    _save(settings_path, data)
    return settings_path, bak, True


def uninstall(settings_path: Path | None = None) -> tuple[Path, Path | None, bool]:
    settings_path = settings_path or paths.claude_settings_file()
    if not settings_path.exists():
        return settings_path, None, False
    data = _load(settings_path)
    hooks = data.get("hooks") or {}
    arr = hooks.get("UserPromptSubmit") or []
    if not isinstance(arr, list):
        return settings_path, None, False
    new_arr = [e for e in arr if not (isinstance(e, dict) and e.get("name") == "claude-rag-hook")]
    if len(new_arr) == len(arr):
        return settings_path, None, False
    if new_arr:
        hooks["UserPromptSubmit"] = new_arr
    else:
        hooks.pop("UserPromptSubmit", None)
    if not hooks:
        data.pop("hooks", None)
    bak = _backup(settings_path)
    _save(settings_path, data)
    return settings_path, bak, True


def is_installed(settings_path: Path | None = None) -> bool:
    settings_path = settings_path or paths.claude_settings_file()
    if not settings_path.exists():
        return False
    try:
        data = _load(settings_path)
    except json.JSONDecodeError:
        return False
    arr = (data.get("hooks") or {}).get("UserPromptSubmit") or []
    return any(isinstance(e, dict) and e.get("name") == "claude-rag-hook" for e in arr)
