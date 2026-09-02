"""Environment diagnostics for ``cle doctor``.

Each check returns a :class:`Check` with a status (ok/warn/fail), a short
detail, and an optional remedy. Checks are deliberately defensive: a missing
optional tool is a WARN, not a crash, and GPU detection degrades to "unknown"
rather than failing (per the audit findings).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import Config
from .models.base import ModelProvider
from .models.registry import ModelRegistry
from .project import Project

Status = Literal["ok", "warn", "fail"]


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    remedy: str | None = None


def _run(cmd: list[str]) -> tuple[bool, str]:
    """Run *cmd*; return (ok, first-line-of-output). Never raises."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return False, f"{cmd[0]} not found on PATH"
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    out = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, (out[0] if out else "")


def check_python() -> Check:
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 11):
        return Check("Python", "ok", version)
    return Check(
        "Python", "fail", f"{version} (need >= 3.11)",
        remedy="Install Python 3.11+ and re-create your virtual environment.",
    )


def check_git() -> Check:
    ok, detail = _run(["git", "--version"])
    if ok:
        return Check("Git", "ok", detail)
    return Check(
        "Git", "fail", detail,
        remedy="Install Git and ensure it is on PATH: https://git-scm.com/downloads",
    )


def check_ripgrep() -> Check:
    ok, detail = _run(["rg", "--version"])
    if ok:
        return Check("ripgrep", "ok", detail)
    return Check(
        "ripgrep", "warn", "rg not found on PATH",
        remedy="Install ripgrep for fast search: https://github.com/BurntSushi/ripgrep",
    )


def check_sqlite() -> Check:
    try:
        conn = sqlite3.connect(":memory:")
        version = conn.execute("select sqlite_version()").fetchone()[0]
        conn.close()
        return Check("SQLite", "ok", f"sqlite {version} (stdlib)")
    except sqlite3.Error as exc:  # pragma: no cover - stdlib should always work
        return Check("SQLite", "fail", str(exc))


def check_ollama_cli() -> Check:
    ok, detail = _run(["ollama", "--version"])
    if ok:
        return Check("Ollama (client)", "ok", detail)
    return Check(
        "Ollama (client)", "fail", detail,
        remedy="Install Ollama: https://ollama.com/download",
    )


def check_ollama_connection(provider: ModelProvider) -> Check:
    health = provider.health()
    if health.ok:
        return Check("Ollama (daemon)", "ok", f"{health.detail} [{health.host}]")
    return Check(
        "Ollama (daemon)", "fail", f"{health.detail} [{health.host}]",
        remedy="Start the daemon:\n  ollama serve\n(or launch the Ollama desktop app)",
    )


def _find_nvidia_smi() -> str | None:
    """Locate nvidia-smi on PATH or common Windows install locations."""
    found = shutil.which("nvidia-smi")
    if found:
        return found
    candidates = [
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
        Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def check_gpu() -> Check:
    """Best-effort GPU detection. Absence is a WARN, never a failure."""
    smi = _find_nvidia_smi()
    if smi is None:
        return Check(
            "GPU (NVIDIA)", "warn", "nvidia-smi not found; GPU acceleration unknown",
            remedy="If you have an NVIDIA GPU, install its driver so nvidia-smi is available.",
        )
    try:
        proc = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("GPU (NVIDIA)", "warn", f"nvidia-smi failed: {exc}")
    line = (proc.stdout or "").strip().splitlines()
    if proc.returncode == 0 and line:
        return Check("GPU (NVIDIA)", "ok", line[0].strip())
    return Check("GPU (NVIDIA)", "warn", "No NVIDIA GPU reported")


def check_configured_models(registry: ModelRegistry) -> Check:
    roles = registry.all_roles()
    configured = {r: m for r, m in roles.items() if m}
    unset = [r for r, m in roles.items() if not m]
    if not configured:
        return Check(
            "Models (roles)", "warn", "No roles configured",
            remedy="Pull a model, then assign a role:\n"
                   "  ollama pull <model>\n  cle model use coding <model>",
        )
    detail = ", ".join(f"{r}={m}" for r, m in configured.items())
    if unset:
        detail += f"  (unset: {', '.join(unset)})"
        return Check("Models (roles)", "warn", detail)
    return Check("Models (roles)", "ok", detail)


def check_project(project: Project, config: Config) -> Check:
    if project.is_initialized:
        return Check("Project config", "ok", f"initialized at {project.root}")
    return Check(
        "Project config", "warn", f"not initialized ({project.root})",
        remedy="Initialize a CLE project here:\n  cle init",
    )


def run_all(
    *,
    config: Config,
    project: Project,
    provider: ModelProvider,
    registry: ModelRegistry,
) -> list[Check]:
    """Run every doctor check and return the results in display order."""
    return [
        check_python(),
        check_git(),
        check_ripgrep(),
        check_sqlite(),
        check_ollama_cli(),
        check_ollama_connection(provider),
        check_gpu(),
        check_configured_models(registry),
        check_project(project, config),
    ]
