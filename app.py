import re
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import pandas as pd
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="WC 2026 Club Tracker",
    page_icon="⚽",
    layout="wide",
)

FBREF_URL = "https://fbref.com/en/comps/1/stats/World-Cup-Stats"
TABLE_ID  = "stats_standard"
CSV_CACHE = Path(__file__).parent / ".wc2026_cache.csv"

# ── Scraper ───────────────────────────────────────────────────────────────────
def scrape_fbref() -> pd.DataFrame:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        st.error("Playwright not installed. Run: `pip install playwright && playwright install chromium`")
        st.stop()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ))
        page.goto(FBREF_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector(f"#{TABLE_ID}", timeout=20000)
        except PWTimeout:
            browser.close()
            st.error("Timed out waiting for FBref table. Try again.")
            st.stop()

        time.sleep(2)

        data = page.evaluate(f"""
        () => {{
            const table = document.getElementById('{TABLE_ID}');
            if (!table) return null;
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
            return rows;
        }}
        """)
        browser.close()

    if not data:
        st.error("No data returned from FBref.")
        st.stop()

    rows = []
    for row in data:
        player = row.get("player", "").strip()
        club   = row.get("club", "").strip()
        squad  = row.get("squad", "").strip()
        if not player or player.lower() == "player":
            continue
        try:
            goals   = int(row.get("goals",   0) or 0)
            assists = int(row.get("assists",  0) or 0)
            ga      = int(row.get("goals_assists", 0) or 0) or (goals + assists)
        except (ValueError, TypeError):
            goals, assists, ga = 0, 0, 0

        if ga == 0:
            continue

        rows.append({
            "player":  player,
            "squad":   squad,
            "club":    club if club else "Unknown",
            "goals":   goals,
            "assists": assists,
            "ga":      ga,
        })

    df = pd.DataFrame(rows)
    df.to_csv(CSV_CACHE, index=False)
    return df


def load_cache() -> pd.DataFrame | None:
    if CSV_CACHE.exists():
        try:
            return pd.read_csv(CSV_CACHE).fillna(0)
        except Exception:
            return None
    return None


def aggregate_clubs(df: pd.DataFrame) -> pd.DataFrame:
    known = df[df["club"] != "Unknown"]
    clubs = (
        known.groupby("club")
        .agg(goals=("goals","sum"), assists=("assists","sum"),
             ga=("ga","sum"), players=("player","count"))
        .reset_index()
        .sort_values("ga", ascending=False)
        .reset_index(drop=True)
    )
    clubs.index += 1
    return clubs


# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
div[data-testid="stExpander"] > details > summary span { font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚽ WC 2026 Club Tracker")
    st.caption("Data source: FBref (auto-scraped)")
    st.divider()

    col1, col2 = st.columns(2)
    scrape_btn   = col1.button("🔄 Scrape FBref", use_container_width=True, type="primary")
    use_cache    = col2.button("📂 Load cache",   use_container_width=True)

    st.divider()
    sort_by = st.radio("Sort by", ["G+A", "Goals", "Assists", "Players", "Club (A–Z)"], index=0)
    search  = st.text_input("🔍 Filter clubs", placeholder="e.g. Arsenal")
    top_n   = st.slider("Show top N clubs", 5, 50, 20)

    st.divider()
    st.caption(f"Source: [FBref]({FBREF_URL})")
    if CSV_CACHE.exists():
        mtime = datetime.fromtimestamp(CSV_CACHE.stat().st_mtime)
        st.caption(f"Cache: {mtime.strftime('%d %b %Y %H:%M')}")
    else:
        st.caption("No cache yet — click Scrape FBref")

# ── Session state ─────────────────────────────────────────────────────────────
if "df" not in st.session_state:
    st.session_state.df = None

# ── Load data ─────────────────────────────────────────────────────────────────
if scrape_btn:
    with st.spinner("Launching headless browser and scraping FBref…"):
        st.session_state.df = scrape_fbref()
    st.success(f"Scraped {len(st.session_state.df)} players!")

elif use_cache:
    cached = load_cache()
    if cached is not None:
        st.session_state.df = cached
        st.success(f"Loaded {len(cached)} players from cache.")
    else:
        st.warning("No cache found. Click **Scrape FBref** first.")

# Auto-load cache on first run if available
if st.session_state.df is None:
    cached = load_cache()
    if cached is not None:
        st.session_state.df = cached

df = st.session_state.df

# ── Empty state ───────────────────────────────────────────────────────────────
if df is None:
    st.markdown("## 2026 FIFA World Cup — Club G+A Leaderboard")
    st.info("👈 Click **Scrape FBref** in the sidebar to load the latest stats.")
    with st.expander("How it works"):
        st.markdown("""
- Clicks **Scrape FBref** to launch a headless Chrome browser
- Loads the [FBref World Cup Stats page]({FBREF_URL}) and parses the Player Standard Stats table
- FBref has a **Club column** built-in, so no manual mapping needed
- Results are cached locally — click **Load cache** next time for instant load
- Click **Scrape FBref** again any day to refresh with latest stats
        """)
    st.stop()

# ── Metrics ───────────────────────────────────────────────────────────────────
st.markdown("## 2026 FIFA World Cup — Club G+A Leaderboard")

clubs_df = aggregate_clubs(df)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total G+A",  int(df["ga"].sum()))
c2.metric("Total Goals",    int(df["goals"].sum()))
c3.metric("Total Assists",  int(df["assists"].sum()))
c4.metric("Players",        len(df))
c5.metric("Clubs",          len(clubs_df))

scraped_at = datetime.fromtimestamp(CSV_CACHE.stat().st_mtime).strftime("%d %b %Y %H:%M") if CSV_CACHE.exists() else "just now"
st.caption(f"Last scraped: {scraped_at} · Source: FBref (Opta)")
st.divider()

# ── Sort & filter ─────────────────────────────────────────────────────────────
sort_map = {
    "G+A":       "ga",
    "Goals":     "goals",
    "Assists":   "assists",
    "Players":   "players",
    "Club (A–Z)":"club",
}
sort_col = sort_map[sort_by]
asc      = sort_col == "club"
clubs_df = clubs_df.sort_values(sort_col, ascending=asc).reset_index(drop=True)
clubs_df.index += 1

if search.strip():
    clubs_df = clubs_df[clubs_df["club"].str.contains(search.strip(), case=False, na=False)]

clubs_df = clubs_df.head(top_n)
max_ga        = clubs_df["ga"].max()   if not clubs_df.empty else 1
max_player_ga = int(df["ga"].max())    if not df.empty       else 10

# ── Layout ────────────────────────────────────────────────────────────────────
left, right = st.columns([3, 2], gap="large")
MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}

with left:
    st.markdown("### Club breakdown")
    for i, row in enumerate(clubs_df.itertuples()):
        medal = MEDALS.get(i, f"`{i+1}`")
        pct   = int((row.ga / max_ga) * 100)

        with st.expander(
            f"{medal} **{row.club}** — {row.ga} G+A "
            f"({row.goals}G {row.assists}A) · {row.players} player{'s' if row.players != 1 else ''}",
            expanded=(i < 3),
        ):
            st.markdown(
                f"<div style='background:#1e2130;border-radius:4px;height:6px;margin-bottom:10px'>"
                f"<div style='background:#1D9E75;width:{pct}%;height:100%;border-radius:4px'></div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            bd = (
                df[df["club"] == row.club][["player", "squad", "goals", "assists", "ga"]]
                .sort_values("ga", ascending=False)
                .reset_index(drop=True)
            )
            bd.index += 1
            bd.columns = ["Player", "National Team", "G", "A", "G+A"]
            st.dataframe(
                bd,
                use_container_width=True,
                column_config={
                    "G+A": st.column_config.ProgressColumn(
                        "G+A", min_value=0, max_value=max_player_ga, format="%d"
                    )
                },
            )

with right:
    st.markdown("### Top clubs chart")

    highlight_col = sort_map.get(sort_by, "ga")
    if highlight_col not in ("goals", "assists", "ga"):
        highlight_col = "ga"

    chart_data = clubs_df.set_index("club")[[highlight_col]].head(15)
    chart_data.columns = [sort_by if sort_by in ("Goals","Assists","G+A") else "G+A"]
    color = {"Goals": "#E24B4A", "Assists": "#378ADD"}.get(sort_by, "#1D9E75")
    st.bar_chart(chart_data, color=color, height=480)

# ── All players table ─────────────────────────────────────────────────────────
with st.expander("📋 All players"):
    all_d = df[["player","squad","club","goals","assists","ga"]].sort_values("ga", ascending=False).reset_index(drop=True)
    all_d.index += 1
    all_d.columns = ["Player","National Team","Club","G","A","G+A"]
    st.dataframe(all_d, use_container_width=True, height=400)
