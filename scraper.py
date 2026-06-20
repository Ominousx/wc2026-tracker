#!/usr/bin/env python3
"""
scraper.py — FBref World Cup Stats scraper using Playwright
Runs a real headless browser to bypass Cloudflare, scrapes the
Player Standard Stats table, and saves to wc2026_stats.csv

Install:
    pip install playwright pandas
    playwright install chromium

Run:
    python scraper.py                    # scrape and print leaderboard
    python scraper.py --save             # scrape and save to wc2026_stats.csv
    python scraper.py --csv wc2026_stats.csv  # use existing CSV, skip scrape
"""

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

FBREF_URL = "https://fbref.com/en/comps/1/stats/World-Cup-Stats"
TABLE_ID  = "stats_standard"
CSV_FILE  = Path(__file__).parent / "wc2026_stats.csv"


# ── Scraper ───────────────────────────────────────────────────────────────────
def scrape_fbref() -> list[dict]:
    """Use Playwright to load FBref and parse the stats table."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("Playwright not installed. Run:\n  pip install playwright && playwright install chromium")
        sys.exit(1)

    print(f"[{now()}] Launching browser…")
    rows = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        )

        print(f"[{now()}] Loading {FBREF_URL} …")
        page.goto(FBREF_URL, wait_until="domcontentloaded", timeout=30000)

        # Wait for table to appear
        try:
            page.wait_for_selector(f"#{TABLE_ID}", timeout=20000)
        except PWTimeout:
            print("Timed out waiting for stats table.")
            browser.close()
            sys.exit(1)

        # Small delay to let JS finish rendering
        time.sleep(2)

        # Parse table via JS in the browser context
        data = page.evaluate(f"""
        () => {{
            const table = document.getElementById('{TABLE_ID}');
            if (!table) return null;

            // Get header names
            const headers = [];
            table.querySelectorAll('thead tr th, thead tr td').forEach(th => {{
                headers.push(th.getAttribute('data-stat') || th.textContent.trim());
            }});

            // Get rows
            const rows = [];
            table.querySelectorAll('tbody tr').forEach(tr => {{
                if (tr.classList.contains('spacer') || tr.classList.contains('thead')) return;
                const row = {{}};
                tr.querySelectorAll('td, th').forEach(td => {{
                    const stat = td.getAttribute('data-stat');
                    if (stat) row[stat] = td.textContent.trim();
                }});
                if (row['player']) rows.push(row);
            }});
            return {{ headers, rows }};
        }}
        """)

        browser.close()

    if not data or not data["rows"]:
        print("No data found in table.")
        sys.exit(1)

    print(f"[{now()}] Scraped {len(data['rows'])} rows")
    return data["rows"]


def parse_rows(raw_rows: list[dict]) -> list[dict]:
    """Extract player, club, goals, assists, ga from raw table rows."""
    parsed = []
    for row in raw_rows:
        player = row.get("player", "").strip()
        club   = row.get("club", "").strip()
        squad  = row.get("squad", "").strip()

        if not player or player.lower() in ("player", ""):
            continue

        try:
            goals   = int(row.get("goals",   "0") or 0)
            assists = int(row.get("assists",  "0") or 0)
            ga      = int(row.get("goals_assists", "0") or 0)
        except ValueError:
            # fallback: compute from goals + assists
            ga = goals + assists

        # FBref uses 'club' column — use it directly, no mapping needed
        if not club:
            club = "Unknown"

        parsed.append({
            "player":  player,
            "squad":   squad,   # national team
            "club":    club,
            "goals":   goals,
            "assists": assists,
            "ga":      ga,
        })

    return [p for p in parsed if p["ga"] > 0]


# ── CSV helpers ───────────────────────────────────────────────────────────────
def save_csv(rows: list[dict], path: Path):
    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    print(f"[{now()}] Saved {len(df)} rows → {path}")


def load_csv(path: Path) -> list[dict]:
    import pandas as pd
    df = pd.read_csv(path)
    df = df.fillna(0)
    return df.to_dict("records")


# ── Leaderboard ───────────────────────────────────────────────────────────────
def aggregate_clubs(rows: list[dict]) -> list[dict]:
    clubs: dict[str, dict] = {}
    for r in rows:
        club = r.get("club", "Unknown")
        if not club or club == "Unknown":
            continue
        c = clubs.setdefault(club, {"club": club, "goals": 0, "assists": 0, "ga": 0, "players": []})
        c["goals"]   += int(r.get("goals",   0))
        c["assists"]  += int(r.get("assists", 0))
        c["ga"]       += int(r.get("ga",      0))
        c["players"].append({"name": r["player"], "goals": int(r.get("goals", 0)),
                             "assists": int(r.get("assists", 0)), "ga": int(r.get("ga", 0))})
    return sorted(clubs.values(), key=lambda x: x["ga"], reverse=True)


def print_leaderboard(clubs: list[dict], top: int | None = None):
    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
        from rich.panel import Panel
        console = Console()
        use_rich = True
    except ImportError:
        use_rich = False

    display  = clubs[:top] if top else clubs
    max_ga   = max((c["ga"] for c in display), default=1)
    total_ga = sum(c["ga"] for c in clubs)

    if use_rich:
        console.print(Panel(
            f"[bold green]{total_ga}[/bold green] G+A  ·  "
            f"[bold cyan]{len(clubs)}[/bold cyan] clubs  ·  "
            f"[dim]{now()}[/dim]",
            title="[bold]⚽ WC 2026 — Club G+A Leaderboard[/bold]",
            border_style="green", expand=False,
        ))

        table = Table(box=box.ROUNDED, border_style="dim", header_style="bold dim", expand=False)
        table.add_column("#",       width=4,  justify="right", style="dim")
        table.add_column("Club",    min_width=24, style="bold")
        table.add_column("G",       width=4,  justify="right", style="red")
        table.add_column("A",       width=4,  justify="right", style="blue")
        table.add_column("G+A",     width=5,  justify="right", style="green")
        table.add_column("Players", width=7,  justify="right", style="cyan")
        table.add_column("Bar",     min_width=20)

        MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, c in enumerate(display):
            bar_len  = int((c["ga"] / max_ga) * 20)
            bar      = Text("█" * bar_len + "░" * (20 - bar_len))
            bar.stylize("green", 0, bar_len)
            bar.stylize("dim",   bar_len, 20)
            table.add_row(
                MEDALS.get(i, str(i + 1)),
                c["club"], str(c["goals"]), str(c["assists"]),
                str(c["ga"]), str(len(c["players"])), bar,
            )

        console.print()
        console.print(table)
    else:
        # Plain text fallback
        print(f"\n{'#':<4} {'Club':<28} {'G':>3} {'A':>3} {'G+A':>5} {'Players':>7}")
        print("-" * 60)
        for i, c in enumerate(display, 1):
            print(f"{i:<4} {c['club']:<28} {c['goals']:>3} {c['assists']:>3} {c['ga']:>5} {len(c['players']):>7}")


def print_club(clubs: list[dict], club_name: str):
    match = next((c for c in clubs if club_name.lower() in c["club"].lower()), None)
    if not match:
        print(f"Club '{club_name}' not found.")
        return

    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text
        console = Console()
        players = sorted(match["players"], key=lambda p: p["ga"], reverse=True)
        max_ga  = max((p["ga"] for p in players), default=1)

        table = Table(
            title=f"[bold]{match['club']}[/bold] — {match['goals']}G {match['assists']}A {match['ga']} G+A",
            box=box.SIMPLE_HEAVY, border_style="dim", header_style="bold dim"
        )
        table.add_column("Player",  min_width=24, style="bold")
        table.add_column("G",       width=4, justify="right", style="red")
        table.add_column("A",       width=4, justify="right", style="blue")
        table.add_column("G+A",     width=5, justify="right", style="green")
        table.add_column("",        min_width=15)

        for p in players:
            bar_len = int((p["ga"] / max_ga) * 15)
            bar     = Text("█" * bar_len, style="green")
            table.add_row(p["name"], str(p["goals"]), str(p["assists"]), str(p["ga"]), bar)

        console.print()
        console.print(table)
    except ImportError:
        print(f"\n{match['club']} — {match['ga']} G+A")
        for p in sorted(match["players"], key=lambda x: x["ga"], reverse=True):
            print(f"  {p['name']:<28} {p['goals']}G  {p['assists']}A  {p['ga']} G+A")


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Scrape FBref World Cup Stats and show club G+A leaderboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py                        # scrape live + print leaderboard
  python scraper.py --save                 # scrape + save CSV
  python scraper.py --csv wc2026_stats.csv # use saved CSV (no scrape)
  python scraper.py --top 10               # top 10 clubs
  python scraper.py --club Arsenal         # player breakdown for Arsenal
  python scraper.py --goals                # sort by goals instead of G+A
        """
    )
    ap.add_argument("--save",  action="store_true", help=f"Save scraped data to {CSV_FILE.name}")
    ap.add_argument("--csv",   type=str,  help="Load from existing CSV instead of scraping")
    ap.add_argument("--top",   type=int,  help="Show top N clubs")
    ap.add_argument("--club",  type=str,  help="Show player breakdown for a specific club")
    ap.add_argument("--goals", action="store_true", help="Sort by goals (default: G+A)")
    args = ap.parse_args()

    # Get data
    if args.csv:
        path = Path(args.csv)
        if not path.exists():
            print(f"File not found: {path}")
            sys.exit(1)
        print(f"[{now()}] Loading from {path}…")
        raw_rows = load_csv(path)
        rows     = [r for r in raw_rows if int(r.get("ga", 0)) > 0]
    else:
        raw_rows = scrape_fbref()
        rows     = parse_rows(raw_rows)
        if args.save:
            save_csv(rows, CSV_FILE)

    if not rows:
        print("No players with G+A found.")
        sys.exit(1)

    clubs = aggregate_clubs(rows)
    if args.goals:
        clubs = sorted(clubs, key=lambda x: x["goals"], reverse=True)

    if args.club:
        print_club(clubs, args.club)
    else:
        print_leaderboard(clubs, top=args.top)


if __name__ == "__main__":
    main()
