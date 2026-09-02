# Development

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Optional extras: `pip install -e ".[semantic]"` (FAISS), `".[parsing]"`
(tree-sitter), `".[tui]"` (Textual).

## Running the tests

```powershell
pytest                 # full suite (offline; no Ollama daemon required)
pytest tests/unit      # fast unit tests
pytest -m integration  # temp git repos, sqlite, ripgrep
pytest -m e2e          # CLI + real pytest subprocess (coding/fix-tests/autopilot)
```

All LLM interaction is faked (`tests/conftest.py::FakeProvider`) or mocked
(`httpx.MockTransport`), so nothing needs a running daemon.

## Layout

- `cle/` — the package (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- `configs/default.yaml` — packaged defaults.
- `docs/` — design docs.
- `tests/{unit,integration,e2e}` — mirrors the layers.

## Conventions

- **Errors** are `CleError` subclasses carrying an actionable `remedy`
  (`cle/errors.py`). Never surface a bare "something went wrong".
- **Commands** live in `cle/cli/commands.py` as functions returning an exit
  code; Typer wiring in `cle/cli/main.py` catches `CleError` centrally.
- **All LLM calls** go through `ModelProvider`; **all writes** through the
  guarded `FileSystem`. Don't bypass these seams.
- **Model output** is printed with `markup=False` (brackets aren't Rich markup).
- Prefer stdlib + the small dependency set (typer/rich/httpx/PyYAML). Justify
  any new dependency; keep the core runnable offline.

## Adding a milestone-style feature

1. Inspect the relevant layer; reuse before adding.
2. Implement behind the existing seams.
3. Add unit + integration tests (offline).
4. Run the full suite green.
5. Update the relevant `docs/*.md`.

## Adding a new agent

Subclass `agents.base.BaseAgent`, reuse the context engine + edit/permission
tools, and follow the plan→approve→guarded-apply pattern (see
[AGENT-ARCHITECTURE.md](AGENT-ARCHITECTURE.md)).

## Adding a benchmark task

Add a `BenchmarkTask` in `cle/benchmark/tasks.py` (declare `required_role` if it
needs a model); it is picked up by `default_suite()` and `cle benchmark`.
