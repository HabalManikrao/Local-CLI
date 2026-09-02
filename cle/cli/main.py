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


if __name__ == "__main__":  # pragma: no cover
    app()
