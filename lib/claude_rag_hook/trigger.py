"""Trigger parser.

Decides whether a user prompt is a RAG turn and, if so, extracts the
query text and any tag scope (e.g. 'rag@work: ...').

Supported forms (case-insensitive, leading whitespace tolerated):

    rag: <text>
    /rag <text>
    rag <text>            (lax form, off by default; only if `lax_trigger`)
    rag@<tag>: <text>     (federated across tagged stores)
    rag@all: <text>       (federated across all registered stores)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TriggerMatch:
    query: str
    tag: str | None  # None means "current folder"; "all" means every store; otherwise a tag


# Order matters: longer / more specific patterns first.
_PATTERNS_TAGGED = [
    re.compile(r"^\s*rag@([A-Za-z0-9_.\-]+)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*/rag@([A-Za-z0-9_.\-]+)\s+(.*)$", re.IGNORECASE | re.DOTALL),
]

_PATTERNS_PLAIN = {
    "rag:": re.compile(r"^\s*rag\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL),
    "/rag": re.compile(r"^\s*/rag(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL),
}

_LAX = re.compile(r"^\s*rag\s+(.*)$", re.IGNORECASE | re.DOTALL)


def parse(prompt: str, triggers: list[str], lax: bool = False) -> TriggerMatch | None:
    if not prompt:
        return None

    for pat in _PATTERNS_TAGGED:
        m = pat.match(prompt)
        if m:
            tag = m.group(1).strip().lower() or None
            query = (m.group(2) or "").strip()
            if not query:
                return None
            return TriggerMatch(query=query, tag=tag)

    enabled = {t.strip().lower() for t in triggers}
    for key, pat in _PATTERNS_PLAIN.items():
        if key not in enabled:
            continue
        m = pat.match(prompt)
        if m:
            query = ((m.group(1) or "") if m.lastindex else "").strip()
            if not query:
                return None
            return TriggerMatch(query=query, tag=None)

    if lax:
        m = _LAX.match(prompt)
        if m:
            query = (m.group(1) or "").strip()
            if not query:
                return None
            return TriggerMatch(query=query, tag=None)

    return None
