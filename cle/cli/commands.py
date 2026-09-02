"""Command implementations.

Each function takes an :class:`~cle.runtime.AppContext` (plus command args) and
returns an integer exit code. Keeping the logic here (separate from the Typer
wiring in ``main.py``) makes commands directly unit-testable.
"""

from __future__ import annotations

from pathlib import Path

from .. import __version__, diagnostics
from ..config import init_project_config, set_project_value
from ..context.embeddings import EmbeddingStore
from ..context.manager import ContextManager
from ..context.retrieval import ContextEngine
from ..errors import CleError, ProjectError
from ..indexing.repository import RepositoryIndex
from ..memory.project import KINDS, ProjectMemory
from ..models.base import Message
from ..tools.checkpoints import CheckpointStore
from ..tools.git import GitRepo
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


# -- cle index --------------------------------------------------------------

def cmd_index(ctx: AppContext) -> int:
    if not ctx.project.is_initialized:
        init_project_config(ctx.project.root)
    ui.console.print(f"Indexing [bold]{ctx.project.root}[/bold] ...")
    index = RepositoryIndex(ctx.project.root)
    try:
        with ui.console.status("scanning files"):
            stats = index.rebuild()
    finally:
        index.close()

    table = ui.kv_table("Index built")
    table.add_row("Files", str(stats.files))
    table.add_row("Parsed (java/py)", str(stats.parsed))
    table.add_row("Symbols", str(stats.symbols))
    table.add_row("Imports", str(stats.imports))
    if stats.languages:
        langs = ", ".join(f"{k}={v}" for k, v in sorted(
            stats.languages.items(), key=lambda kv: -kv[1]))
        table.add_row("Languages", langs)
    ui.console.print(table)
    ctx.audit.event("index", files=stats.files, symbols=stats.symbols)
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

    index_db = p.cle_dir / "index" / "index.db"
    if index_db.exists():
        index = RepositoryIndex(p.root)
        try:
            counts = index.counts()
            table.add_row(
                "Index",
                f"{counts['files']} files, {counts['symbols']} symbols, "
                f"{counts['imports']} imports",
            )
        finally:
            index.close()
    else:
        table.add_row("Index", "not indexed (run: cle index)")
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
    # markup=False: model output may contain brackets that are not Rich markup.
    ui.console.print(result.text, markup=False)
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
                ui.console.print(chunk, end="", markup=False)
        except CleError as exc:
            ui.console.print()
            ui.print_error(exc)
            history.pop()  # drop the turn that failed
            continue
        ui.console.print()
        history.append(Message("assistant", "".join(pieces)))


# -- context / retrieval helpers -------------------------------------------

def _require_index(ctx: AppContext) -> RepositoryIndex:
    index = RepositoryIndex(ctx.project.root)
    if not index.is_built():
        index.close()
        raise ProjectError(
            "The project is not indexed yet.",
            remedy="Build the index first:\n  cle index",
        )
    return index


def _context_engine(ctx: AppContext, index: RepositoryIndex) -> ContextEngine:
    return ContextEngine(
        ctx.project.root, index, ctx.provider, ctx.registry, ctx.config
    )


# -- cle search "<pattern>" -------------------------------------------------

def cmd_search(ctx: AppContext, pattern: str, ignore_case: bool, fixed: bool) -> int:
    from ..tools.search import search as exact_search

    matches = exact_search(
        ctx.project.root, pattern, ignore_case=ignore_case, fixed_string=fixed
    )
    if not matches:
        ui.console.print(f"No matches for [bold]{pattern}[/bold].")
        return 0
    table = ui.status_table(f"search: {pattern}")
    table.columns[0].header = "Location"
    table.columns[1].header = "Src"
    table.columns[2].header = "Line"
    for m in matches:
        table.add_row(f"{m.path}:{m.line}", m.source.value, m.text.strip()[:120])
    ui.console.print(table)
    ui.console.print(f"\n{len(matches)} match(es).")
    ctx.audit.event("search", pattern=pattern, matches=len(matches))
    return 0


# -- cle symbol <name> ------------------------------------------------------

def cmd_symbol(ctx: AppContext, name: str) -> int:
    try:
        index = _require_index(ctx)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    try:
        symbols = index.find_symbols(name)
    finally:
        index.close()
    if not symbols:
        ui.console.print(f"No symbol named [bold]{name}[/bold] in the index.")
        return 0
    table = ui.status_table(f"symbol: {name}")
    table.columns[0].header = "Kind"
    table.columns[1].header = "Parent"
    table.columns[2].header = "Location"
    for s in symbols:
        span = f"{s['line_start']}-{s['line_end']}" if s["line_end"] else str(s["line_start"])
        table.add_row(s["kind"], s["parent"] or "—", f"{s['file_path']}:{span}")
    ui.console.print(table)
    ctx.audit.event("symbol", name=name, hits=len(symbols))
    return 0


# -- cle explain <file> -----------------------------------------------------

def cmd_explain(ctx: AppContext, file: str) -> int:
    target = (ctx.project.root / file).resolve()
    if not target.exists():
        ui.print_error(ProjectError(
            f"File not found: {file}",
            remedy="Check the path (relative to the project root).",
        ))
        return 1
    try:
        model = ctx.router.model_for_intent("architecture")
    except CleError as exc:
        ui.print_error(exc)
        return 1

    rel = target.relative_to(ctx.project.root).as_posix()
    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        ui.print_error(ProjectError(f"Could not read {file}: {exc}"))
        return 1

    # Structural outline from the index (if available), always LOCAL evidence.
    outline = ""
    index = RepositoryIndex(ctx.project.root)
    try:
        if index.is_built():
            syms = index.symbols_in_file(rel)
            if syms:
                outline = "\n".join(
                    f"- {s['kind']} {s['name']} (line {s['line_start']})" for s in syms
                )
    finally:
        index.close()

    system = (
        "You are a senior engineer explaining code from the user's LOCAL project. "
        "Base your explanation only on the provided source. Cite file:line where useful."
    )
    prompt = (
        f"File: {rel}\n\n"
        + (f"Symbol outline (LOCAL):\n{outline}\n\n" if outline else "")
        + f"Source:\n```\n{source[:16000]}\n```\n\n"
        "Explain what this file does, its key responsibilities, and how the "
        "pieces fit together."
    )
    ctx.audit.event("explain", file=rel, model=model)
    try:
        result = ctx.provider.generate(model, prompt, system=system)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    ui.console.print(result.text, markup=False)
    return 0


# -- cle embed --------------------------------------------------------------

def cmd_embed(ctx: AppContext) -> int:
    model = ctx.config.get("models.embedding", "") or ""
    if not model:
        ui.print_error(CleError(
            "No embedding model configured.",
            remedy="Pull one and assign it:\n"
                   "  ollama pull nomic-embed-text\n"
                   "  cle model use embedding nomic-embed-text",
        ))
        return 1
    try:
        index = _require_index(ctx)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    store = EmbeddingStore(index.db, ctx.provider, model)
    try:
        with ui.console.status(f"embedding chunks with {model}"):
            count = store.build(ctx.project.root)
    except CleError as exc:
        index.close()
        ui.print_error(exc)
        return 1
    index.close()
    ui.console.print(f"Embedded [bold]{count}[/bold] chunks with [bold]{model}[/bold].")
    ctx.audit.event("embed", model=model, chunks=count)
    return 0


# -- cle memory -------------------------------------------------------------

def _open_memory(ctx: AppContext) -> ProjectMemory:
    if not ctx.project.is_initialized:
        init_project_config(ctx.project.root)
    return ProjectMemory(ctx.project.root)


def cmd_memory(ctx: AppContext) -> int:
    mem = _open_memory(ctx)
    try:
        summary = mem.summary()
        settings = mem.settings()
    finally:
        mem.close()
    table = ui.kv_table("Project memory")
    table.add_row("Project", str(ctx.project.root))
    if summary:
        for kind, n in summary.items():
            table.add_row(kind, str(n))
    else:
        table.add_row("entries", "none yet")
    for key, value in settings.items():
        table.add_row(f"setting:{key}", value)
    ui.console.print(table)
    ui.console.print(
        "\nAdd with: [bold]cle memory add <kind> \"<title>\" [body][/bold]  "
        "(kinds: " + ", ".join(KINDS) + ")"
    )
    return 0


def cmd_memory_show(ctx: AppContext, kind: str | None) -> int:
    if kind and kind not in KINDS:
        ui.err_console.print(f"[red]Unknown kind '{kind}'.[/red] Valid: {', '.join(KINDS)}")
        return 1
    mem = _open_memory(ctx)
    try:
        entries = mem.entries(kind)
        settings = mem.settings()
    finally:
        mem.close()
    if not entries and not settings:
        ui.console.print("Project memory is empty.")
        return 0
    if entries:
        table = ui.status_table("Memory entries")
        table.columns[0].header = "ID/Kind"
        table.columns[1].header = "Title"
        table.columns[2].header = "Body"
        for e in entries:
            table.add_row(f"{e.id} · {e.kind}", e.title, (e.body or "").strip()[:100])
        ui.console.print(table)
    if settings:
        stable = ui.kv_table("Settings")
        for k, v in settings.items():
            stable.add_row(k, v)
        ui.console.print(stable)
    return 0


def cmd_memory_clear(ctx: AppContext, yes: bool) -> int:
    if not yes:
        confirm = ui.console.input(
            "Clear ALL project memory? This cannot be undone [y/N]: "
        ).strip().lower()
        if confirm not in {"y", "yes"}:
            ui.console.print("Aborted.")
            return 0
    mem = _open_memory(ctx)
    try:
        mem.clear()
    finally:
        mem.close()
    ui.console.print("Project memory cleared.")
    ctx.audit.event("memory_clear")
    return 0


def cmd_memory_add(ctx: AppContext, kind: str, title: str, body: str | None) -> int:
    if kind not in KINDS:
        ui.err_console.print(f"[red]Unknown kind '{kind}'.[/red] Valid: {', '.join(KINDS)}")
        return 1
    mem = _open_memory(ctx)
    try:
        entry_id = mem.add(kind, title, body)
    finally:
        mem.close()
    ui.console.print(f"Recorded {kind} #{entry_id}: [bold]{title}[/bold]")
    ctx.audit.event("memory_add", entry_kind=kind, id=entry_id)
    return 0


def cmd_memory_set(ctx: AppContext, key: str, value: str) -> int:
    mem = _open_memory(ctx)
    try:
        mem.set_setting(key, value)
    finally:
        mem.close()
    ui.console.print(f"Set memory setting [bold]{key}[/bold] = {value}")
    ctx.audit.event("memory_set", key=key)
    return 0


def cmd_memory_remove(ctx: AppContext, entry_id: int) -> int:
    mem = _open_memory(ctx)
    try:
        removed = mem.remove(entry_id)
    finally:
        mem.close()
    if removed:
        ui.console.print(f"Removed entry #{entry_id}.")
        return 0
    ui.console.print(f"No entry #{entry_id}.")
    return 1


# -- git safety: diff / checkpoint / rollback -------------------------------

def _require_git(ctx: AppContext) -> GitRepo:
    repo = GitRepo(ctx.project.root)
    if not repo.is_repo():
        raise ProjectError(
            "This project is not a git repository.",
            remedy="Initialize git to enable checkpoints/rollback:\n  git init",
        )
    return repo


def cmd_diff(ctx: AppContext) -> int:
    try:
        repo = _require_git(ctx)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    status = repo.status()
    ui.console.print(
        f"branch [bold]{status.branch}[/bold] — "
        + ("clean" if status.clean else
           f"{len(status.changed_files)} changed, {len(status.untracked_files)} untracked")
    )
    diff = repo.diff()
    if diff.strip():
        from rich.syntax import Syntax
        ui.console.print(Syntax(diff, "diff", theme="ansi_dark", word_wrap=False))
    if status.untracked_files:
        ui.console.print("\n[dim]untracked:[/dim] " + ", ".join(status.untracked_files))
    return 0


def cmd_checkpoint(ctx: AppContext, label: str) -> int:
    try:
        repo = _require_git(ctx)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    try:
        sha = repo.create_checkpoint()
        status = repo.status()
    except CleError as exc:
        ui.print_error(exc)
        return 1
    store = CheckpointStore(ctx.project.root)
    cp = store.add(sha, status.branch, label or "manual", status.untracked_files)
    ui.console.print(
        f"Checkpoint [bold]#{cp.id}[/bold] created "
        f"([bold]{sha[:10]}[/bold] on {cp.branch}) — {cp.label}"
    )
    ctx.audit.event("checkpoint", id=cp.id, sha=sha, label=cp.label)
    return 0


def cmd_rollback(ctx: AppContext, checkpoint_id: int | None, yes: bool) -> int:
    try:
        repo = _require_git(ctx)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    store = CheckpointStore(ctx.project.root)
    cp = store.get(checkpoint_id) if checkpoint_id else store.latest()
    if cp is None:
        ui.print_error(ProjectError(
            "No checkpoint to roll back to.",
            remedy="Create one first:\n  cle checkpoint \"before edits\"",
        ))
        return 1
    if not yes:
        confirm = ui.console.input(
            f"Restore tracked files to checkpoint #{cp.id} ({cp.sha[:10]})? "
            "Uncommitted changes to tracked files will be lost [y/N]: "
        ).strip().lower()
        if confirm not in {"y", "yes"}:
            ui.console.print("Aborted.")
            return 0
    try:
        repo.restore_checkpoint(cp.sha)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    ui.console.print(f"Rolled back tracked files to checkpoint #{cp.id}.")
    # New untracked files added since the checkpoint are reported, never deleted.
    now_untracked = set(repo.status().untracked_files)
    new_files = sorted(now_untracked - set(cp.untracked))
    if new_files:
        ui.console.print(
            "[yellow]note[/yellow]: these files were added since the checkpoint "
            "and were left in place:\n  " + "\n  ".join(new_files)
        )
    ctx.audit.event("rollback", id=cp.id, sha=cp.sha)
    return 0
