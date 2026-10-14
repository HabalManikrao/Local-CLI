"""Typer application — wires CLI commands to their implementations.

The app stays thin: it parses arguments, builds an :class:`AppContext`, and
delegates to ``commands.py``. Structured :class:`CleError` exceptions are caught
here and rendered once, so individual commands don't repeat error plumbing.
"""

from __future__ import annotations

import logging

import typer

from .. import __version__
from ..errors import CleError
from ..runtime import AppContext, build_context
from . import commands, ui

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="cle",
    help="Local CLI Engineering — offline-first, Ollama-powered engineering agent.",
    no_args_is_help=True,
    add_completion=False,
)

# `cle model ...` subcommand group.
model_app = typer.Typer(help="Inspect and configure model roles.")
app.add_typer(model_app, name="model")

# `cle memory ...` subcommand group.
memory_app = typer.Typer(
    help="Project-scoped memory (decisions, issues, conventions, commands).",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(memory_app, name="memory")

# `cle java ...` and `cle winium ...` analysis groups.
java_app = typer.Typer(help="Java code intelligence.")
app.add_typer(java_app, name="java")
winium_app = typer.Typer(help="Winium automation-framework intelligence.")
app.add_typer(winium_app, name="winium")


def _version_callback(value: bool) -> None:
    if value:
        ui.console.print(f"cle {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose (DEBUG) logging."),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    # Stash flags; context is built lazily per command so `--help` stays cheap.
    ctx.obj = {"verbose": verbose}


def _ctx(ctx: typer.Context) -> AppContext:
    return build_context(verbose=bool(ctx.obj and ctx.obj.get("verbose")))


def _run(fn, *args) -> None:
    """Execute a command function, rendering CleError and mapping exit codes."""
    try:
        code = fn(*args)
    except CleError as exc:
        ui.print_error(exc)
        raise typer.Exit(code=1) from None
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        ui.err_console.print("\n[dim]interrupted[/dim]")
        raise typer.Exit(code=130) from None
    except Exception as exc:  # last-resort guard: never dump a raw traceback
        # The full traceback is logged (visible with --verbose); the user sees a
        # structured message instead of a Python stack trace.
        logger.exception("Unhandled error in %s", getattr(fn, "__name__", fn))
        ui.print_error(CleError(
            f"Unexpected error: {exc}",
            remedy=(
                "This is likely a bug. Re-run with --verbose to see the full "
                "trace, then report it."
            ),
        ))
        raise typer.Exit(code=1) from None
    if code:
        raise typer.Exit(code=code)


@app.command()
def init(ctx: typer.Context) -> None:
    """Initialize a CLE project in the current directory."""
    _run(commands.cmd_init, _ctx(ctx))


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Validate the local environment (Python, Git, Ollama, models, ...)."""
    _run(commands.cmd_doctor, _ctx(ctx))


@app.command()
def index(ctx: typer.Context) -> None:
    """Scan the project and build the local code index (files/symbols/imports)."""
    _run(commands.cmd_index, _ctx(ctx))


@app.command()
def status(ctx: typer.Context) -> None:
    """Show project, provider, model-role, and index status."""
    _run(commands.cmd_status, _ctx(ctx))


@app.command()
def models(ctx: typer.Context) -> None:
    """List configured roles and models installed in Ollama."""
    _run(commands.cmd_models, _ctx(ctx))


@app.command()
def search(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="Text or regex to search for."),
    ignore_case: bool = typer.Option(False, "--ignore-case", "-i", help="Case-insensitive."),
    fixed: bool = typer.Option(False, "--fixed", "-F", help="Literal string (no regex)."),
) -> None:
    """Exact text search across the project (ripgrep, with a Python fallback)."""
    _run(commands.cmd_search, _ctx(ctx), pattern, ignore_case, fixed)


@app.command()
def symbol(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Symbol name to look up in the index."),
) -> None:
    """Find a class/interface/method/function/field by name (structural search)."""
    _run(commands.cmd_symbol, _ctx(ctx), name)


@app.command()
def explain(
    ctx: typer.Context,
    file: str = typer.Argument(..., help="Path (relative to project root) to explain."),
) -> None:
    """Explain a source file using the reasoning model and its symbol outline."""
    _run(commands.cmd_explain, _ctx(ctx), file)


@app.command()
def embed(ctx: typer.Context) -> None:
    """Build the local semantic index (embeddings) for semantic search."""
    _run(commands.cmd_embed, _ctx(ctx))


@app.command()
def code(
    ctx: typer.Context,
    request: str = typer.Argument(..., help="What you want changed."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without prompting."),
    no_apply: bool = typer.Option(False, "--no-apply", help="Plan only; don't edit."),
) -> None:
    """Plan and (after approval) apply code changes for a request."""
    _run(commands.cmd_code, _ctx(ctx), request, yes, no_apply)


@app.command()
def ask(ctx: typer.Context, question: str = typer.Argument(..., help="Your question.")) -> None:
    """Ask a one-shot question (routed to the 'fast' model)."""
    _run(commands.cmd_ask, _ctx(ctx), question)


@app.command()
def chat(ctx: typer.Context) -> None:
    """Start an interactive chat session."""
    _run(commands.cmd_chat, _ctx(ctx))


@app.command()
def test(ctx: typer.Context) -> None:
    """Detect the build system and run the project's tests."""
    _run(commands.cmd_test, _ctx(ctx))


@app.command()
def debug(ctx: typer.Context) -> None:
    """Run tests and, if failing, diagnose the root cause (no changes)."""
    _run(commands.cmd_debug, _ctx(ctx))


@app.command(name="fix-tests")
def fix_tests(
    ctx: typer.Context,
    max_iterations: int = typer.Option(None, "--max-iter", help="Iteration cap (default: config)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply fixes without prompting."),
) -> None:
    """Iteratively run tests and propose/apply fixes (bounded loop)."""
    _run(commands.cmd_fix_tests, _ctx(ctx), max_iterations, yes)


@app.command()
def autopilot(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="The engineering task to attempt."),
    max_iterations: int = typer.Option(None, "--max-iter", help="Iteration cap (default: config)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve edits."),
) -> None:
    """Autonomously plan, edit, build, test, and self-repair a task (bounded)."""
    _run(commands.cmd_autopilot, _ctx(ctx), task, max_iterations, yes)


@app.command()
def benchmark(ctx: typer.Context) -> None:
    """Benchmark the configured models/agents on local tasks; store results."""
    _run(commands.cmd_benchmark, _ctx(ctx))


@app.command()
def dashboard(ctx: typer.Context) -> None:
    """Show a status dashboard (project, models, index, memory, git)."""
    _run(commands.cmd_dashboard, _ctx(ctx))


@app.command()
def diff(ctx: typer.Context) -> None:
    """Show the working-tree git diff and status."""
    _run(commands.cmd_diff, _ctx(ctx))


@app.command()
def checkpoint(
    ctx: typer.Context,
    label: str = typer.Argument("manual", help="Label for this checkpoint."),
) -> None:
    """Create a non-destructive snapshot you can roll back to."""
    _run(commands.cmd_checkpoint, _ctx(ctx), label)


@app.command()
def rollback(
    ctx: typer.Context,
    checkpoint_id: int = typer.Argument(None, help="Checkpoint id (default: latest)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Restore tracked files to a previous checkpoint."""
    _run(commands.cmd_rollback, _ctx(ctx), checkpoint_id, yes)


@model_app.command("use")
def model_use(
    ctx: typer.Context,
    role: str = typer.Argument(..., help="Role: fast|coding|reasoning|embedding."),
    model: str = typer.Argument(..., help="Ollama model name to assign."),
) -> None:
    """Assign an Ollama model to a task role."""
    _run(commands.cmd_model_use, _ctx(ctx), role, model)


@model_app.command("list")
def model_list(ctx: typer.Context) -> None:
    """List configured roles and installed models (alias of `cle models`)."""
    _run(commands.cmd_models, _ctx(ctx))


@memory_app.callback()
def memory_main(ctx: typer.Context) -> None:
    """Show a memory summary when `cle memory` is run with no subcommand."""
    if ctx.invoked_subcommand is None:
        _run(commands.cmd_memory, _ctx(ctx))


@memory_app.command("show")
def memory_show(
    ctx: typer.Context,
    kind: str = typer.Argument(None, help="Filter by kind (optional)."),
) -> None:
    """List memory entries (optionally of one kind) and settings."""
    _run(commands.cmd_memory_show, _ctx(ctx), kind)


@memory_app.command("add")
def memory_add(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help="decision|issue|convention|important_file|agent_decision|note"),
    title: str = typer.Argument(..., help="Short title."),
    body: str = typer.Argument(None, help="Optional detail."),
) -> None:
    """Record a memory entry."""
    _run(commands.cmd_memory_add, _ctx(ctx), kind, title, body)


@memory_app.command("set")
def memory_set(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="e.g. build_command, test_command"),
    value: str = typer.Argument(..., help="The value to store."),
) -> None:
    """Set a scalar memory setting (build/test commands, etc.)."""
    _run(commands.cmd_memory_set, _ctx(ctx), key, value)


@memory_app.command("remove")
def memory_remove(
    ctx: typer.Context,
    entry_id: int = typer.Argument(..., help="Entry id to remove."),
) -> None:
    """Remove a memory entry by id."""
    _run(commands.cmd_memory_remove, _ctx(ctx), entry_id)


@memory_app.command("clear")
def memory_clear(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Clear all project memory."""
    _run(commands.cmd_memory_clear, _ctx(ctx), yes)


@java_app.command("analyze")
def java_analyze(ctx: typer.Context) -> None:
    """Analyze Java code for quality issues (evidence-backed; no changes)."""
    _run(commands.cmd_java_analyze, _ctx(ctx))


@winium_app.command("analyze")
def winium_analyze(ctx: typer.Context) -> None:
    """Analyze Winium automation code for smells (evidence-backed; no changes)."""
    _run(commands.cmd_winium_analyze, _ctx(ctx))


if __name__ == "__main__":  # pragma: no cover
    app()
