"""Command implementations.

Each function takes an :class:`~cle.runtime.AppContext` (plus command args) and
returns an integer exit code. Keeping the logic here (separate from the Typer
wiring in ``main.py``) makes commands directly unit-testable.
"""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape

from .. import __version__, diagnostics
from ..agents.coding import CodingAgent
from ..agents.debugging import DebugAgent
from ..agents.testing import TestAgent
from ..config import init_project_config, set_project_value
from ..context.embeddings import EmbeddingStore
from ..context.retrieval import ContextEngine
from ..errors import CleError, ProjectError
from ..indexing.repository import RepositoryIndex
from ..memory.project import KINDS, TEST_COMMAND, ProjectMemory
from ..models.base import Message
from ..models.registry import ROLES
from ..project import git_is_available
from ..runtime import AppContext
from ..safety.permissions import PermissionGuard, PermissionPolicy, approve_all
from ..tools.checkpoints import CheckpointStore
from ..tools.filesystem import FileSystem
from ..tools.git import GitRepo
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
        with ui.progress_bar() as progress:
            task = progress.add_task(f"embedding with {model}", total=None)

            def on_progress(done: int, total: int, rel: str) -> None:
                progress.update(task, total=total, completed=done,
                                description=f"embedding {rel}")

            count = store.build(ctx.project.root, on_progress=on_progress)
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


# -- cle code "<request>" ---------------------------------------------------

def _render_plan(plan) -> None:
    # Model-derived text is escaped: a stray "[/...]" in the model's prose (type
    # hints like Optional[str], regex, paths) would otherwise raise MarkupError.
    ui.console.print(f"\n[bold]Goal[/bold]: {escape(str(plan.goal))}")
    if plan.files_inspected:
        ui.console.print(
            f"[bold]Files inspected[/bold]: {escape(', '.join(plan.files_inspected))}"
        )
    if plan.reasoning:
        ui.console.print(f"[bold]Reasoning[/bold]: {escape(str(plan.reasoning))}")
    ui.console.print("\n[bold]Proposed changes[/bold]:")
    if not plan.changes:
        ui.console.print("  (none)")
    for c in plan.changes:
        loc = escape(str(c.get("path", "?")))
        if str(c.get("op", "")).upper() == "RENAME_FILE":
            loc += f" -> {escape(str(c.get('new_path')))}"
        op = escape(str(c.get("op")))
        why = escape(str(c.get("explanation", "")))
        ui.console.print(f"  • {op}: {loc} — {why}")
    if plan.expected_impact:
        ui.console.print(f"\n[bold]Expected impact[/bold]: {escape(str(plan.expected_impact))}")
    if plan.tests_to_run:
        ui.console.print(f"[bold]Tests to run[/bold]: {escape(', '.join(plan.tests_to_run))}")
    if plan.risks:
        ui.console.print("[bold]Risks[/bold]:")
        for r in plan.risks:
            ui.console.print(f"  ! {escape(str(r))}")


def cmd_code(ctx: AppContext, request: str, yes: bool, no_apply: bool) -> int:
    agent = CodingAgent(
        ctx.project.root, ctx.provider, ctx.router, ctx.registry, ctx.config
    )
    ctx.audit.event("code", request=request)
    try:
        plan = agent.plan(request)
    except CleError as exc:
        ui.print_error(exc)
        return 1

    _render_plan(plan)

    # Show the concrete diff.
    if plan.edit_plan.ops:
        preview = plan.edit_plan.preview(ctx.project.root)
        if preview.strip():
            from rich.syntax import Syntax
            ui.console.print("\n[bold]Diff preview[/bold]:")
            ui.console.print(Syntax(preview, "diff", theme="ansi_dark", word_wrap=False))

    if plan.validation_errors:
        ui.print_error(CleError(
            "The proposed changes did not validate:\n- "
            + "\n- ".join(plan.validation_errors),
            remedy="Re-run the request, optionally rephrasing, or edit manually.",
        ))
        return 1

    if not plan.edit_plan.ops:
        ui.console.print("\nNo file changes proposed.")
        return 0

    if no_apply:
        ui.console.print("\n[dim]--no-apply: stopping after the plan.[/dim]")
        return 0

    # Approval (once, for the whole batch).
    if not yes:
        confirm = ui.console.input(
            f"\nApply {len(plan.edit_plan.ops)} change(s)? [y/N]: "
        ).strip().lower()
        if confirm not in {"y", "yes"}:
            ui.console.print("Aborted. No files were modified.")
            return 0

    # Checkpoint before editing (safety), if this is a git repo.
    repo = GitRepo(ctx.project.root)
    if repo.is_repo():
        try:
            sha = repo.create_checkpoint()
            status = repo.status()
            cp = CheckpointStore(ctx.project.root).add(
                sha, status.branch, f"before code: {request[:40]}", status.untracked_files
            )
            ui.console.print(f"[dim]checkpoint #{cp.id} ({sha[:10]}) created[/dim]")
        except CleError:
            pass  # non-fatal; proceed
    elif ctx.config.get("safety.require_git", True):
        ui.console.print(
            "[yellow]note[/yellow]: not a git repo — no checkpoint. "
            "Run [bold]git init[/bold] for rollback safety."
        )

    # The user approved the batch; apply through a guard that permits the
    # approved writes but still honors DENY policy (e.g. delete disabled).
    policy = PermissionPolicy.from_config(ctx.config)
    guard = PermissionGuard(policy, approver=approve_all)
    fs = FileSystem(ctx.project.root, guard)
    try:
        results = agent.apply(plan, fs)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    for r in results:
        ui.console.print(f"  [green]✓[/green] {escape(str(r))}")
    ctx.audit.event("code_applied", files=[op.path for op in plan.edit_plan.ops])
    ui.console.print(
        f"\nApplied {len(results)} change(s). Review with [bold]cle diff[/bold]; "
        "undo with [bold]cle rollback[/bold]."
    )
    if plan.tests_to_run:
        ui.console.print("Next: run your tests — [bold]cle test[/bold].")
    return 0


# -- cle test / debug / fix-tests -------------------------------------------

def _test_command_override(ctx: AppContext) -> list[str] | None:
    """Read a stored test command from memory, if any."""
    import shlex
    if not ctx.project.is_initialized:
        return None
    mem = ProjectMemory(ctx.project.root)
    try:
        cmd = mem.get_setting(TEST_COMMAND)
    finally:
        mem.close()
    return shlex.split(cmd) if cmd else None


def _report_test_result(result) -> None:
    if result.error:
        ui.print_error(CleError(
            result.error,
            remedy="Set a test command:\n  cle memory set test_command \"<cmd>\"",
        ))
        return
    header = (
        f"system [bold]{result.system.value}[/bold] · "
        f"`{' '.join(result.command)}` · exit {result.returncode}"
    )
    if result.passed:
        ui.console.print(f"[green]PASS[/green] — {header}")
        return
    ui.console.print(f"[red]FAIL[/red] — {header}")
    if result.failures:
        table = ui.status_table("Failures")
        table.columns[0].header = "Test"
        table.columns[1].header = "Location"
        table.columns[2].header = "Message"
        for f in result.failures:
            loc = f.file or "—"
            if f.line:
                loc += f":{f.line}"
            table.add_row(f.name, loc, (f.message or "").strip()[:80])
        ui.console.print(table)
    else:
        tail = "\n".join(result.output.splitlines()[-15:])
        ui.console.print(tail, markup=False)


def cmd_test(ctx: AppContext) -> int:
    guard = PermissionGuard(PermissionPolicy.from_config(ctx.config), approver=approve_all)
    agent = TestAgent(ctx.project.root, guard)
    try:
        result = agent.run(command=_test_command_override(ctx))
    except CleError as exc:
        ui.print_error(exc)
        return 1
    _report_test_result(result)
    ctx.audit.event("test", system=result.system.value,
                    passed=result.passed, failures=len(result.failures))
    if result.error:
        return 1
    return 0 if result.passed else 1


def cmd_debug(ctx: AppContext) -> int:
    guard = PermissionGuard(PermissionPolicy.from_config(ctx.config), approver=approve_all)
    result = TestAgent(ctx.project.root, guard).run(command=_test_command_override(ctx))
    if result.error:
        ui.print_error(CleError(result.error))
        return 1
    if result.passed:
        ui.console.print("[green]Tests pass[/green] — nothing to debug.")
        return 0
    _report_test_result(result)
    agent = DebugAgent(ctx.project.root, ctx.provider, ctx.router, ctx.registry, ctx.config)
    ctx.audit.event("debug", failures=len(result.failures))
    try:
        diagnosis = agent.diagnose(result)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    ui.console.print("\n[bold]Diagnosis[/bold]:")
    ui.console.print(diagnosis, markup=False)
    return 0


def cmd_fix_tests(ctx: AppContext, max_iterations: int | None, yes: bool) -> int:
    limit = max_iterations or int(ctx.config.get("agent.max_iterations", 5))
    guard = PermissionGuard(PermissionPolicy.from_config(ctx.config), approver=approve_all)
    test_agent = TestAgent(ctx.project.root, guard)
    debug_agent = DebugAgent(ctx.project.root, ctx.provider, ctx.router, ctx.registry, ctx.config)
    coding_agent = CodingAgent(ctx.project.root, ctx.provider, ctx.router, ctx.registry, ctx.config)
    cmd_override = _test_command_override(ctx)

    for iteration in range(1, limit + 1):
        ui.console.print(f"\n[bold]— fix-tests iteration {iteration}/{limit} —[/bold]")
        result = test_agent.run(command=cmd_override)
        if result.error:
            ui.print_error(CleError(result.error))
            return 1
        if result.passed:
            ui.console.print("[green]All tests pass.[/green]")
            ctx.audit.event("fix_tests", iterations=iteration, result="passed")
            return 0
        _report_test_result(result)

        # Ask the coding agent for a fix based on the debug agent's framing.
        request = debug_agent.fix_request(result)
        try:
            plan = coding_agent.plan(request)
        except CleError as exc:
            ui.print_error(exc)
            return 1
        _render_plan(plan)
        if plan.validation_errors or not plan.edit_plan.ops:
            ui.console.print(
                "[yellow]No applicable fix proposed; stopping.[/yellow]"
            )
            ctx.audit.event("fix_tests", iterations=iteration, result="no_fix")
            return 1
        preview = plan.edit_plan.preview(ctx.project.root)
        if preview.strip():
            from rich.syntax import Syntax
            ui.console.print(Syntax(preview, "diff", theme="ansi_dark", word_wrap=False))
        if not yes:
            confirm = ui.console.input(
                f"Apply {len(plan.edit_plan.ops)} fix change(s)? [y/N]: "
            ).strip().lower()
            if confirm not in {"y", "yes"}:
                ui.console.print("Aborted.")
                return 1

        repo = GitRepo(ctx.project.root)
        if repo.is_repo():
            try:
                sha = repo.create_checkpoint()
                st = repo.status()
                CheckpointStore(ctx.project.root).add(
                    sha, st.branch, f"fix-tests iter {iteration}", st.untracked_files)
            except CleError:
                pass
        fs = FileSystem(ctx.project.root, guard)
        try:
            coding_agent.apply(plan, fs)
        except CleError as exc:
            ui.print_error(exc)
            return 1

    ui.console.print(
        f"\n[red]Still failing after {limit} iteration(s).[/red] "
        "Inspect with [bold]cle debug[/bold]."
    )
    ctx.audit.event("fix_tests", iterations=limit, result="exhausted")
    return 1


# -- cle java analyze / winium analyze --------------------------------------

_SEV_STYLE = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan", "INFO": "dim"}


def _render_findings(title: str, findings) -> None:
    if not findings:
        ui.console.print(f"[green]{title}: no findings.[/green]")
        return
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    summary = "  ".join(f"{sev}={n}" for sev, n in sorted(counts.items()))
    ui.console.print(f"[bold]{title}[/bold] — {len(findings)} finding(s): {summary}\n")
    for f in findings:
        style = _SEV_STYLE.get(f.severity, "white")
        ui.console.print(f"[{style}]{f.severity}[/{style}]  [bold]{f.title}[/bold]  "
                         f"[dim]({f.category})[/dim]")
        ui.console.print(f"  File: {f.file}")
        ui.console.print(f"  Line: {f.line}")
        if f.snippet:
            ui.console.print(f"  Code: {f.snippet}", markup=False)
        ui.console.print(f"  Recommendation: {f.recommendation}\n")


def _has_java(ctx: AppContext) -> bool:
    from ..analysis.base import iter_java_files
    return bool(iter_java_files(ctx.project.root))


def cmd_java_analyze(ctx: AppContext) -> int:
    from ..analysis.java import analyze_java
    if not _has_java(ctx):
        ui.console.print("No Java files found under the project.")
        return 0
    findings = analyze_java(ctx.project.root)
    _render_findings("Java analysis", findings)
    ctx.audit.event("java_analyze", findings=len(findings))
    return 0


def cmd_winium_analyze(ctx: AppContext) -> int:
    from ..analysis.winium import analyze_winium
    if not _has_java(ctx):
        ui.console.print("No Java files found under the project.")
        return 0
    findings = analyze_winium(ctx.project.root)
    _render_findings("Winium analysis", findings)
    ctx.audit.event("winium_analyze", findings=len(findings))
    return 0


# -- cle autopilot "<task>" -------------------------------------------------

def _autopilot_checkpoint(ctx: AppContext, label: str) -> None:
    repo = GitRepo(ctx.project.root)
    if repo.is_repo():
        try:
            sha = repo.create_checkpoint()
            st = repo.status()
            CheckpointStore(ctx.project.root).add(sha, st.branch, label, st.untracked_files)
            ui.console.print(f"[dim]checkpoint ({sha[:10]}): {label}[/dim]")
        except CleError:
            pass


def _apply_with_approval(ctx: AppContext, agent, plan, fs, *, require_approval: bool,
                         yes: bool, label: str) -> bool:
    """Show a plan's diff, get approval if required, checkpoint, and apply.

    Returns True if applied, False if aborted/nothing to do.
    """
    if plan.validation_errors or not plan.edit_plan.ops:
        return False
    preview = plan.edit_plan.preview(ctx.project.root)
    if preview.strip():
        from rich.syntax import Syntax
        ui.console.print(Syntax(preview, "diff", theme="ansi_dark", word_wrap=False))
    if require_approval and not yes:
        confirm = ui.console.input(
            f"Apply {len(plan.edit_plan.ops)} change(s)? [y/N]: "
        ).strip().lower()
        if confirm not in {"y", "yes"}:
            ui.console.print("Aborted.")
            return False
    _autopilot_checkpoint(ctx, label)
    agent.apply(plan, fs)
    return True


def cmd_autopilot(ctx: AppContext, task: str, max_iterations: int | None, yes: bool) -> int:
    cfg = ctx.config
    limit = max_iterations or int(cfg.get("autonomous.max_iterations", 5))
    require_approval = bool(cfg.get("autonomous.require_approval", True))
    # Autonomous policy layered over base safety (e.g. autonomous.allow_delete).
    policy = PermissionPolicy.from_config(cfg)
    policy.allow_delete = bool(cfg.get("autonomous.allow_delete", policy.allow_delete))
    guard = PermissionGuard(policy, approver=approve_all)
    fs = FileSystem(ctx.project.root, guard)

    coding = CodingAgent(ctx.project.root, ctx.provider, ctx.router, ctx.registry, cfg)
    test_agent = TestAgent(ctx.project.root, guard)
    debug = DebugAgent(ctx.project.root, ctx.provider, ctx.router, ctx.registry, cfg)
    cmd_override = _test_command_override(ctx)

    if bool(cfg.get("autonomous.require_git", True)) and not GitRepo(ctx.project.root).is_repo():
        ui.console.print(
            "[yellow]note[/yellow]: autonomous.require_git is set but this is not a "
            "git repo — proceeding without checkpoint safety. Run [bold]git init[/bold]."
        )

    ui.console.print(f"[bold]Autopilot[/bold]: {task}\n")
    ctx.audit.event("autopilot_start", task=task, limit=limit)
    changed_files: set[str] = set()
    iterations_used = 0

    # PLAN → ANALYZE → PROPOSE → (APPROVE) → EDIT
    ui.console.print("[bold]● Plan[/bold]")
    try:
        plan = coding.plan(task)
    except CleError as exc:
        ui.print_error(exc)
        return 1
    _render_plan(plan)
    if plan.validation_errors:
        ui.print_error(CleError("Initial plan failed validation:\n- "
                                + "\n- ".join(plan.validation_errors)))
        return 1
    if plan.edit_plan.ops:
        ui.console.print("\n[bold]● Edit[/bold]")
        if not _apply_with_approval(ctx, coding, plan, fs,
                                    require_approval=require_approval, yes=yes,
                                    label=f"autopilot: {task[:40]}"):
            ui.console.print("Stopped before applying changes.")
            return 1
        changed_files.update(op.path for op in plan.edit_plan.ops)

    # BUILD/TEST → (DEBUG → FIX → TEST) loop
    last_result = None
    for iteration in range(1, limit + 1):
        iterations_used = iteration
        ui.console.print(f"\n[bold]● Test (iteration {iteration}/{limit})[/bold]")
        last_result = test_agent.run(command=cmd_override)
        if last_result.error:
            ui.console.print(f"[yellow]{last_result.error}[/yellow]")
            break
        _report_test_result(last_result)
        if last_result.passed:
            break
        ui.console.print("\n[bold]● Debug → Fix[/bold]")
        try:
            fix_plan = coding.plan(debug.fix_request(last_result))
        except CleError as exc:
            ui.print_error(exc)
            break
        _render_plan(fix_plan)
        applied = _apply_with_approval(ctx, coding, fix_plan, fs,
                                       require_approval=require_approval, yes=yes,
                                       label=f"autopilot fix iter {iteration}")
        if not applied:
            ui.console.print("[yellow]No applicable fix; stopping.[/yellow]")
            break
        changed_files.update(op.path for op in fix_plan.edit_plan.ops)

    # REVIEW + FINAL REPORT
    passed = bool(last_result and last_result.passed)
    ui.console.print("\n[bold]● Final report[/bold]")
    report = ui.kv_table("Autopilot report")
    report.add_row("Task", task)
    report.add_row("Files changed", ", ".join(sorted(changed_files)) or "none")
    report.add_row("Test result", "[green]PASS[/green]" if passed else "[red]FAIL[/red]")
    report.add_row("Iterations", str(iterations_used))
    if last_result and last_result.error:
        report.add_row("Note", last_result.error)
    ui.console.print(report)
    ui.console.print("Undo everything with [bold]cle rollback[/bold].")
    ctx.audit.event("autopilot_end", task=task, passed=passed,
                    iterations=iterations_used, files=sorted(changed_files))
    return 0 if passed else 1


# -- cle benchmark ----------------------------------------------------------

def _system_metrics() -> dict:
    import os

    from .. import diagnostics
    metrics: dict = {"cpu_count": os.cpu_count()}
    smi = diagnostics._find_nvidia_smi()
    if smi:
        import subprocess
        try:
            proc = subprocess.run(
                [smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=15,
            )
            line = (proc.stdout or "").strip().splitlines()
            if proc.returncode == 0 and line:
                metrics["gpu"] = line[0].strip()
        except (OSError, subprocess.SubprocessError):
            pass
    metrics.setdefault("gpu", "unknown")
    return metrics


def cmd_benchmark(ctx: AppContext) -> int:
    import json
    import tempfile
    from dataclasses import asdict
    from datetime import datetime

    from ..benchmark.harness import BenchContext, BenchmarkSuite, summarize
    from ..benchmark.tasks import default_suite

    workroot = Path(tempfile.mkdtemp(prefix="cle-bench-"))
    bctx = BenchContext(ctx.provider, ctx.router, ctx.registry, ctx.config, workroot)
    suite = BenchmarkSuite(default_suite())

    ui.console.print("[bold]Running benchmark suite...[/bold]")
    with ui.console.status("benchmarking"):
        results = suite.run(bctx)
    summary = summarize(results)

    table = ui.status_table("Benchmark results")
    table.columns[0].header = "Task"
    table.columns[1].header = "Result"
    table.columns[2].header = "Latency / note"
    for r in results:
        if r.skipped:
            status = "[dim]SKIP[/dim]"
        elif r.success:
            status = "[green]PASS[/green]"
        else:
            status = "[red]FAIL[/red]"
        detail = f"{r.latency_s:.3f}s  iters={r.iterations}  {r.note}" if not r.skipped else r.note
        table.add_row(f"{r.name} ({r.category})", status, detail)
    ui.console.print(table)
    ui.console.print(
        f"\n{summary['passed']}/{summary['ran']} passed"
        + (f" ({summary['success_rate']:.0%})" if summary["success_rate"] is not None else "")
        + f", {summary['skipped']} skipped, {summary['total_latency_s']:.2f}s total."
    )

    # Store results locally.
    out_dir = ctx.project.root / ".cle" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(list(out_dir.glob("benchmark-*.json"))) + 1
    out_path = out_dir / f"benchmark-{n:03d}.json"
    payload = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "models": ctx.registry.all_roles(),
        "system": _system_metrics(),
        "summary": summary,
        "results": [asdict(r) for r in results],
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    ui.console.print(f"Saved: {out_path}")
    ctx.audit.event("benchmark", passed=summary["passed"], ran=summary["ran"])
    return 0


# -- cle dashboard (optional TUI snapshot) ----------------------------------

def cmd_dashboard(ctx: AppContext) -> int:
    from rich.columns import Columns
    from rich.panel import Panel

    p = ctx.project
    proj = Panel(
        f"root: {p.root}\ninitialized: {'yes' if p.is_initialized else 'no'}\n"
        f"git: {'yes' if p.is_git_repo else 'no'}",
        title="Project", border_style="cyan",
    )
    roles = ctx.registry.all_roles()
    models = Panel(
        "\n".join(f"{r}: {m or '—'}" for r, m in roles.items())
        + f"\nprovider: {ctx.config.get('provider.host')}",
        title="Models", border_style="magenta",
    )

    # Index
    index_line = "not indexed"
    if (p.cle_dir / "index" / "index.db").exists():
        idx = RepositoryIndex(p.root)
        try:
            c = idx.counts()
            index_line = f"{c['files']} files\n{c['symbols']} symbols\n{c['imports']} imports"
        finally:
            idx.close()
    index_panel = Panel(index_line, title="Index", border_style="green")

    # Memory
    mem_line = "n/a"
    if p.is_initialized:
        mem = ProjectMemory(p.root)
        try:
            s = mem.summary()
            mem_line = "\n".join(f"{k}: {v}" for k, v in s.items()) or "empty"
        finally:
            mem.close()
    mem_panel = Panel(mem_line, title="Memory", border_style="yellow")

    # Git status
    git_line = "not a repo"
    repo = GitRepo(p.root)
    if repo.is_repo():
        st = repo.status()
        git_line = (f"branch: {st.branch}\n"
                    + ("clean" if st.clean else
                       f"{len(st.changed_files)} changed, {len(st.untracked_files)} untracked"))
    git_panel = Panel(git_line, title="Git", border_style="blue")

    ui.console.print(Panel("[bold]Local CLE — status dashboard[/bold]", border_style="white"))
    ui.console.print(Columns([proj, models], equal=True, expand=True))
    ui.console.print(Columns([index_panel, mem_panel, git_panel], equal=True, expand=True))
    return 0
