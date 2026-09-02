"""Rich-based UI helpers shared across commands.

Centralizes console creation and common renderings (tables, status rows, error
panels) so output stays consistent and commands stay terse.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..errors import CleError

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
