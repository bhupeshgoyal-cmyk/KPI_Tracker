import pandas as pd
import streamlit as st
from datetime import date
from auth import require_auth, logout
from data_loader import load_kpis, load_actuals, enrich_with_rag, append_actual
from ai_engine import generate_insights
import config

st.set_page_config(
    page_title="KPI Dashboard",
    page_icon="📊",
    layout="wide",
)

# =============================================================================
# Auth & data
# =============================================================================
user       = require_auth()
department = user["department"]

with st.sidebar:
    st.markdown(f"### {user['name']}")
    st.caption(user["email"])
    st.caption(f"Department: **{department}**")
    st.divider()

    # Month selector — defaults to current month
    today         = date.today()
    current_month = today.strftime("%Y-%m")
    months        = [
        (date(today.year, m, 1)).strftime("%Y-%m")
        for m in range(1, 13)
    ]
    selected_month = st.selectbox(
        "Month",
        options=months,
        index=months.index(current_month),
    )

    st.divider()
    if st.button("Sign out", use_container_width=True):
        logout()

try:
    kpis_df    = load_kpis(department, selected_month)
    actuals_df = load_actuals(department, selected_month)
    enriched   = enrich_with_rag(kpis_df, actuals_df)
except Exception as e:
    st.error(f"Could not load data from Google Sheets: {e}")
    st.stop()

if kpis_df.empty:
    st.warning(f"No KPIs found for **{department}** in **{selected_month}**. Check the KPI Registry sheet.")
    st.stop()

# =============================================================================
# Helpers
# =============================================================================
RAG_BADGE       = {"Green": "🟢 Green", "Amber": "🟡 Amber", "Red": "🔴 Red", "Unknown": "⚪ No Data"}
RAG_DELTA_COLOR = {"Green": "normal",   "Amber": "off",       "Red": "inverse", "Unknown": "off"}

def _fmt(value, fallback="—"):
    return f"{value:.2f}" if pd.notna(value) else fallback

def _variance_label(variance, target):
    if pd.isna(variance) or pd.isna(target) or target == 0:
        return None
    pct  = (variance / target) * 100
    sign = "+" if variance >= 0 else ""
    return f"{sign}{variance:.2f}  ({sign}{pct:.1f}%)"

def _render_insight(text: str) -> None:
    """Parse SITUATION / SCRUTINY / ACTION sections and render with coloured borders."""
    section_styles = {
        "SITUATION:": ("📊", "#1f77b4"),
        "SCRUTINY:":  ("🔍", "#ff7f0e"),
        "ACTION:":    ("⚡", "#d62728"),
    }
    current_label, current_lines = None, []

    def _flush(label, lines):
        if not label or not lines:
            return
        icon, color = section_styles.get(label, ("", "#888"))
        body = " ".join(lines).strip()
        st.markdown(f"**{icon} {label.rstrip(':')}**")
        st.markdown(
            f"<div style='border-left:3px solid {color};"
            f"padding:0.5rem 1rem;margin-bottom:1rem'>{body}</div>",
            unsafe_allow_html=True,
        )

    for line in text.splitlines():
        stripped = line.strip()
        matched  = next((k for k in section_styles if stripped.upper().startswith(k)), None)
        if matched:
            _flush(current_label, current_lines)
            current_label = matched
            current_lines = [stripped[len(matched):].strip()]
        elif stripped:
            current_lines.append(stripped)

    _flush(current_label, current_lines)
    if current_label is None:          # model returned free-form text
        st.markdown(text)

# =============================================================================
# 1. Welcome
# =============================================================================
st.title("📊 KPI Dashboard")
st.markdown(f"**{department}** · {selected_month}")
st.divider()

# =============================================================================
# 2. KPI Summary (metric cards)
# =============================================================================
raw_rag = enriched["RAG Status"]

st.subheader("KPI Summary")
b1, b2, b3, b4 = st.columns(4)
b1.metric("Total KPIs", len(enriched))
b2.metric("🟢 Green",   int((raw_rag == "Green").sum()))
b3.metric("🟡 Amber",   int((raw_rag == "Amber").sum()))
b4.metric("🔴 Red",     int((raw_rag == "Red").sum()))

st.write("")

COLS = 3
for chunk in [enriched.iloc[i:i+COLS] for i in range(0, len(enriched), COLS)]:
    cols = st.columns(COLS)
    for col, (_, kpi) in zip(cols, chunk.iterrows()):
        actual   = kpi["Latest Actual"]
        target   = kpi[config.KPI_COL_TARGET]
        rag      = kpi["RAG Status"]
        variance = (actual - target) if pd.notna(actual) and pd.notna(target) else None
        with col:
            st.metric(
                label=f"{RAG_BADGE[rag]}  ·  {kpi[config.KPI_COL_NAME]}",
                value=_fmt(actual),
                delta=_variance_label(variance, target),
                delta_color=RAG_DELTA_COLOR[rag],
                help=(
                    f"**KPI Code:** {kpi[config.KPI_COL_CODE]}\n\n"
                    f"**Target:** {_fmt(target)}\n\n"
                    f"**Thresholds:** "
                    f"🟢 ≥ {_fmt(kpi[config.KPI_COL_GREEN])}  "
                    f"🟡 ≥ {_fmt(kpi[config.KPI_COL_AMBER])}  "
                    f"🔴 < {_fmt(kpi[config.KPI_COL_AMBER])}"
                ),
            )

st.divider()

# =============================================================================
# 3. KPI Table
# =============================================================================
st.subheader("KPI Table")

table_df = enriched[[
    config.KPI_COL_CODE,
    config.KPI_COL_NAME,
    config.KPI_COL_TARGET,
    "Latest Actual",
    "RAG Status",
]].copy()
table_df["RAG Status"] = table_df["RAG Status"].map(lambda s: RAG_BADGE.get(s, s))
table_df = table_df.rename(columns={
    config.KPI_COL_CODE:   "Code",
    config.KPI_COL_NAME:   "KPI Name",
    config.KPI_COL_TARGET: "Target",
})

st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Target":        st.column_config.NumberColumn(format="%.2f"),
        "Latest Actual": st.column_config.NumberColumn(format="%.2f"),
    },
)

st.divider()

# =============================================================================
# 4. Input Form
# =============================================================================
st.subheader("📝 Submit Weekly Actual")

kpi_options    = {
    f"{r[config.KPI_COL_NAME]} ({r[config.KPI_COL_CODE]})": r[config.KPI_COL_CODE]
    for _, r in kpis_df.iterrows()
}
selected_label = st.selectbox("Select KPI", options=list(kpi_options.keys()))
selected_code  = kpi_options[selected_label]

kpi_history = (
    actuals_df[actuals_df[config.ACTUAL_COL_KPI_CODE] == selected_code]
    if not actuals_df.empty else pd.DataFrame()
)

if not kpi_history.empty:
    last         = kpi_history.sort_values(config.ACTUAL_COL_DATE).iloc[-1]
    last_date    = pd.to_datetime(last[config.ACTUAL_COL_DATE]).strftime("%d %b %Y")
    last_comment = last[config.ACTUAL_COL_COMMENT] or "—"
    with st.container(border=True):
        st.caption(f"Last submission — {last_date}")
        lc1, lc2 = st.columns(2)
        lc1.metric("Previous Actual", _fmt(last[config.ACTUAL_COL_ACTUAL]))
        lc2.markdown(f"**Comment**\n\n{last_comment}")
else:
    st.info("No previous submission found for this KPI.")

with st.form("actuals_form", clear_on_submit=True):
    actual_value = st.number_input("Actual value", min_value=0.0, step=0.01, format="%.2f")
    comment      = st.text_area(
        "Comment",
        placeholder="Briefly explain the result — what drove it, any context…",
        max_chars=500,
    )
    fc1, fc2 = st.columns(2)
    fc1.text_input("Date",         value=date.today().strftime("%Y-%m-%d"), disabled=True)
    fc2.text_input("Submitted by", value=user["email"],                     disabled=True)
    submitted = st.form_submit_button("Submit", use_container_width=True, type="primary")

if submitted:
    try:
        append_actual(
            date=date.today().strftime("%Y-%m-%d"),
            kpi_code=selected_code,
            actual=actual_value,
            comment=comment.strip(),
            updated_by=user["email"],
        )
        st.success(f"Saved! {selected_label} → {actual_value:.2f} on {date.today().strftime('%d %b %Y')}")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to save: {e}")

st.divider()

# =============================================================================
# 5. Latest Comments
# =============================================================================
st.subheader("💬 Latest Comments")

if actuals_df.empty:
    st.info("No comments submitted yet.")
else:
    comments = (
        actuals_df[actuals_df[config.ACTUAL_COL_COMMENT].str.strip().ne("")]
        .sort_values(config.ACTUAL_COL_DATE, ascending=False)
        .groupby(config.ACTUAL_COL_KPI_CODE, sort=False)
        .first()
        .reset_index()
        .merge(
            kpis_df[[config.KPI_COL_CODE, config.KPI_COL_NAME]],
            left_on=config.ACTUAL_COL_KPI_CODE,
            right_on=config.KPI_COL_CODE,
            how="left",
        )
        .sort_values(config.ACTUAL_COL_DATE, ascending=False)
    )

    if comments.empty:
        st.info("No comments submitted yet.")
    else:
        for _, row in comments.iterrows():
            entry_date = pd.to_datetime(row[config.ACTUAL_COL_DATE]).strftime("%d %b %Y")
            st.markdown(f"**{row[config.KPI_COL_NAME]}** → {row[config.ACTUAL_COL_COMMENT]}")
            st.caption(f"{entry_date} · {row[config.ACTUAL_COL_UPDATED_BY]}")
            st.divider()

# =============================================================================
# 6. AI Insights — Performance Summary
# =============================================================================
st.subheader("🧠 Performance Summary")

if st.button("Generate Insight", type="primary"):
    with st.spinner("Analysing performance data…"):
        st.session_state["insight"] = generate_insights(department, enriched)

if "insight" in st.session_state:
    _render_insight(st.session_state["insight"])
    if st.button("Clear", key="clear_insight"):
        del st.session_state["insight"]
        st.rerun()
