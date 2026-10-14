"""Rich-based UI helpers shared across commands.

Centralizes console creation and common renderings (tables, status rows, error
panels) so output stays consistent and commands stay terse.
"""

from __future__ import annotations

import contextlib
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..errors import CleError


def _force_utf8(stream) -> None:
    """Make a text stream encode as UTF-8.

    The default Windows console is cp1252, which cannot encode glyphs like
    ``->`` arrows or most model output (emoji, math, non-Latin scripts). Writing
    those would raise ``UnicodeEncodeError`` mid-render. Reconfiguring to UTF-8
    with ``errors="replace"`` makes output robust on every terminal; the guard
    keeps it a no-op where reconfigure is unavailable (e.g. captured streams).
    """
    with contextlib.suppress(AttributeError, ValueError, OSError):
        stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8(sys.stdout)
_force_utf8(sys.stderr)

# A single shared console. stderr console is used for errors so stdout stays
# clean for pipeable command output.
console = Console()
err_console = Console(stderr=True)

# Status glyphs (ASCII-safe fallbacks kept simple for Windows terminals).
OK = "[green]OK[/green]"
WARN = "[yellow]WARN[/yellow]"
FAIL = "[red]FAIL[/red]"


def print_error(exc: CleError) -> None:
    """Render a structured CLE error to stderr."""
    body = exc.message
    if exc.remedy:
        body += f"\n\n[bold]Try:[/bold]\n{exc.remedy}"
    err_console.print(Panel(body, title="Error", border_style="red", expand=False))


def status_table(title: str) -> Table:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    return table


def kv_table(title: str) -> Table:
    table = Table(title=title, show_header=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value", overflow="fold")
    return table
