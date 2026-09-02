"""Typer application — wires CLI commands to their implementations.

The app stays thin: it parses arguments, builds an :class:`AppContext`, and
delegates to ``commands.py``. Structured :class:`CleError` exceptions are caught
here and rendered once, so individual commands don't repeat error plumbing.
"""

from __future__ import annotations

import typer

from .. import __version__
from ..errors import CleError
from ..runtime import AppContext, build_context
from . import commands, ui

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
        raise typer.Exit(code=1)
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
def ask(ctx: typer.Context, question: str = typer.Argument(..., help="Your question.")) -> None:
    """Ask a one-shot question (routed to the 'fast' model)."""
    _run(commands.cmd_ask, _ctx(ctx), question)


@app.command()
def chat(ctx: typer.Context) -> None:
    """Start an interactive chat session."""
    _run(commands.cmd_chat, _ctx(ctx))


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


if __name__ == "__main__":  # pragma: no cover
    app()
