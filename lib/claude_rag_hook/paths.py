"""Filesystem paths used by claude-rag-hook.

XDG-compliant locations for config, cache, and per-user state.
"""

from __future__ import annotations

import os
from pathlib import Path


INDEX_DIR_NAME = ".claude-rag-index"
HYDRA_INDEX_DIR_NAME = ".hydra-index"


def _xdg(env: str, fallback: Path) -> Path:
    val = os.environ.get(env)
    return Path(val) if val else fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "claude-rag-hook"


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", Path.home() / ".cache") / "claude-rag-hook"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / "claude-rag-hook"


SYSTEM_MODELS_DIR = Path("/var/cache/claude-rag-hook/models")


def models_cache_dir() -> Path:
    """Return the directory fastembed (and any future model backends)
    should use as their cache.

    Prefer the machine-wide /var/cache/claude-rag-hook/models/ if it
    exists and is writable by the current user (created by the apt
    postinst, mode 0775 root:adm). Falls back to the per-user
    ~/.cache/claude-rag-hook/models/ otherwise.

    Centralising this in one helper means:
    - Reboots don't wipe model files (the upstream-default /tmp does).
    - apt postinst can pre-fetch into the same location the hook will
      read at runtime, so first `rag` is fast even on fresh installs.
    - apt purge can clean it up.
    - Multi-user hosts share one ~80MB ONNX download.
    """
    if SYSTEM_MODELS_DIR.is_dir() and os.access(SYSTEM_MODELS_DIR, os.W_OK):
        return SYSTEM_MODELS_DIR
    user = cache_dir() / "models"
    user.mkdir(parents=True, exist_ok=True)
    return user


def config_file() -> Path:
    return config_dir() / "config.yaml"


def stores_registry() -> Path:
    return state_dir() / "stores.json"


def daemon_socket() -> Path:
    return cache_dir() / "embedder.sock"


def daemon_pidfile() -> Path:
    return cache_dir() / "embedder.pid"


def daemon_logfile() -> Path:
    return cache_dir() / "embedder.log"


def claude_settings_file() -> Path:
    return Path.home() / ".claude" / "settings.json"


def find_index(start: Path) -> Path | None:
    """Walk up from `start` and return the path to the nearest index folder.

    Recognises this tool's `.claude-rag-index/` and hydra-llm's
    `.hydra-index/` (so users who already use hydra-llm don't need to
    re-index).
    """
    start = start.resolve()
    for d in (start, *start.parents):
        for name in (INDEX_DIR_NAME, HYDRA_INDEX_DIR_NAME):
            cand = d / name
            if cand.is_dir():
                return cand
    return None


def ensure_dirs() -> None:
    for d in (config_dir(), cache_dir(), state_dir()):
        d.mkdir(parents=True, exist_ok=True)
    # The cache dir holds the daemon socket; tighten permissions.
    try:
        os.chmod(cache_dir(), 0o700)
    except OSError:
        pass
