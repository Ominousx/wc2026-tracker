#!/usr/bin/env python3
"""
WC 2026 Club G+A Tracker — CLI
Usage:
    python cli.py                  # paste mode (interactive)
    python cli.py --file data.txt  # read from a saved paste file
    python cli.py --sort goals     # sort by goals (default: ga)
    python cli.py --top 10         # show top N clubs only
    python cli.py --club Arsenal   # show a specific club's players
    python cli.py --refresh        # force re-fetch Wikipedia squad mapping
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from squad_mapper import get_player_club_map, lookup

console = Console()

# ── Parser ────────────────────────────────────────────────────────────────────
def parse_fotmob(raw: str, mapping: dict) -> list[dict]:
    """Parse FotMob (or FBref) Goals+Assists paste into list of dicts."""
    rows = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # FotMob: "Jonathan David    3"  (2+ spaces or tab before number)
        m = re.search(r"^(.*?)\s{2,}(\d+)\s*$", line)
        if not m:
            m = re.search(r"^(.*?)\t(\d+)\s*$", line)
        if not m:
            m = re.search(r"^(.*?)\s+(\d+)\s*$", line)
        if not m:
            continue

        name = m.group(1).strip()
        ga   = int(m.group(2))

        # Strip FBref artefacts
        name = re.sub(r"^\d+\s+", "", name)
        name = re.sub(r"xG\s*\+?\s*xA\s*:?\s*[\d.]+", "", name, flags=re.I).strip()

        if name.lower() in ("player", "#", "stats", "all", "name", "") or not name:
            continue
        if not (0 < ga < 40):
            continue

        club = lookup(name, mapping)
        rows.append({"player": name, "ga": ga, "club": club})

    return rows


def aggregate_clubs(rows: list[dict]) -> list[dict]:
    clubs: dict[str, dict] = {}
    for r in rows:
        if r["club"] == "Unknown":
            continue
        c = clubs.setdefault(r["club"], {"club": r["club"], "ga": 0, "players": []})
        c["ga"] += r["ga"]
        c["players"].append({"name": r["player"], "ga": r["ga"]})
    return sorted(clubs.values(), key=lambda x: x["ga"], reverse=True)


# ── Display ───────────────────────────────────────────────────────────────────
MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}

def render_leaderboard(clubs: list[dict], top: int | None = None, sort: str = "ga"):
    if sort == "name":
        clubs = sorted(clubs, key=lambda x: x["club"])
    elif sort == "players":
        clubs = sorted(clubs, key=lambda x: len(x["players"]), reverse=True)

    display = clubs[:top] if top else clubs
    max_ga  = max((c["ga"] for c in display), default=1)

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold dim",
        border_style="dim",
        expand=False,
        min_width=60,
    )
    table.add_column("#",       style="dim",    width=4,  justify="right")
    table.add_column("Club",    style="bold",   min_width=24)
    table.add_column("G+A",     style="green",  width=5,  justify="right")
    table.add_column("Players", style="cyan",   width=7,  justify="right")
    table.add_column("Bar",                     min_width=20)

    for i, club in enumerate(display):
        medal    = MEDALS.get(i, str(i + 1))
        bar_len  = int((club["ga"] / max_ga) * 20)
        bar      = "█" * bar_len + "░" * (20 - bar_len)
        bar_text = Text(bar)
        bar_text.stylize("green", 0, bar_len)
        bar_text.stylize("dim",   bar_len, 20)

        table.add_row(
            medal,
            club["club"],
            str(club["ga"]),
            str(len(club["players"])),
            bar_text,
        )

    console.print()
    console.print(table)


def render_club(clubs: list[dict], club_name: str):
    match = next((c for c in clubs if c["club"].lower() == club_name.lower()), None)
    if not match:
        # fuzzy
        match = next((c for c in clubs if club_name.lower() in c["club"].lower()), None)
    if not match:
        console.print(f"[red]Club '{club_name}' not found.[/red]")
        return

    players = sorted(match["players"], key=lambda p: p["ga"], reverse=True)
    max_ga  = max((p["ga"] for p in players), default=1)

    table = Table(
        title=f"[bold]{match['club']}[/bold] — {match['ga']} G+A",
        box=box.SIMPLE_HEAVY,
        border_style="dim",
        show_header=True,
        header_style="bold dim",
    )
    table.add_column("Player", min_width=24, style="bold")
    table.add_column("G+A",    width=5, justify="right", style="green")
    table.add_column("",       min_width=15)

    for p in players:
        bar_len  = int((p["ga"] / max_ga) * 15)
        bar      = Text("█" * bar_len, style="green")
        table.add_row(p["name"], str(p["ga"]), bar)

    console.print()
    console.print(table)


def render_unmapped(rows: list[dict]):
    unk = [r for r in rows if r["club"] == "Unknown"]
    if not unk:
        return
    console.print(f"\n[yellow]⚠ {len(unk)} unmapped player(s):[/yellow]")
    for r in sorted(unk, key=lambda x: x["ga"], reverse=True):
        console.print(f"  [dim]{r['player']:<30}[/dim] [yellow]{r['ga']} G+A[/yellow]")
    console.print("[dim]  → Run with --refresh to re-fetch Wikipedia squads[/dim]\n")


def render_summary(rows: list[dict], clubs: list[dict]):
    total_ga  = sum(r["ga"] for r in rows)
    n_players = len(rows)
    n_clubs   = len(clubs)
    n_unknown = sum(1 for r in rows if r["club"] == "Unknown")

    console.print(Panel(
        f"[bold green]{total_ga}[/bold green] G+A  ·  "
        f"[bold]{n_players}[/bold] players  ·  "
        f"[bold cyan]{n_clubs}[/bold cyan] clubs  ·  "
        f"[yellow]{n_unknown} unmapped[/yellow]  ·  "
        f"[dim]{datetime.now().strftime('%d %b %Y %H:%M')}[/dim]",
        title="[bold]⚽ WC 2026 Club Tracker[/bold]",
        border_style="green",
        expand=False,
    ))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="WC 2026 Club G+A Tracker — paste FotMob data, get a club leaderboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py                       # interactive paste mode
  python cli.py --file data.txt       # read from saved paste file
  python cli.py --top 10              # top 10 clubs only
  python cli.py --club Liverpool      # player breakdown for one club
  python cli.py --sort name           # sort alphabetically
  python cli.py --refresh             # force re-fetch squad mapping
        """
    )
    parser.add_argument("--file",    "-f", type=str,  help="Path to a text file with FotMob G+A paste")
    parser.add_argument("--top",     "-n", type=int,  help="Show top N clubs only")
    parser.add_argument("--club",    "-c", type=str,  help="Show player breakdown for a specific club")
    parser.add_argument("--sort",    "-s", type=str,  default="ga",
                        choices=["ga", "players", "name"], help="Sort order (default: ga)")
    parser.add_argument("--refresh", "-r", action="store_true", help="Force re-fetch Wikipedia squad mapping")
    parser.add_argument("--no-unmapped", action="store_true", help="Hide unmapped players section")
    args = parser.parse_args()

    # Load squad mapping
    with Progress(SpinnerColumn(), TextColumn("[dim]{task.description}"), console=console, transient=True) as p:
        p.add_task("Loading squad mapping from Wikipedia…")
        try:
            mapping = get_player_club_map(force_refresh=args.refresh)
            console.print(f"[dim]✓ {len(mapping)} players mapped (Wikipedia 2026 WC Squads)[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not fetch Wikipedia squads: {e}[/yellow]")
            mapping = {}

    # Get raw data
    if args.file:
        path = Path(args.file)
        if not path.exists():
            console.print(f"[red]File not found: {path}[/red]")
            sys.exit(1)
        raw = path.read_text(encoding="utf-8")
        console.print(f"[dim]Read from {path}[/dim]")
    else:
        console.print("\n[bold]Paste FotMob Goals + Assists data below.[/bold]")
        console.print("[dim]  → fotmob.com → World Cup → Stats → Goals+Assists → See all → Ctrl+A, Ctrl+C[/dim]")
        console.print("[dim]  → When done, press Enter twice (or Ctrl+D on Mac/Linux)[/dim]\n")
        lines = []
        try:
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
        except EOFError:
            pass
        raw = "\n".join(lines)

    if not raw.strip():
        console.print("[red]No data provided.[/red]")
        sys.exit(1)

    # Parse
    rows  = parse_fotmob(raw, mapping)
    clubs = aggregate_clubs(rows)

    if not rows:
        console.print("[red]Could not parse any players. Check the paste format.[/red]")
        sys.exit(1)

    # Render
    render_summary(rows, clubs)

    if args.club:
        render_club(clubs, args.club)
    else:
        render_leaderboard(clubs, top=args.top, sort=args.sort)

    if not args.no_unmapped:
        render_unmapped(rows)


if __name__ == "__main__":
    main()
