"""
squad_mapper.py
Fetches the full 2026 FIFA World Cup squads from Wikipedia at startup,
building a complete player → club mapping (~1,248 players across 48 teams).
Results are cached locally so Wikipedia is only hit once per day.
"""

import json
import re
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CACHE_FILE = Path(__file__).parent / ".squad_cache.json"
WIKI_API   = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE  = "2026_FIFA_World_Cup_squads"


def _fetch_from_wikipedia() -> dict[str, str]:
    """Scrape Wikipedia squad tables → {player_name: club}."""
    params = {
        "action": "parse",
        "page": WIKI_PAGE,
        "prop": "text",
        "format": "json",
        "disablelimitreport": "1",
    }
    headers = {"User-Agent": "WC2026-club-tracker/1.0 (research tool)"}

    resp = requests.get(WIKI_API, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    html = resp.json()["parse"]["text"]["*"]

    soup = BeautifulSoup(html, "html.parser")
    mapping: dict[str, str] = {}

    for table in soup.find_all("table", class_="wikitable"):
        header_row = table.find("tr")
        if not header_row:
            continue

        headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        if "Player" not in headers or "Club" not in headers:
            continue

        pi = headers.index("Player")
        ci = headers.index("Club")

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(pi, ci):
                continue

            name = cells[pi].get_text(strip=True)
            club = cells[ci].get_text(strip=True)

            # Strip "(captain)" etc.
            name = re.sub(r"\s*\(.*?\)\s*", "", name).strip()
            name = re.sub(r"\s+", " ", name).strip()

            if name and club and name not in ("Player",):
                mapping[name] = club

    return mapping


def _load_cache() -> dict | None:
    """Return cached mapping if it was fetched today, else None."""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if data.get("date") == str(date.today()):
            return data["mapping"]
    except Exception:
        pass
    return None


def _save_cache(mapping: dict[str, str]) -> None:
    payload = {"date": str(date.today()), "mapping": mapping}
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_player_club_map(force_refresh: bool = False) -> dict[str, str]:
    """
    Return full player→club dict.
    Fetches from Wikipedia once per day; uses cache otherwise.
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            return cached

    mapping = _fetch_from_wikipedia()
    _save_cache(mapping)
    return mapping


def lookup(name: str, mapping: dict[str, str]) -> str:
    """
    Look up a player's club, trying:
    1. Exact match
    2. Accent-stripped match (handles FBref name variants)
    3. Returns "Unknown" if not found
    """
    if name in mapping:
        return mapping[name]

    import unicodedata
    def strip(s: str) -> str:
        return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()

    stripped = strip(name)
    for k, v in mapping.items():
        if strip(k) == stripped:
            return v

    return "Unknown"


if __name__ == "__main__":
    print("Fetching full squad mapping from Wikipedia...")
    t0 = time.time()
    m = get_player_club_map(force_refresh=True)
    print(f"Done in {time.time()-t0:.1f}s — {len(m)} players mapped")
    print("\nSample (first 20):")
    for name, club in list(m.items())[:20]:
        print(f"  {name:<30} → {club}")
