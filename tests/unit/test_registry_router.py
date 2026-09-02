import pytest

from cle.config import Config
from cle.errors import ModelNotConfiguredError
from cle.models.registry import ModelRegistry
from cle.models.router import ModelRouter


def _cfg(models=None, routing=None):
    data = {
        "models": {"fast": "", "coding": "", "reasoning": "", "embedding": ""},
        "routing": {
            "simple_question": "fast",
            "code_generation": "coding",
            "debugging": "reasoning",
            "default": "fast",
        },
    }
    if models:
        data["models"].update(models)
    if routing:
        data["routing"].update(routing)
    return Config(data, None)


def test_registry_configured_only_returns_set_roles():
    reg = ModelRegistry(_cfg({"fast": "f", "coding": "c"}))
    assert reg.configured() == {"fast": "f", "coding": "c"}


def test_registry_resolve_returns_model():
    reg = ModelRegistry(_cfg({"coding": "codellama"}))
    assert reg.resolve("coding") == "codellama"


def test_registry_resolve_unset_raises_actionable():
    reg = ModelRegistry(_cfg())
    with pytest.raises(ModelNotConfiguredError) as exc:
        reg.resolve("coding")
    assert exc.value.remedy and "cle model use coding" in exc.value.remedy


def test_registry_resolve_unknown_role_raises():
    reg = ModelRegistry(_cfg())
    with pytest.raises(ModelNotConfiguredError):
        reg.resolve("nonsense")


def test_router_intent_to_role():
    cfg = _cfg({"reasoning": "r"})
    router = ModelRouter(cfg, ModelRegistry(cfg))
    assert router.role_for_intent("debugging") == "reasoning"


def test_router_unknown_intent_falls_back_to_default():
    cfg = _cfg({"fast": "f"})
    router = ModelRouter(cfg, ModelRegistry(cfg))
    assert router.role_for_intent("something_new") == "fast"
    assert router.model_for_intent("something_new") == "f"


def test_router_resolves_intent_to_model():
    cfg = _cfg({"coding": "cc"})
    router = ModelRouter(cfg, ModelRegistry(cfg))
    assert router.model_for_intent("code_generation") == "cc"
