"""Command implementations.

Each function takes an :class:`~cle.runtime.AppContext` (plus command args) and
returns an integer exit code. Keeping the logic here (separate from the Typer
wiring in ``main.py``) makes commands directly unit-testable.
"""

from __future__ import annotations

from pathlib import Path

from .. import __version__, diagnostics
from ..config import init_project_config, set_project_value
from ..errors import CleError
from ..models.base import Message
from ..models.registry import ROLES
from ..project import detect_project, git_is_available
from ..runtime import AppContext
from . import ui

_STATUS_RENDER = {"ok": ui.OK, "warn": ui.WARN, "fail": ui.FAIL}


# -- cle init ---------------------------------------------------------------

def cmd_init(ctx: AppContext) -> int:
    root = ctx.project.root
    path = init_project_config(root)
    ui.console.print(f"Initialized CLE project at [bold]{root}[/bold]")
    ui.console.print(f"  config: {path}")

    if not ctx.project.is_git_repo:
        if git_is_available():
            ui.console.print(
                "  [yellow]note[/yellow]: not a git repository. "
                "CLE safety features expect git — run [bold]git init[/bold] "
                "to enable checkpoints and rollback."
            )
        else:
            ui.console.print(
                "  [yellow]note[/yellow]: git was not found on PATH; "
                "install it to enable checkpoints and rollback."
            )
    ctx.audit.event("init", project=str(root), config=str(path))
    ui.console.print("\nNext: [bold]cle doctor[/bold] to validate your environment.")
    return 0


# -- cle doctor -------------------------------------------------------------

def cmd_doctor(ctx: AppContext) -> int:
    checks = diagnostics.run_all(
        config=ctx.config,
        project=ctx.project,
        provider=ctx.provider,
        registry=ctx.registry,
    )
    table = ui.status_table("cle doctor")
    for check in checks:
        table.add_row(check.name, _STATUS_RENDER[check.status], check.detail)
    ui.console.print(table)

    failures = [c for c in checks if c.status == "fail"]
    warnings = [c for c in checks if c.status == "warn"]
    for c in failures + warnings:
        if c.remedy:
            glyph = "[red]FAIL[/red]" if c.status == "fail" else "[yellow]WARN[/yellow]"
            ui.console.print(f"\n{glyph} {c.name}:\n  " + c.remedy.replace("\n", "\n  "))

    ctx.audit.event(
        "doctor",
        failures=[c.name for c in failures],
        warnings=[c.name for c in warnings],
    )
    if failures:
        ui.console.print(
            f"\n[red]{len(failures)} check(s) failed.[/red] "
            "Resolve the items above and re-run [bold]cle doctor[/bold]."
        )
        return 1
    ui.console.print("\n[green]All required checks passed.[/green]")
    return 0


# -- cle status -------------------------------------------------------------

def cmd_status(ctx: AppContext) -> int:
    p = ctx.project
    table = ui.kv_table("cle status")
    table.add_row("CLE version", __version__)
    table.add_row("Project root", str(p.root))
    table.add_row("Initialized", "yes" if p.is_initialized else "no")
    table.add_row("Git repo", "yes" if p.is_git_repo else "no")
    table.add_row("Provider", f"{ctx.config.get('provider.type')} @ "
                              f"{ctx.config.get('provider.host')}")

    roles = ctx.registry.all_roles()
    role_str = ", ".join(f"{r}={m or '—'}" for r, m in roles.items())
    table.add_row("Model roles", role_str)

    # Index status: not built until Milestone 4.
    index_db = p.cle_dir / "index" / "index.db"
    table.add_row("Index", "built" if index_db.exists() else "not indexed")
    ui.console.print(table)
    return 0


# -- cle models -------------------------------------------------------------

def cmd_models(ctx: AppContext) -> int:
    # Configured roles first (always available, offline).
    roles = ctx.registry.all_roles()
    rtable = ui.kv_table("Configured roles")
    for role, model in roles.items():
        rtable.add_row(role, model or "[dim]unset[/dim]")
    ui.console.print(rtable)

    # Installed models require the daemon; degrade gracefully if it's down.
    try:
        installed = ctx.provider.list_models()
    except CleError as exc:
        ui.print_error(exc)
        return 1

    if not installed:
        ui.console.print("\n[yellow]No models installed.[/yellow] "
                         "Pull one with: [bold]ollama pull <model>[/bold]")
        return 0

    mtable = ui.status_table("Installed models (Ollama)")
    mtable.columns[1].header = "Params"
    mtable.columns[2].header = "Size"
    for m in installed:
        size = f"{m.size_bytes / 1e9:.1f} GB" if m.size_bytes else "—"
        mtable.add_row(m.name, m.parameter_size or "—", size)
    ui.console.print(mtable)
    return 0


# -- cle model use <role> <model> ------------------------------------------

def cmd_model_use(ctx: AppContext, role: str, model: str) -> int:
    if role not in ROLES:
        ui.err_console.print(
            f"[red]Unknown role '{role}'.[/red] Valid roles: {', '.join(ROLES)}"
        )
        return 1
    if not ctx.project.is_initialized:
        # Ensure a project exists so we have somewhere to persist the choice.
        init_project_config(ctx.project.root)
    path = set_project_value(ctx.project.root, f"models.{role}", model)
    ui.console.print(f"Set [bold]{role}[/bold] → [bold]{model}[/bold]")
    ui.console.print(f"  ({path})")

    # Best-effort: warn if the model isn't installed. Never fail on daemon-down.
    try:
        installed = {m.name for m in ctx.provider.list_models()}
        base = model.split(":", 1)[0]
        if model not in installed and f"{base}:latest" not in installed and base not in installed:
            ui.console.print(
                f"  [yellow]note[/yellow]: '{model}' is not installed. "
                f"Pull it with: [bold]ollama pull {model}[/bold]"
            )
    except CleError:
        pass  # daemon down — assignment is still valid; doctor will flag it.

    ctx.audit.event("model_use", role=role, model=model)
    return 0


# -- cle ask "<question>" ---------------------------------------------------

def cmd_ask(ctx: AppContext, question: str) -> int:
    try:
        model = ctx.router.model_for_intent("simple_question")
    except CleError as exc:
        ui.print_error(exc)
        return 1
    ctx.audit.event("ask", intent="simple_question", model=model, request=question)
    try:
        result = ctx.provider.generate(model, question)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    ui.console.print(result.text)
    return 0


# -- cle chat ---------------------------------------------------------------

def cmd_chat(ctx: AppContext) -> int:
    try:
        model = ctx.router.model_for_intent("simple_question")
    except CleError as exc:
        ui.print_error(exc)
        return 1

    ui.console.print(
        f"[bold]cle chat[/bold] — model [bold]{model}[/bold]. "
        "Type 'exit' or Ctrl-C to quit.\n"
    )
    history: list[Message] = []
    while True:
        try:
            user = ui.console.input("[bold cyan]you[/bold cyan] > ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.console.print("\n[dim]bye[/dim]")
            return 0
        if user.lower() in {"exit", "quit"}:
            ui.console.print("[dim]bye[/dim]")
            return 0
        if not user:
            continue
        history.append(Message("user", user))
        ui.console.print("[bold green]cle[/bold green] > ", end="")
        pieces: list[str] = []
        try:
            for chunk in ctx.provider.stream(model, history):
                pieces.append(chunk)
                ui.console.print(chunk, end="")
        except CleError as exc:
            ui.console.print()
            ui.print_error(exc)
            history.pop()  # drop the turn that failed
            continue
        ui.console.print()
        history.append(Message("assistant", "".join(pieces)))
