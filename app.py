import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="WC 2026 Club Tracker", page_icon="⚽", layout="wide")

FBREF_URL  = "https://fbref.com/en/comps/1/stats/World-Cup-Stats"
FOTMOB_URL = "https://www.fotmob.com/en-GB/leagues/77/stats/season/24254/players/_goals_and_goal_assist/world-cup"
CSV_CACHE  = Path(__file__).parent / ".wc2026_cache.csv"

# ── Parser ────────────────────────────────────────────────────────────────────
def parse_paste(raw: str) -> pd.DataFrame:
    """
    Handles both FBref and FotMob paste formats.

    FotMob (2 cols):   Jonathan David    3
    FBref  (full row): 1 Jonathan David FW Canada 26 Juventus 2000 2 2 150 1.7 3 0 3 ...
    """
    rows = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Try to detect FBref full-row format (has many tab/space separated cols)
        # FBref cols: Rk Player Pos Squad Age Club Born MP Starts Min 90s Gls Ast G+A ...
        parts = re.split(r'\t', line)
        if len(parts) >= 13:
            # Tab-separated FBref export
            try:
                player  = parts[1].strip()
                club    = parts[5].strip()
                goals   = int(parts[11] or 0)
                assists = int(parts[12] or 0)
                ga      = int(parts[13] or 0) if len(parts) > 13 else goals + assists
                if player and player.lower() not in ("player",""):
                    rows.append({"player": player, "club": club or "Unknown",
                                 "goals": goals, "assists": assists, "ga": ga})
                continue
            except (ValueError, IndexError):
                pass

        # FotMob / simple format: "Name    N"
        m = re.search(r"^(.*?)\s{2,}(\d+)\s*$", line)
        if not m:
            m = re.search(r"^(.*?)\t(\d+)\s*$", line)
        if not m:
            m = re.search(r"^(.*?)\s+(\d+)\s*$", line)
        if not m:
            continue

        name = m.group(1).strip()
        ga   = int(m.group(2))

        # Strip FBref noise
        name = re.sub(r"^\d+\s+", "", name)
        name = re.sub(r"xG\s*\+?\s*xA\s*:?\s*[\d.]+", "", name, flags=re.I).strip()

        if name.lower() in ("player","#","stats","all","name","") or not name:
            continue
        if not (0 < ga < 40):
            continue

        rows.append({"player": name, "club": "Unknown", "goals": 0, "assists": 0, "ga": ga})

    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["player","club","goals","assists","ga"])


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
    tab_fbref, tab_fotmob = st.tabs(["FBref", "FotMob"])

    with tab_fbref:
        st.markdown(f"""
1. Open [FBref WC Stats]({FBREF_URL})
2. Scroll to **Player Standard Stats**
3. Click the small **spreadsheet icon** (↗ top right of table) to download CSV — or just **select all & copy** the table
4. Paste below ↓
""")

    with tab_fotmob:
        st.markdown(f"""
1. Open [FotMob WC Stats]({FOTMOB_URL})
2. Click **See all** under Goals + Assists
3. Select all & copy (Ctrl+A, Ctrl+C)
4. Paste below ↓
""")

    paste = st.text_area(
        "Paste data here",
        height=300,
        placeholder="Paste FBref or FotMob stats here...",
    )

    st.divider()
    sort_by = st.radio("Sort by", ["G+A", "Goals", "Assists", "Players", "Club (A–Z)"], index=0)
    search  = st.text_input("🔍 Filter clubs", placeholder="e.g. Arsenal")
    top_n   = st.slider("Show top N clubs", 5, 60, 20)

# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("## 2026 FIFA World Cup — Club G+A Leaderboard")

if not paste.strip():
    st.info("👈 Paste FBref or FotMob data in the sidebar to load the leaderboard.")
    st.markdown("""
| Source | Pros | How |
|--------|------|-----|
| **FBref** | Has Goals + Assists separately, Club column built-in | Copy table or download CSV |
| **FotMob** | Cleaner paste, just name + G+A total | See all → Ctrl+A Ctrl+C |
""")
    st.stop()

# Parse
df = parse_paste(paste)

if df.empty:
    st.error("Could not parse any data. Try copying the table again.")
    st.stop()

has_club = df["club"].ne("Unknown").any()
has_goals = df["goals"].sum() > 0

# ── Metrics ───────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total G+A",     int(df["ga"].sum()))
c2.metric("Goals",         int(df["goals"].sum()) if has_goals else "—")
c3.metric("Assists",       int(df["assists"].sum()) if has_goals else "—")
c4.metric("Players",       len(df))
c5.metric("Clubs",         df[df["club"]!="Unknown"]["club"].nunique() if has_club else "—")

st.caption(f"Parsed {len(df)} players · {datetime.now().strftime('%d %b %Y %H:%M')}")
st.divider()

# ── Club leaderboard (only if club info available) ────────────────────────────
if has_club:
    clubs_df = aggregate_clubs(df)

    sort_map = {"G+A":"ga","Goals":"goals","Assists":"assists","Players":"players","Club (A–Z)":"club"}
    sort_col = sort_map[sort_by]
    clubs_df = clubs_df.sort_values(sort_col, ascending=(sort_col=="club")).reset_index(drop=True)

    if search.strip():
        clubs_df = clubs_df[clubs_df["club"].str.contains(search.strip(), case=False, na=False)]

    clubs_df = clubs_df.head(top_n)
    max_ga        = clubs_df["ga"].max() if not clubs_df.empty else 1
    max_player_ga = int(df["ga"].max())  if not df.empty       else 10

    MEDALS = {0:"🥇", 1:"🥈", 2:"🥉"}
    left, right = st.columns([3, 2], gap="large")

    with left:
        st.markdown("### Club breakdown")
        for i, row in enumerate(clubs_df.itertuples()):
            medal = MEDALS.get(i, f"`{i+1}`")
            pct   = int((row.ga / max_ga) * 100)
            label = f"{medal} **{row.club}** — {row.ga} G+A"
            if has_goals:
                label += f" ({row.goals}G {row.assists}A)"
            label += f" · {row.players}p"

            with st.expander(label, expanded=(i < 3)):
                st.markdown(
                    f"<div style='background:#1e2130;border-radius:4px;height:6px;margin-bottom:10px'>"
                    f"<div style='background:#1D9E75;width:{pct}%;height:100%;border-radius:4px'></div></div>",
                    unsafe_allow_html=True,
                )
                cols = ["player","goals","assists","ga"] if has_goals else ["player","ga"]
                bd = df[df["club"]==row.club][cols].sort_values("ga", ascending=False).reset_index(drop=True)
                bd.index += 1
                bd.columns = (["Player","G","A","G+A"] if has_goals else ["Player","G+A"])
                st.dataframe(bd, use_container_width=True,
                    column_config={"G+A": st.column_config.ProgressColumn(
                        "G+A", min_value=0, max_value=max_player_ga, format="%d")})

    with right:
        st.markdown("### Top clubs")
        highlight = sort_map.get(sort_by, "ga")
        if highlight not in ("goals","assists","ga"):
            highlight = "ga"
        chart = clubs_df.set_index("club")[[highlight]].head(15)
        chart.columns = [sort_by if sort_by in ("Goals","Assists","G+A") else "G+A"]
        color = {"Goals":"#E24B4A","Assists":"#378ADD"}.get(sort_by,"#1D9E75")
        st.bar_chart(chart, color=color, height=480)

else:
    # FotMob paste — no club info, show player leaderboard instead
    st.info("ℹ️ FotMob data doesn't include club names. Showing player leaderboard. Use FBref paste for club breakdown.")
    st.markdown("### Player G+A Leaderboard")
    player_df = df[["player","ga"]].sort_values("ga", ascending=False).reset_index(drop=True)
    player_df.index += 1
    player_df.columns = ["Player","G+A"]

    left, right = st.columns([3,2], gap="large")
    with left:
        st.dataframe(player_df, use_container_width=True, height=500,
            column_config={"G+A": st.column_config.ProgressColumn(
                "G+A", min_value=0, max_value=int(df["ga"].max()), format="%d")})
    with right:
        chart = player_df.head(15).set_index("Player")
        st.bar_chart(chart, color="#1D9E75", height=480)

# ── All players ───────────────────────────────────────────────────────────────
with st.expander("📋 All parsed players"):
    cols = ["player","club","goals","assists","ga"] if has_goals else ["player","ga"]
    all_d = df[cols].sort_values("ga", ascending=False).reset_index(drop=True)
    all_d.index += 1
    st.dataframe(all_d, use_container_width=True, height=400)
