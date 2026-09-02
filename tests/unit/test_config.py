from pathlib import Path

import pytest

from cle.config import (
    Config,
    load_config,
    load_defaults,
    set_project_value,
    _deep_merge,
)
from cle.errors import ConfigError


def test_load_defaults_has_expected_shape():
    d = load_defaults()
    assert d["provider"]["type"] == "ollama"
    assert set(d["models"].keys()) == {"fast", "coding", "reasoning", "embedding"}
    assert d["safety"]["require_approval"] is True


def test_deep_merge_recurses_and_replaces():
    base = {"a": {"b": 1, "c": 2}, "list": [1, 2]}
    override = {"a": {"c": 9}, "list": [3]}
    merged = _deep_merge(base, override)
    assert merged == {"a": {"b": 1, "c": 9}, "list": [3]}
    # original untouched
    assert base["a"]["c"] == 2


def test_config_get_dotted_path():
    cfg = Config({"models": {"coding": "x"}}, None)
    assert cfg.get("models.coding") == "x"
    assert cfg.get("models.missing", "def") == "def"
    assert cfg.get("nope.nope", None) is None


def test_project_override_merges_over_defaults(tmp_path: Path):
    set_project_value(tmp_path, "models.coding", "codellama")
    cfg = load_config(tmp_path)
    assert cfg.get("models.coding") == "codellama"
    # untouched defaults still present
    assert cfg.get("safety.require_approval") is True


def test_set_project_value_creates_nested(tmp_path: Path):
    path = set_project_value(tmp_path, "provider.host", "http://localhost:9999")
    assert path.exists()
    cfg = load_config(tmp_path)
    assert cfg.get("provider.host") == "http://localhost:9999"


def test_invalid_yaml_raises_config_error(tmp_path: Path):
    cfg_path = tmp_path / ".cle" / "config.yaml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("this: : : not valid", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)
