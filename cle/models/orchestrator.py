"""Dynamic multi-model orchestration.

Sits on top of the existing seams (``ModelProvider`` / ``ModelRouter`` /
``ModelRegistry``) and decides *which* model(s) handle a task and *how*:

- **single**   — one suitable model (the default; preserves legacy behaviour),
- **ensemble** — several models answer independently, then a synthesiser
  reconciles them,
- **sequential/review** — one model produces, another reviews (used by the
  coding workflow).

Design rules honoured here:

- No model names are hard-coded. Capabilities are *discovered* from the role
  assignments in config (the model wired to the ``coding`` role has the
  ``coding`` capability, etc.) plus optional ``orchestration.models`` overrides.
- Role-based routing remains the fallback: ``route()`` returns the intent's
  configured role model unless an override / flag / escalation applies.
- Everything is bounded (max models, retries, timeout) and reports *why* a
  decision was made, for observability.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

from ..config import Config
from ..errors import CleError, ProviderError
from .base import GenerateResult, ModelProvider
from .registry import ROLES, ModelRegistry
from .router import ModelRouter

# Which capability each role implies. A model may hold several roles and so
# gain several capabilities. Kept here (not keyed by model name) so nothing is
# hard-coded to a particular model.
_ROLE_CAPABILITY = {
    "fast": "chat",
    "coding": "coding",
    "reasoning": "reasoning",
    "embedding": "embedding",
}
_COMPLEXITY_KEYWORDS = (
    "refactor", "architecture", "debug", "why", "design", "optimize",
    "concurrency", "race condition", "security", "redesign", "trade-off",
)


@dataclass(frozen=True)
class OrchestrationSettings:
    """Parsed ``orchestration:`` config, with safe defaults when fields absent."""

    enabled: bool = True
    strategy: str = "adaptive"          # adaptive | single
    max_models_per_task: int = 3
    max_parallel_models: int = 3
    timeout_seconds: int = 120
    max_retries: int = 2
    automatic_routing: bool = True
    escalation_enabled: bool = True
    collaboration_enabled: bool = True
    review_code_changes: bool = True
    ensemble_enabled: bool = True
    ensemble_count: int = 3
    priority: str = "balanced"          # speed | balanced | quality
    fallback_enabled: bool = True

    @classmethod
    def from_config(cls, config: Config) -> OrchestrationSettings:
        def g(path: str, default):
            val = config.get(f"orchestration.{path}")
            return default if val is None else val

        return cls(
            enabled=bool(g("enabled", True)),
            strategy=str(g("strategy", "adaptive")),
            max_models_per_task=int(g("limits.max_models_per_task", 3)),
            max_parallel_models=int(g("limits.max_parallel_models", 3)),
            timeout_seconds=int(g("limits.timeout_seconds", 120)),
            max_retries=int(g("limits.max_retries", 2)),
            automatic_routing=bool(g("routing.automatic", True)),
            escalation_enabled=bool(g("routing.escalation_enabled", True)),
            collaboration_enabled=bool(g("collaboration.enabled", True)),
            review_code_changes=bool(g("collaboration.review_code_changes", True)),
            ensemble_enabled=bool(g("ensemble.enabled", True)),
            ensemble_count=int(g("ensemble.default_model_count", 3)),
            priority=str(g("preferences.priority", "balanced")),
            fallback_enabled=bool(g("fallback.enabled", True)),
        )


@dataclass(frozen=True)
class ModelProfile:
    """What a configured model can do (discovered, not hard-coded)."""

    name: str
    roles: frozenset[str]
    capabilities: frozenset[str]
    speed_tier: str                     # fast | medium | slow (best-effort)
    installed: bool = True

    def can(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass
class ModelRun:
    """Outcome of invoking one model once (for diagnostics)."""

    model: str
    ok: bool
    text: str = ""
    error: str = ""
    role: str = ""


@dataclass
class RoutingDecision:
    """Why the orchestrator chose what it chose (observability)."""

    strategy: str                       # single | ensemble | sequential
    models: list[str]
    reason: str
    complexity: str
    intent: str


@dataclass
class OrchestrationResult:
    text: str
    decision: RoutingDecision
    runs: list[ModelRun] = field(default_factory=list)


def classify_complexity(intent: str, prompt: str) -> str:
    """Heuristic task-complexity estimate: simple | moderate | complex."""
    p = (prompt or "").lower()
    if intent in ("code_generation", "architecture", "debugging"):
        return "complex"
    if len(p) > 600 or any(k in p for k in _COMPLEXITY_KEYWORDS):
        return "complex"
    if len(p) > 200:
        return "moderate"
    return "simple"


def build_profiles(
    registry: ModelRegistry,
    config: Config,
    provider: ModelProvider | None = None,
) -> dict[str, ModelProfile]:
    """Build model->profile from role assignments (+ optional provider sizes).

    Capabilities come from which roles a model fills; speed is inferred from the
    provider's reported parameter size when available (``1B`` → fast), else from
    the ``fast`` role. Nothing is keyed on a specific model name.
    """
    roles_for: dict[str, set[str]] = {}
    for role in ROLES:
        model = config.get(f"models.{role}", "") or ""
        if model:
            roles_for.setdefault(model, set()).add(role)

    # Best-effort size lookup for speed tiers; degrade silently if daemon down.
    sizes: dict[str, float] = {}
    installed: set[str] = set()
    if provider is not None:
        try:
            for m in provider.list_models():
                installed.add(m.name)
                sizes[m.name] = _parse_params_billions(m.parameter_size)
        except CleError:
            pass

    profiles: dict[str, ModelProfile] = {}
    for model, roles in roles_for.items():
        caps = {_ROLE_CAPABILITY[r] for r in roles if r in _ROLE_CAPABILITY}
        caps.add("chat")  # any generative model can chat
        b = sizes.get(model) or sizes.get(f"{model.split(':', 1)[0]}:latest", 0.0)
        if "fast" in roles or (b and b <= 2.0):
            tier = "fast"
        elif b and b >= 13.0:
            tier = "slow"
        else:
            tier = "medium"
        profiles[model] = ModelProfile(
            name=model,
            roles=frozenset(roles),
            capabilities=frozenset(caps),
            speed_tier=tier,
            installed=(model in installed) if provider is not None else True,
        )
    return profiles


def _parse_params_billions(param_size: str | None) -> float:
    if not param_size:
        return 0.0
    s = param_size.strip().upper().rstrip("B")
    try:
        if s.endswith("M"):
            return float(s[:-1]) / 1000.0
        return float(s)
    except ValueError:
        return 0.0


class Orchestrator:
    """Chooses and coordinates models for a task."""

    def __init__(
        self,
        provider: ModelProvider,
        router: ModelRouter,
        registry: ModelRegistry,
        config: Config,
    ) -> None:
        self.provider = provider
        self.router = router
        self.registry = registry
        self.config = config
        self.settings = OrchestrationSettings.from_config(config)
        # Built lazily: capability/health info needs a provider round-trip, so
        # we only pay it when routing actually needs it (escalation / ensemble /
        # fallback), never on the simple single-model default path.
        self._profiles_cache: dict[str, ModelProfile] | None = None

    def _profiles(self) -> dict[str, ModelProfile]:
        if self._profiles_cache is None:
            self._profiles_cache = build_profiles(self.registry, self.config, self.provider)
        return self._profiles_cache

    # -- routing ------------------------------------------------------------

    def route(
        self,
        intent: str,
        prompt: str,
        *,
        model_override: str | None = None,
        ensemble: bool = False,
    ) -> RoutingDecision:
        """Decide strategy + model(s) for a task, explaining why."""
        complexity = classify_complexity(intent, prompt)

        # 1. Explicit override always wins.
        if model_override:
            return RoutingDecision(
                strategy="single", models=[model_override],
                reason=f"explicit --model override ({model_override})",
                complexity=complexity, intent=intent,
            )

        base = self._role_model(intent)

        # 2. Ensemble requested (and enabled).
        if ensemble and self.settings.ensemble_enabled:
            models = self._ensemble_members(base)
            if len(models) >= 2:
                return RoutingDecision(
                    strategy="ensemble", models=models,
                    reason=f"ensemble of {len(models)} models requested",
                    complexity=complexity, intent=intent,
                )
            # Not enough distinct models to ensemble → fall through to single.

        # 3. Adaptive escalation: simple tasks stay fast; complex ones escalate
        #    to the strongest available generative model.
        chosen, why = base, f"role '{self.router.role_for_intent(intent)}' for intent"
        if (
            self.settings.enabled
            and self.settings.automatic_routing
            and self.settings.strategy == "adaptive"
        ):
            if self.settings.priority == "speed":
                fast = self._fastest_generative()
                if fast:
                    chosen, why = fast, "priority=speed → fastest model"
            elif complexity == "complex" and self.settings.escalation_enabled:
                strong = self._strongest_generative()
                if strong and strong != base:
                    chosen, why = strong, f"complex task → escalated to {strong}"
            elif self.settings.priority == "quality":
                strong = self._strongest_generative()
                if strong:
                    chosen, why = strong, "priority=quality → strongest model"

        return RoutingDecision(
            strategy="single", models=[chosen or base], reason=why,
            complexity=complexity, intent=intent,
        )

    # -- execution ----------------------------------------------------------

    def run_text(
        self,
        intent: str,
        prompt: str,
        *,
        system: str | None = None,
        model_override: str | None = None,
        ensemble: bool = False,
    ) -> OrchestrationResult:
        """Route then execute, returning text + full decision/diagnostics."""
        decision = self.route(
            intent, prompt, model_override=model_override, ensemble=ensemble
        )
        if decision.strategy == "ensemble":
            return self._run_ensemble(decision, prompt, system)
        text, runs = self._run_single_with_fallback(decision.models[0], prompt, system)
        return OrchestrationResult(text=text, decision=decision, runs=runs)

    def _run_single_with_fallback(
        self, model: str, prompt: str, system: str | None
    ) -> tuple[str, list[ModelRun]]:
        runs: list[ModelRun] = []
        candidates = [model] + self._fallback_chain(model)
        last_err: CleError | None = None
        for cand in candidates:
            try:
                res = self._generate_with_retry(cand, prompt, system)
                runs.append(ModelRun(model=cand, ok=True, text=res.text))
                return res.text, runs
            except CleError as exc:
                runs.append(ModelRun(model=cand, ok=False, error=exc.message))
                last_err = exc
                if not self.settings.fallback_enabled:
                    break
        raise last_err or ProviderError("No model could handle the task.")

    def _run_ensemble(
        self, decision: RoutingDecision, prompt: str, system: str | None
    ) -> OrchestrationResult:
        models = decision.models[: self.settings.max_models_per_task]
        runs = self._parallel_generate(models, prompt, system)
        ok = [r for r in runs if r.ok]
        if not ok:
            raise ProviderError(
                "All ensemble models failed.",
                remedy="Check the Ollama daemon and the configured models.",
            )
        if len(ok) == 1:
            return OrchestrationResult(text=ok[0].text, decision=decision, runs=runs)
        synth = self._synthesise([(r.model, r.text) for r in ok], prompt)
        return OrchestrationResult(text=synth, decision=decision, runs=runs)

    def _parallel_generate(
        self, models: list[str], prompt: str, system: str | None
    ) -> list[ModelRun]:
        workers = max(1, min(self.settings.max_parallel_models, len(models)))
        runs: list[ModelRun] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._generate_with_retry, m, prompt, system): m
                for m in models
            }
            for fut, model in futures.items():
                try:
                    res = fut.result(timeout=self.settings.timeout_seconds)
                    runs.append(ModelRun(model=model, ok=True, text=res.text))
                except FuturesTimeout:
                    runs.append(ModelRun(model=model, ok=False, error="timed out"))
                except CleError as exc:
                    runs.append(ModelRun(model=model, ok=False, error=exc.message))
                except Exception as exc:  # defensive: never let a worker escape
                    runs.append(ModelRun(model=model, ok=False, error=str(exc)))
        return runs

    def _synthesise(self, answers: list[tuple[str, str]], question: str) -> str:
        """Reconcile several independent answers with the strongest model."""
        joined = "\n\n".join(
            f"--- Answer from model {i + 1} ({name}) ---\n{text}"
            for i, (name, text) in enumerate(answers)
        )
        model = self._strongest_generative() or answers[0][0]
        system = (
            "You are a careful reviewer. Several models answered the same "
            "question independently. Compare them, note where they agree and "
            "disagree, discard anything unsupported, and produce the single best "
            "answer. Be concise."
        )
        prompt = (
            f"Question:\n{question}\n\n{joined}\n\n"
            "Give the best synthesised answer, and one line on any disagreement."
        )
        try:
            return self._generate_with_retry(model, prompt, system).text
        except CleError:
            # Synthesis failed — fall back to the first successful answer.
            return answers[0][1]

    # -- model invocation helpers ------------------------------------------

    def _generate_with_retry(
        self, model: str, prompt: str, system: str | None
    ) -> GenerateResult:
        attempts = max(1, self.settings.max_retries + 1)
        last: CleError | None = None
        for _ in range(attempts):
            try:
                return self.provider.generate(model, prompt, system=system)
            except CleError as exc:
                last = exc
        raise last or ProviderError(f"Model '{model}' failed.")

    # -- selection helpers --------------------------------------------------

    def _role_model(self, intent: str) -> str:
        """The role-based model for an intent (legacy behaviour / fallback)."""
        return self.router.model_for_intent(intent)

    def _generative_profiles(self) -> list[ModelProfile]:
        profs = [
            p for p in self._profiles().values()
            if p.installed and p.capabilities - {"embedding"}
        ]
        return profs

    def _strongest_generative(self) -> str | None:
        order = {"slow": 0, "medium": 1, "fast": 2}
        profs = sorted(self._generative_profiles(), key=lambda p: order.get(p.speed_tier, 1))
        # Prefer reasoning/coding-capable, then slowest (usually largest).
        ranked = sorted(
            profs,
            key=lambda p: (
                -(("reasoning" in p.capabilities) + ("coding" in p.capabilities)),
                order.get(p.speed_tier, 1),
            ),
        )
        return ranked[0].name if ranked else None

    def _fastest_generative(self) -> str | None:
        order = {"fast": 0, "medium": 1, "slow": 2}
        profs = sorted(self._generative_profiles(), key=lambda p: order.get(p.speed_tier, 1))
        return profs[0].name if profs else None

    def _ensemble_members(self, base: str) -> list[str]:
        """Distinct generative models for an ensemble, base first."""
        members = [base]
        for p in self._generative_profiles():
            if p.name not in members:
                members.append(p.name)
            if len(members) >= self.settings.ensemble_count:
                break
        return members

    def _fallback_chain(self, model: str) -> list[str]:
        if not self.settings.fallback_enabled:
            return []
        return [p.name for p in self._generative_profiles() if p.name != model]
