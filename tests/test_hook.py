"""Smoke tests for the hook entrypoint.

Focus is on the non-blocking paths: status command and the
indexing-banner short-circuit. Anything that would touch the embedder
or LanceDB is out of scope here (covered by the indexer tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_rag_hook import hook, paths, progress as progress_mod


def _make_envelope(prompt: str, cwd: Path) -> str:
    return json.dumps({"prompt": prompt, "cwd": str(cwd)})


def test_status_no_index_in_indexable_project(tmp_path, capsys, monkeypatch):
    # A project with a marker but no index yet. Status should report
    # "not yet built" and tell the user how to start.
    (tmp_path / ".git").mkdir()
    rc = hook.run(_make_envelope("rag", tmp_path), cwd=tmp_path)
    assert rc == 0
    captured = capsys.readouterr()
    assert "not yet built" in captured.out or "not yet built" in captured.err
    assert "rag" in captured.out  # action hint


def test_status_with_populated_index(tmp_path, capsys):
    # A populated index with last_run.json should report concrete numbers.
    (tmp_path / ".git").mkdir()
    index_dir = tmp_path / paths.INDEX_DIR_NAME
    index_dir.mkdir()
    # LanceDB-style table dir to satisfy the "populated" check.
    (index_dir / "chunks.lance").mkdir()
    progress_mod.write_last_run(
        index_dir,
        progress_mod.LastRun(
            finished_at=0.0,  # ancient -> "ago" formatter shouldn't crash
            elapsed_seconds=12.5,
            kind="indexing",
            files_total=42,
            files_indexed=42,
            files_pruned=0,
            chunks_added=315,
        ),
    )
    rc = hook.run(_make_envelope("rag", tmp_path), cwd=tmp_path)
    assert rc == 0
    captured = capsys.readouterr()
    assert "315" in captured.out
    assert "ready" in captured.out
    assert "42" in captured.out


def test_status_alternate_forms(tmp_path, capsys):
    # `rag status`, `/rag`, and bare `rag` should all hit the status path.
    (tmp_path / ".git").mkdir()
    for form in ("rag", "/rag", "rag status", "rag:"):
        rc = hook.run(_make_envelope(form, tmp_path), cwd=tmp_path)
        assert rc == 0, f"form {form!r} returned {rc}"
        captured = capsys.readouterr()
        assert "[claude-rag-hook status]" in captured.out, (
            f"form {form!r} did not produce a status block: {captured.out!r}"
        )


def test_indexing_banner_on_non_rag_prompt(tmp_path, capsys):
    # An active indexing job for the cwd's tree should produce a banner
    # on stdout for any non-rag prompt.
    import os
    (tmp_path / ".git").mkdir()
    index_dir = tmp_path / paths.INDEX_DIR_NAME
    index_dir.mkdir()
    progress_mod.write(
        index_dir,
        progress_mod.Progress(
            state="indexing",
            started_at=0.0,
            files_done=10,
            files_total=100,
            pid=os.getpid(),  # the test process is, by definition, alive
        ),
    )
    rc = hook.run(_make_envelope("how do I write a regex?", tmp_path), cwd=tmp_path)
    assert rc == 0
    captured = capsys.readouterr()
    assert "still indexing" in captured.out
    assert "10/100" in captured.out


def test_no_banner_when_no_active_job(tmp_path, capsys):
    # No progress file -> no banner on a non-rag prompt.
    (tmp_path / ".git").mkdir()
    rc = hook.run(_make_envelope("how do I write a regex?", tmp_path), cwd=tmp_path)
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_non_json_input_treated_as_prompt(tmp_path, capsys):
    # Some Claude Code wrappers may pass raw text. Bare `rag` should
    # still trip the status path.
    (tmp_path / ".git").mkdir()
    rc = hook.run("rag", cwd=tmp_path)
    assert rc == 0
    captured = capsys.readouterr()
    assert "[claude-rag-hook status]" in captured.out
