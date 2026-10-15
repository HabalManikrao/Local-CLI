"""Dynamic multi-model orchestration: routing, ensemble, fallback, retries."""

from __future__ import annotations

import pytest

from cle.cli import commands
from cle.config import init_project_config, load_config, set_project_value
from cle.errors import ConfigError, ProviderError
from cle.models.base import GenerateResult, Health, ModelInfo, ModelProvider
from cle.models.orchestrator import (
    OrchestrationSettings,
    Orchestrator,
    build_profiles,
    classify_complexity,
)
from cle.models.registry import ModelRegistry
from cle.models.router import ModelRouter
from tests.conftest import make_context

# -- a controllable provider ------------------------------------------------

class ScriptedProvider(ModelProvider):
    """Records generate() calls; can fail or flake specific models."""

    def __init__(self, installed=None, fail=(), flake=None):
        self.installed = installed or []        # list[ModelInfo]
        self.fail = set(fail)                   # models that always fail
        self.flake = dict(flake or {})          # model -> remaining failures then ok
        self.generate_calls: list[str] = []

    def health(self):
        return Health(ok=True, detail="ok", host="fake")

    def list_models(self):
        return list(self.installed)

    def generate(self, model, prompt, *, system=None):
        self.generate_calls.append(model)
        if model in self.fail:
            raise ProviderError(f"{model} unavailable")
        if self.flake.get(model, 0) > 0:
            self.flake[model] -= 1
            raise ProviderError(f"{model} transient")
        return GenerateResult(text=f"[{model}] answer", model=model)

    def chat(self, model, messages):
        return GenerateResult(text=f"[{model}] chat", model=model)

    def stream(self, model, messages):
        yield f"[{model}] "
        yield "streamed"

    def embed(self, model, text):
        return [0.0]


def _models(fast="m-fast", coding="m-code", reasoning="m-reason", embedding="m-embed"):
    return {"fast": fast, "coding": coding, "reasoning": reasoning, "embedding": embedding}


def _orch(tmp_path, provider, models, **cfg):
    init_project_config(tmp_path)
    for role, m in models.items():
        set_project_value(tmp_path, f"models.{role}", m)
    for k, v in cfg.items():
        set_project_value(tmp_path, k.replace("__", "."), v)
    config = load_config(tmp_path)
    reg = ModelRegistry(config)
    return Orchestrator(provider, ModelRouter(config, reg), reg, config)


def _installed(*pairs):
    # pairs: (name, param_size)
    return [ModelInfo(name=n, parameter_size=p) for n, p in pairs]


# -- settings & classification ----------------------------------------------

def test_settings_defaults_when_missing():
    class Empty:
        def get(self, k, d=None):
            return None
    s = OrchestrationSettings.from_config(Empty())
    assert s.enabled is True and s.strategy == "adaptive"
    assert s.max_models_per_task == 3 and s.ensemble_count == 3
    assert s.priority == "balanced" and s.fallback_enabled is True


def test_classify_complexity():
    assert classify_complexity("simple_question", "hi") == "simple"
    assert classify_complexity("code_generation", "x") == "complex"
    assert classify_complexity("simple_question", "please refactor the auth module") == "complex"
    assert classify_complexity("simple_question", "x" * 300) == "moderate"


def test_build_profiles_discovers_capabilities_and_speed(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B")))
    orch = _orch(tmp_path, prov, _models())
    profs = build_profiles(orch.registry, orch.config, prov)
    assert profs["m-code"].can("coding")
    assert profs["m-reason"].can("reasoning")
    assert profs["m-fast"].speed_tier == "fast"       # 1B / fast role
    assert profs["m-reason"].speed_tier == "medium"   # 8B (not >=13)
    assert not profs["m-embed"].can("coding")         # embedding-only


# -- routing ----------------------------------------------------------------

def test_route_defaults_to_role_model(tmp_path):
    orch = _orch(tmp_path, ScriptedProvider(), _models())
    d = orch.route("simple_question", "hello")
    assert d.strategy == "single" and d.models == ["m-fast"]


def test_route_explicit_override_wins(tmp_path):
    orch = _orch(tmp_path, ScriptedProvider(), _models())
    d = orch.route("simple_question", "hello", model_override="whatever:7b")
    assert d.models == ["whatever:7b"] and "override" in d.reason


def test_route_escalates_complex_tasks(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B"), ("m-code", "8B")))
    orch = _orch(tmp_path, prov, _models())
    d = orch.route("simple_question", "please refactor and redesign the whole module")
    assert d.strategy == "single"
    assert d.models[0] != "m-fast"          # escalated away from the fast base
    assert "escalated" in d.reason


def test_route_ensemble_when_requested(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B"), ("m-code", "8B")))
    orch = _orch(tmp_path, prov, _models())
    d = orch.route("simple_question", "compare these", ensemble=True)
    assert d.strategy == "ensemble" and len(d.models) >= 2


def test_route_priority_speed_picks_fastest(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B")))
    orch = _orch(tmp_path, prov, _models(), orchestration__preferences__priority="speed")
    d = orch.route("architecture", "design a system")
    assert d.models == ["m-fast"] and "speed" in d.reason


# -- execution: single, fallback, retries -----------------------------------

def test_run_single_success(tmp_path):
    prov = ScriptedProvider()
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "hi")
    assert res.text == "[m-fast] answer"
    assert prov.generate_calls == ["m-fast"]


def test_run_single_falls_back_on_failure(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B")), fail=["m-fast"])
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "hi")
    assert res.text.startswith("[m-")           # fell back to another model
    assert any(not r.ok for r in res.runs) and any(r.ok for r in res.runs)


def test_run_single_retries_transient(tmp_path):
    prov = ScriptedProvider(flake={"m-fast": 1})   # fails once, then succeeds
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "hi")
    assert res.text == "[m-fast] answer"
    assert prov.generate_calls == ["m-fast", "m-fast"]   # retried


def test_run_all_fail_raises(tmp_path):
    prov = ScriptedProvider(
        installed=_installed(("m-fast", "1B"), ("m-reason", "8B")),
        fail=["m-fast", "m-reason", "m-code", "m-embed"],
    )
    orch = _orch(tmp_path, prov, _models())
    with pytest.raises(ProviderError):
        orch.run_text("simple_question", "hi")


# -- execution: ensemble ----------------------------------------------------

def test_ensemble_synthesises_from_multiple(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B"), ("m-code", "8B")))
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "compare approaches", ensemble=True)
    assert res.decision.strategy == "ensemble"
    assert len([r for r in res.runs if r.ok]) >= 2      # several models answered
    # synthesis ran on a strong model (an extra generate beyond the members)
    assert len(prov.generate_calls) > len(res.runs)


def test_ensemble_tolerates_partial_failure(tmp_path):
    prov = ScriptedProvider(
        installed=_installed(("m-fast", "1B"), ("m-reason", "8B"), ("m-code", "8B")),
        fail=["m-code"],
    )
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "compare approaches", ensemble=True)
    assert any(not r.ok for r in res.runs)      # one failed
    assert res.text                              # still produced an answer


# -- CLI integration --------------------------------------------------------

def test_cmd_ask_ensemble_integration(tmp_path, capsys):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B"), ("m-code", "8B")))
    ctx = make_context(tmp_path, provider=prov, models=_models())
    code = commands.cmd_ask(ctx, "compare these two approaches", None, None, True)
    assert code == 0
    assert prov.generate_calls                  # ensemble actually invoked models
    assert capsys.readouterr().out.strip()      # a synthesised answer was printed


def test_cmd_ask_model_override_streams(tmp_path, capsys):
    prov = ScriptedProvider()
    ctx = make_context(tmp_path, provider=prov, models=_models())
    code = commands.cmd_ask(ctx, "hi", None, "special:7b", False)
    assert code == 0
    assert "special:7b" in capsys.readouterr().out   # streamed from the override


def test_cmd_config_show(tmp_path, capsys):
    ctx = make_context(tmp_path, provider=ScriptedProvider(), models=_models())
    assert commands.cmd_config_show(ctx) == 0
    assert "orchestration" in capsys.readouterr().out


# -- Phase 14: config validation --------------------------------------------

def test_config_validation_rejects_bad_strategy():
    s = OrchestrationSettings(strategy="magic")
    with pytest.raises(ConfigError):
        s.validate()


def test_config_validation_rejects_bad_priority_and_limits():
    with pytest.raises(ConfigError):
        OrchestrationSettings(priority="fastest").validate()
    with pytest.raises(ConfigError):
        OrchestrationSettings(max_parallel_models=0).validate()
    with pytest.raises(ConfigError):
        OrchestrationSettings(timeout_seconds=0).validate()


def test_from_config_raises_on_invalid(tmp_path):
    init_project_config(tmp_path)
    set_project_value(tmp_path, "orchestration.strategy", "bogus")
    config = load_config(tmp_path)
    with pytest.raises(ConfigError):
        OrchestrationSettings.from_config(config)


# -- Phase 14: override never silently falls back ---------------------------

def test_override_does_not_fall_back(tmp_path):
    prov = ScriptedProvider(
        installed=_installed(("m-fast", "1B"), ("m-reason", "8B")),
        fail=["badmodel"],
    )
    orch = _orch(tmp_path, prov, _models())
    with pytest.raises(ProviderError):
        orch.run_text("simple_question", "hi", model_override="badmodel")
    # Only the override was tried (with retries) — never a different model.
    assert set(prov.generate_calls) == {"badmodel"}


def test_override_decision_flags(tmp_path):
    orch = _orch(tmp_path, ScriptedProvider(), _models())
    d = orch.route("simple_question", "hi", model_override="x:7b")
    assert d.is_override is True and "fallback disabled" in " ".join(d.notes)


# -- Phase 14: status taxonomy + timing/attempts ----------------------------

def test_status_complete_on_clean_single(tmp_path):
    orch = _orch(tmp_path, ScriptedProvider(), _models())
    res = orch.run_text("simple_question", "hi")
    assert res.status == "complete_success"
    assert res.duration_s >= 0.0 and res.runs[0].attempts == 1


def test_status_fallback_when_primary_fails(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B")), fail=["m-fast"])
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "hi")
    assert res.status == "fallback_success"


def test_status_partial_on_ensemble_member_failure(tmp_path):
    prov = ScriptedProvider(
        installed=_installed(("m-fast", "1B"), ("m-reason", "8B"), ("m-code", "8B")),
        fail=["m-code"],
    )
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "compare", ensemble=True)
    assert res.status == "partial_success"


def test_run_records_retry_attempts(tmp_path):
    prov = ScriptedProvider(flake={"m-fast": 1})
    orch = _orch(tmp_path, prov, _models())
    res = orch.run_text("simple_question", "hi")
    assert res.runs[0].attempts == 2       # one retry recorded


# -- Phase 14: deterministic routing ----------------------------------------

def test_routing_is_deterministic(tmp_path):
    prov = ScriptedProvider(installed=_installed(("m-fast", "1B"), ("m-reason", "8B"), ("m-code", "8B")))
    orch = _orch(tmp_path, prov, _models())
    d1 = orch.route("simple_question", "please refactor the whole thing")
    d2 = orch.route("simple_question", "please refactor the whole thing")
    assert (d1.strategy, d1.models, d1.escalated) == (d2.strategy, d2.models, d2.escalated)


# -- Phase 14: code review is independent-aware and text-only ---------------

class _Plan:
    goal = "add validation"


def test_code_review_reports_non_independence(tmp_path, capsys):
    # coding and reasoning point at the SAME model -> review is not independent.
    prov = ScriptedProvider()
    ctx = make_context(tmp_path, provider=prov,
                       models={"fast": "m-fast", "coding": "same:8b",
                               "reasoning": "same:8b", "embedding": "m-embed"})
    before = set(tmp_path.rglob("*"))
    commands._render_code_review(ctx, "req", _Plan(), "some diff", coder_model="same:8b")
    out = capsys.readouterr().out
    assert "not an independent review" in out
    # The reviewer only produced text — it must not have created/modified files.
    assert set(tmp_path.rglob("*")) == before


def test_code_review_independent_when_models_differ(tmp_path, capsys):
    prov = ScriptedProvider()
    ctx = make_context(tmp_path, provider=prov, models=_models())  # coding != reasoning
    commands._render_code_review(ctx, "req", _Plan(), "some diff", coder_model="m-code")
    out = capsys.readouterr().out
    assert "not an independent review" not in out
