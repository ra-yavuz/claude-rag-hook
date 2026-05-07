"""Index a folder: walk -> chunk -> embed -> store.

Incremental: a manifest of (rel, mtime, size) lets the indexer skip
unchanged files between runs. Unknown / removed files are dropped from
the table.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import chunker, paths, registry, store, walker
from .embedder import Embedder


@dataclass
class IndexOptions:
    target_chars: int = 1500
    overlap_chars: int = 200
    max_file_size_mb: float = 1.0
    respect_gitignore: bool = True
    extra_excludes: list[str] | None = None
    extra_includes: list[str] | None = None
    full_rebuild: bool = False
    tags: list[str] | None = None
    batch_size: int = 64


def index_folder(
    root: Path,
    embedder: Embedder,
    opts: IndexOptions,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    index_dir = root / paths.INDEX_DIR_NAME
    say = progress or (lambda _msg: None)

    if opts.full_rebuild and index_dir.exists():
        # Drop the existing index entirely.
        import shutil
        shutil.rmtree(index_dir)

    walk_opts = walker.WalkOptions(
        max_file_size_mb=opts.max_file_size_mb,
        respect_gitignore=opts.respect_gitignore,
        extra_excludes=opts.extra_excludes,
        extra_includes=opts.extra_includes,
    )
    files = walker.all_files(root, walk_opts)
    say(f"walk: {len(files)} candidate files")

    table = store.open_table(index_dir, embedder.dim)
    manifest = store.read_files_manifest(index_dir)

    seen_rels: set[str] = set()
    to_index: list[walker.WalkedFile] = []
    for f in files:
        seen_rels.add(f.rel)
        prev = manifest.get(f.rel)
        if (
            prev is not None
            and int(prev.get("size") or -1) == f.size
            and float(prev.get("mtime") or -1.0) == f.mtime
            and not opts.full_rebuild
        ):
            continue
        to_index.append(f)

    # Files that were in the manifest but no longer exist: drop them.
    removed = [rel for rel in manifest.keys() if rel not in seen_rels]
    for rel in removed:
        store.delete_rel(table, rel)
        manifest.pop(rel, None)
    if removed:
        say(f"prune: removed {len(removed)} stale files")

    if not to_index:
        say("up to date, nothing to embed")
        store.write_meta(index_dir, embedder.kind, embedder.model, embedder.dim)
        store.write_files_manifest(index_dir, manifest)
        return {
            "files_total": len(files),
            "files_indexed": 0,
            "files_pruned": len(removed),
            "chunks_added": 0,
        }

    say(f"embed: {len(to_index)} files to (re)index")

    total_chunks = 0
    batch_texts: list[str] = []
    batch_meta: list[dict] = []

    def _flush() -> None:
        nonlocal batch_texts, batch_meta, total_chunks
        if not batch_texts:
            return
        vectors = embedder.embed_documents(batch_texts)
        rows = []
        for v, meta in zip(vectors, batch_meta):
            rows.append({**meta, "vector": v})
        store.add_rows(table, rows)
        total_chunks += len(rows)
        batch_texts = []
        batch_meta = []

    for f in to_index:
        try:
            text = f.path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"warn: skipping {f.rel}: {e}", file=sys.stderr)
            continue
        # Drop any prior chunks for this rel, we're going to add fresh ones.
        store.delete_rel(table, f.rel)
        chunks = chunker.chunk_text(text, opts.target_chars, opts.overlap_chars)
        for c in chunks:
            batch_texts.append(c.text)
            batch_meta.append({
                "rel": f.rel,
                "start_line": int(c.start_line),
                "end_line": int(c.end_line),
                "kind": f.kind,
                "text": c.text,
            })
            if len(batch_texts) >= opts.batch_size:
                _flush()
        manifest[f.rel] = {"size": f.size, "mtime": f.mtime}
    _flush()

    store.write_meta(index_dir, embedder.kind, embedder.model, embedder.dim)
    store.write_files_manifest(index_dir, manifest)

    entry = registry.StoreEntry(
        path=str(root),
        tags=list(opts.tags or []),
        embedder=f"{embedder.kind}:{embedder.model}",
        dim=int(embedder.dim),
    )
    registry.upsert(entry)

    say(f"done: {total_chunks} chunks across {len(to_index)} files")
    return {
        "files_total": len(files),
        "files_indexed": len(to_index),
        "files_pruned": len(removed),
        "chunks_added": total_chunks,
    }
