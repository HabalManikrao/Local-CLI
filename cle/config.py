"""Configuration loading.

Layering (lowest precedence first):
  1. Packaged defaults (``configs/default.yaml``).
  2. Project config (``<project>/.cle/config.yaml``), deep-merged on top.

Project config is intentionally sparse: it overrides only what differs from
the defaults, so upgrades to the default schema flow through automatically.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

# Packaged defaults live at <repo>/configs/default.yaml. Resolve relative to
# this file so it works regardless of the current working directory.
_DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "configs" / "default.yaml"

# Directory + file name used for project-scoped config.
CLE_DIR_NAME = ".cle"
PROJECT_CONFIG_NAME = "config.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of *base* with *override* merged in.

    Dicts merge recursively; every other type (including lists) is replaced
    wholesale by the override value.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"Could not read config file: {path}",
            remedy="Check the file exists and is readable.",
        ) from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Config file is not valid YAML: {path}\n{exc}",
            remedy="Fix the YAML syntax and try again.",
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config file must contain a YAML mapping at the top level: {path}",
        )
    return data


def load_defaults() -> dict[str, Any]:
    """Load the packaged default configuration."""
    if not _DEFAULTS_PATH.exists():
        raise ConfigError(
            f"Packaged defaults are missing: {_DEFAULTS_PATH}",
            remedy="Reinstall CLE; the default config shipped with the package "
            "is absent.",
        )
    return _load_yaml(_DEFAULTS_PATH)


class Config:
    """Read-only view over merged configuration with dotted-path access."""

    def __init__(self, data: dict[str, Any], project_config_path: Path | None):
        self._data = data
        # Path the project overrides were (or would be) loaded from; useful
        # for `cle status` / `cle doctor` reporting.
        self.project_config_path = project_config_path

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def get(self, dotted: str, default: Any = None) -> Any:
        """Fetch a value by dotted path, e.g. ``config.get("models.coding")``."""
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def project_config_path(root: Path) -> Path:
    return root / CLE_DIR_NAME / PROJECT_CONFIG_NAME


def init_project_config(root: Path) -> Path:
    """Create ``<root>/.cle/config.yaml`` if absent. Returns its path.

    Idempotent: an existing project config is left untouched.
    """
    path = project_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Local CLE project configuration.\n"
            "# Values here override packaged defaults (deep-merged).\n"
            "# Assign models with:  cle model use <role> <model>\n"
            "version: 1\n",
            encoding="utf-8",
        )
    return path


def set_project_value(root: Path, dotted: str, value: Any) -> Path:
    """Set a dotted-path *value* in the project config, creating it if needed.

    Only the project overrides file is modified; defaults are never written.
    """
    path = init_project_config(root)
    data = _load_yaml(path)
    node = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        existing = node.get(part)
        if not isinstance(existing, dict):
            existing = {}
            node[part] = existing
        node = existing
    node[parts[-1]] = value
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return path


def load_config(project_root: Path | None) -> Config:
    """Build the effective configuration for *project_root*.

    If *project_root* is ``None`` or has no project config, defaults are used
    as-is (commands like ``cle doctor`` must work outside a project).
    """
    merged = load_defaults()
    project_config_path: Path | None = None
    if project_root is not None:
        candidate = project_root / CLE_DIR_NAME / PROJECT_CONFIG_NAME
        project_config_path = candidate
        if candidate.exists():
            overrides = _load_yaml(candidate)
            merged = _deep_merge(merged, overrides)
    return Config(merged, project_config_path)
