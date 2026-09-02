from cle import diagnostics
from cle.config import load_config
from cle.models.registry import ModelRegistry
from cle.project import detect_project

from tests.conftest import FakeProvider


def test_check_python_ok():
    c = diagnostics.check_python()
    assert c.status == "ok"


def test_check_sqlite_ok():
    c = diagnostics.check_sqlite()
    assert c.status == "ok"
    assert "sqlite" in c.detail.lower()


def test_check_gpu_warns_when_smi_absent(monkeypatch):
    monkeypatch.setattr(diagnostics, "_find_nvidia_smi", lambda: None)
    c = diagnostics.check_gpu()
    assert c.status == "warn"
    assert c.remedy is not None


def test_check_ollama_connection_reports_health():
    ok = diagnostics.check_ollama_connection(FakeProvider(healthy=True))
    assert ok.status == "ok"
    down = diagnostics.check_ollama_connection(FakeProvider(healthy=False))
    assert down.status == "fail"
    assert "ollama serve" in (down.remedy or "")


def test_check_configured_models_warn_when_unset(tmp_path):
    cfg = load_config(None)
    reg = ModelRegistry(cfg)
    c = diagnostics.check_configured_models(reg)
    assert c.status == "warn"


def test_check_project_warns_when_uninitialized(tmp_path):
    cfg = load_config(None)
    project = detect_project(tmp_path)
    c = diagnostics.check_project(project, cfg)
    assert c.status == "warn"
    assert "cle init" in (c.remedy or "")


def test_run_all_returns_checks(tmp_path):
    cfg = load_config(None)
    project = detect_project(tmp_path)
    checks = diagnostics.run_all(
        config=cfg, project=project,
        provider=FakeProvider(healthy=True),
        registry=ModelRegistry(cfg),
    )
    names = {c.name for c in checks}
    assert "Python" in names and "Ollama (daemon)" in names and "GPU (NVIDIA)" in names
