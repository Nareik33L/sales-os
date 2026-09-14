"""Config loaders must fail closed: valid YAML loads, bad weights and unknown files raise."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from config.loaders import (
    CONFIG_DIR,
    AppConfig,
    ConfigError,
    config_yaml_files,
    load_all,
    load_priority_weights,
)


def test_committed_yaml_files_all_load():
    stems = {p.stem for p in config_yaml_files()}
    assert stems == {
        "ai",
        "excel_mapping",
        "matching",
        "priority_weights",
        "sources",
    }
    cfg = load_all()
    assert isinstance(cfg, AppConfig)
    assert cfg.priority_weights.deal.weights.deal_value == pytest.approx(0.30)
    deal_total = sum(cfg.priority_weights.deal.weights.model_dump().values())
    action_total = sum(cfg.priority_weights.action.weights.model_dump().values())
    assert deal_total == pytest.approx(1.0)
    assert action_total == pytest.approx(1.0)
    assert "hubspot" in cfg.sources.connectors
    assert cfg.ai.tasks["extract_memory"].require_quotes is True
    assert cfg.excel_mapping.product == "PRODUCT_B"
    assert cfg.matching.thresholds.auto_link == pytest.approx(0.90)


def test_deal_weights_not_summing_to_one_raises(tmp_path: Path):
    src = (CONFIG_DIR / "priority_weights.yaml").read_text(encoding="utf-8")
    bad = src.replace("deal_value: 0.30", "deal_value: 0.50", 1)
    assert "deal_value: 0.50" in bad
    path = tmp_path / "priority_weights.yaml"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError, match=r"deal weights sum to"):
        load_priority_weights(path)


def test_action_weights_not_summing_to_one_raises(tmp_path: Path):
    src = (CONFIG_DIR / "priority_weights.yaml").read_text(encoding="utf-8")
    bad = src.replace("inherited_deal_score: 0.6", "inherited_deal_score: 0.9", 1)
    path = tmp_path / "priority_weights.yaml"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError, match=r"action weights sum to"):
        load_priority_weights(path)


def test_unknown_yaml_file_fails_fast(tmp_path: Path):
    for path in config_yaml_files():
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "extra.yaml").write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="No typed loader"):
        load_all(tmp_path)


def test_invalid_yaml_raises(tmp_path: Path):
    path = tmp_path / "priority_weights.yaml"
    path.write_text("version: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_priority_weights(path)


def test_missing_config_file_raises(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_priority_weights(tmp_path / "priority_weights.yaml")


def test_run_exits_on_invalid_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for path in config_yaml_files():
        shutil.copy(path, tmp_path / path.name)
    weights = tmp_path / "priority_weights.yaml"
    weights.write_text(
        weights.read_text(encoding="utf-8").replace(
            "deal_value: 0.30", "deal_value: 0.50", 1
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("config.loaders.CONFIG_DIR", tmp_path)
    monkeypatch.setenv("SALESOS_DB_PATH", str(tmp_path / "salesos.db"))
    monkeypatch.setenv("SALESOS_DATA_DIR", str(tmp_path))
    from run import main

    assert main(["--migrate"]) == 1
