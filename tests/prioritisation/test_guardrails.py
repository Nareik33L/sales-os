"""Architecture guardrails for core/prioritisation (ADR-002)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "core" / "prioritisation"


def test_prioritisation_never_imports_ai():
    files = list(ROOT.glob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "ai" and not alias.name.startswith("ai.")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "ai" and not module.startswith("ai.")
