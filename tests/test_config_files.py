"""YAML config and prompt JSON schemas must parse (typed loaders are SOS-06b)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_config_yaml_loads():
    files = sorted((ROOT / "config").glob("*.yaml"))
    assert files, "expected config/*.yaml"
    for path in files:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded is not None, path


def test_prompt_schemas_load():
    files = sorted((ROOT / "ai" / "prompts" / "schemas").glob("*.json"))
    assert files, "expected ai/prompts/schemas/*.json"
    for path in files:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict), path
