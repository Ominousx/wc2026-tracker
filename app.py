import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import pandas as pd
import streamlit as st

st.set_page_config(page_title="WC 2026 Club Tracker", page_icon="⚽", layout="wide")

FBREF_URL = "https://fbref.com/en/comps/1/stats/World-Cup-Stats"

# ── Parser ────────────────────────────────────────────────────────────────────
def clean_club(raw: str) -> str:
    """Strip FBref club prefix: '1.it Juventus' → 'Juventus'"""
    return re.sub(r'^\d+\.[a-z]{2,3}\s+', '', raw).strip()

def parse_fbref_tsv(raw: str) -> pd.DataFrame:
    """
    Parse FBref Player Standard Stats tab-separated paste.
    Columns (0-indexed):
      0=Rk  1=Player  2=Pos  3=Squad  4=Age  5=Club  6=Born
      7=MP  8=Starts  9=Min  10=90s
      11=Gls  12=Ast  13=G+A  ...
    """
    rows = []
    seen = set()

    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')

        # Must have at least 14 columns for G+A
        if len(parts) < 14:
            continue

        player   = parts[1].strip()
        raw_club = parts[5].strip()
        club     = clean_club(raw_club) if raw_club else "Unknown"

        # Skip header rows
        if player.lower() in ('player', 'rk', '') or not player:
            continue

        # Deduplicate (FBref repeats header rows mid-table)
        key = player.lower()
        if key in seen:
            continue
        seen.add(key)

        try:
            goals   = int(parts[11]) if parts[11].strip() else 0
            assists = int(parts[12]) if parts[12].strip() else 0
            ga      = int(parts[13]) if parts[13].strip() else goals + assists
        except (ValueError, IndexError):
            goals, assists, ga = 0, 0, 0

        squad = parts[3].strip() if len(parts) > 3 else ""
        # Strip flag prefix from squad: "ca Canada" → "Canada"
        squad = re.sub(r'^[a-z]{2}\s+', '', squad).strip()

        if not club:
            club = "Unknown"

        rows.append({
            "player":  player,
            "squad":   squad,
            "club":    club,
            "goals":   goals,
            "assists": assists,
            "ga":      ga,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["player","squad","club","goals","assists","ga"])

def aggregate_clubs(df: pd.DataFrame) -> pd.DataFrame:
    known = df[df["club"] != "Unknown"]
    return (
        known.groupby("club")
        .agg(goals=("goals","sum"), assists=("assists","sum"),
             ga=("ga","sum"), players=("player","count"))
        .reset_index()
        .sort_values("ga", ascending=False)
        .reset_index(drop=True)
    )

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚽ WC 2026 Club Tracker")
    st.divider()

    st.markdown("**How to get data:**")
    st.markdown(f"""
1. Open [FBref World Cup Stats]({FBREF_URL})
2. Scroll to **Player Standard Stats** table
3. Look for the small **Share & Export** button above the table → click **Get table as CSV (for Excel)**
4. That opens a page of raw text — **Ctrl+A, Ctrl+C**
5. Paste below ↓

*Or just select all rows in the table directly and copy.*
""")

    paste = st.text_area("Paste FBref data here", height=280,
        placeholder="Paste the FBref Player Standard Stats table here...")

    st.divider()
    sort_by = st.radio("Sort by", ["G+A","Goals","Assists","Players","Club (A–Z)"], index=0)
    search  = st.text_input("🔍 Filter clubs", placeholder="e.g. Arsenal")
    top_n   = st.slider("Show top N clubs", 5, 80, 25)
    only_ga = st.checkbox("Only show players with G+A > 0", value=True)

# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("## 2026 FIFA World Cup — Club G+A Leaderboard")

if not paste.strip():
    st.info("👈 Paste the FBref Player Standard Stats table in the sidebar.")
    with st.expander("ℹ️ Step-by-step"):
        st.markdown(f"""
**Every matchday, ~30 seconds:**

1. Go to [{FBREF_URL}]({FBREF_URL})
2. Scroll to the big **Player Standard Stats** table
3. Click **Share & Export** (top right of table) → **Get table as CSV**
4. New page opens with raw text — press **Ctrl+A** then **Ctrl+C**
5. Come back here, paste in the sidebar → done

The **G+A**, **Goals**, **Assists** and **Club** columns are all parsed automatically.
No mapping needed — FBref has the club name directly in the table.
        """)
    st.stop()

# Parse
df = parse_fbref_tsv(paste)

if df.empty:
    st.error("Could not parse. Make sure you're pasting the FBref CSV export (tab-separated).")
    st.stop()

if only_ga:
    df_display = df[df["ga"] > 0]
else:
    df_display = df

unknown = df_display[df_display["club"] == "Unknown"]
known   = df_display[df_display["club"] != "Unknown"]

# ── Metrics ───────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total G+A",    int(df_display["ga"].sum()))
c2.metric("Goals",        int(df_display["goals"].sum()))
c3.metric("Assists",      int(df_display["assists"].sum()))
c4.metric("Players",      len(df_display))
c5.metric("Clubs",        known["club"].nunique())

st.caption(f"Parsed {len(df)} total players · {len(df_display)} with G+A > 0 · "
           f"{datetime.now().strftime('%d %b %Y %H:%M')} · Source: FBref")
st.divider()

# ── Aggregate & sort ──────────────────────────────────────────────────────────
clubs_df = aggregate_clubs(df_display)

sort_map = {"G+A":"ga","Goals":"goals","Assists":"assists",
            "Players":"players","Club (A–Z)":"club"}
sort_col = sort_map[sort_by]
clubs_df = clubs_df.sort_values(sort_col, ascending=(sort_col=="club")).reset_index(drop=True)

if search.strip():
    clubs_df = clubs_df[clubs_df["club"].str.contains(search.strip(), case=False, na=False)]

clubs_df = clubs_df.head(top_n)
max_ga        = clubs_df["ga"].max()   if not clubs_df.empty else 1
max_player_ga = int(df_display["ga"].max()) if not df_display.empty else 10

# ── Layout ────────────────────────────────────────────────────────────────────
MEDALS = {0:"🥇", 1:"🥈", 2:"🥉"}
left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown("### Club breakdown")
    for i, row in enumerate(clubs_df.itertuples()):
        medal = MEDALS.get(i, f"`{i+1}`")
        pct   = int((row.ga / max_ga) * 100)

        with st.expander(
            f"{medal} **{row.club}** — {row.ga} G+A "
            f"({row.goals}G {row.assists}A) · {row.players}p",
            expanded=(i < 3),
        ):
            st.markdown(
                f"<div style='background:#1e2130;border-radius:4px;height:6px;margin-bottom:10px'>"
                f"<div style='background:#1D9E75;width:{pct}%;height:100%;border-radius:4px'>"
                f"</div></div>", unsafe_allow_html=True,
            )
            bd = (
                df_display[df_display["club"] == row.club]
                [["player","squad","goals","assists","ga"]]
                .sort_values("ga", ascending=False)
                .reset_index(drop=True)
            )
            bd.index += 1
            bd.columns = ["Player","National Team","G","A","G+A"]
            st.dataframe(bd, use_container_width=True,
                column_config={"G+A": st.column_config.ProgressColumn(
                    "G+A", min_value=0, max_value=max_player_ga, format="%d")})

with right:
    st.markdown("### Top clubs")
    highlight = sort_map.get(sort_by, "ga")
    if highlight not in ("goals","assists","ga"):
        highlight = "ga"
    chart = clubs_df.set_index("club")[[highlight]].head(20)
    chart.columns = [sort_by if sort_by in ("Goals","Assists","G+A") else "G+A"]
    color = {"Goals":"#E24B4A","Assists":"#378ADD"}.get(sort_by,"#1D9E75")
    st.bar_chart(chart, color=color, height=520)

# ── Unknown clubs ─────────────────────────────────────────────────────────────
if not unknown.empty:
    st.divider()
    with st.expander(f"⚠ {len(unknown)} players with missing club"):
        st.caption("FBref had no club listed for these players.")
        u = unknown[["player","squad","goals","assists","ga"]].reset_index(drop=True)
        u.index += 1
        st.dataframe(u, use_container_width=True)

# ── Full table ────────────────────────────────────────────────────────────────
with st.expander("📋 All players"):
    all_d = df_display[["player","squad","club","goals","assists","ga"]]\
        .sort_values("ga", ascending=False).reset_index(drop=True)
    all_d.index += 1
    all_d.columns = ["Player","National Team","Club","G","A","G+A"]
    st.dataframe(all_d, use_container_width=True, height=400)
