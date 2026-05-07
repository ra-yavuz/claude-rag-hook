import json
from pathlib import Path

from claude_rag_hook import installer


def test_install_into_fresh_settings(tmp_path: Path):
    p = tmp_path / "settings.json"
    path, bak, changed = installer.install(settings_path=p)
    assert changed and path == p and bak is None
    data = json.loads(p.read_text())
    arr = data["hooks"]["UserPromptSubmit"]
    assert any(e.get("name") == "claude-rag-hook" for e in arr)


def test_install_idempotent(tmp_path: Path):
    p = tmp_path / "settings.json"
    installer.install(settings_path=p)
    _path, _bak, changed = installer.install(settings_path=p)
    assert changed is False


def test_install_preserves_other_hooks(tmp_path: Path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "hooks": {
            "UserPromptSubmit": [{"name": "other", "command": "other-tool"}]
        }
    }))
    installer.install(settings_path=p)
    arr = json.loads(p.read_text())["hooks"]["UserPromptSubmit"]
    names = {e.get("name") for e in arr}
    assert "other" in names and "claude-rag-hook" in names


def test_uninstall_removes_only_our_entry(tmp_path: Path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "hooks": {
            "UserPromptSubmit": [{"name": "other"}]
        }
    }))
    installer.install(settings_path=p)
    installer.uninstall(settings_path=p)
    arr = json.loads(p.read_text())["hooks"]["UserPromptSubmit"]
    names = [e.get("name") for e in arr]
    assert names == ["other"]
