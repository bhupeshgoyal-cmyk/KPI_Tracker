import pandas as pd
import streamlit as st
from datetime import date
from auth import require_auth, logout
from data_loader import (
    load_kpis, load_actuals, load_available_months,
    enrich_with_rag, compute_mtd, append_actual, parse_month,
)
from ai_engine import generate_insights
import config

st.set_page_config(
    page_title="KPI Dashboard",
    page_icon="📊",
    layout="wide",
)

# =============================================================================
# Auth
# =============================================================================
user       = require_auth()
department = user["department"]

# =============================================================================
# Sidebar
# =============================================================================
with st.sidebar:
    st.markdown(f"### {user['name']}")
    st.caption(user["email"])
    st.caption(f"Department: **{department}**")
    st.divider()

    # Month selector — sourced from KPI Registry (FY order)
    available_months = load_available_months(department)

    if not available_months:
        st.warning("No months found in KPI Registry.")
        selected_month = ""
    else:
        # Default to current month if present, otherwise the latest month <= today
        today = date.today()
        today_ts = pd.Timestamp(today)
        
        # Try multiple formats for current month
        current_month_candidates = [
            today.strftime("%b-%Y"),  # Apr-2026
            today.strftime("%Y-%m"),  # 2026-04
        ]
        
        default_idx = 0
        # Check if current month is in available_months (try multiple formats)
        for candidate in current_month_candidates:
            if candidate in available_months:
                default_idx = available_months.index(candidate)
                break
        else:
            # If current month not found, find the latest month that is <= today
            past = [
                (i, parse_month(m))
                for i, m in enumerate(available_months)
                if pd.notna(parse_month(m)) and parse_month(m) <= today_ts
            ]
            if past:
                default_idx = past[-1][0]
        
        selected_month = st.selectbox(
            "Month",
            options=available_months,
            index=default_idx,
        )

    st.divider()
    if st.button("Sign out", width="stretch"):
        logout()

if not selected_month:
    st.warning("No KPI data found. Add months to the KPI Registry sheet.")
    st.stop()

# =============================================================================
# Load data
# =============================================================================
try:
    kpis_df    = load_kpis(department, selected_month)
    actuals_df = load_actuals(department, selected_month)
    enriched   = enrich_with_rag(kpis_df, actuals_df)
    enriched   = compute_mtd(enriched)
except Exception as e:
    st.error(f"Could not load data from Google Sheets: {e}")
    st.stop()

if kpis_df.empty:
    st.warning(f"No KPIs found for **{department}** in **{selected_month}**.")
    st.stop()

# =============================================================================
# Helpers
# =============================================================================
def _fmt(value, fallback="—", decimals=2):
    try:
        return f"{float(value):.{decimals}f}" if pd.notna(value) else fallback
    except (TypeError, ValueError):
        return fallback

def _fmt_target(value, fallback="—"):
    """Format a target value intelligently based on its range.
    Decimal values (0-1): treated as percentages: 0.95 → '95%'
    Values 1-100 with specific decimal patterns: treated as percentages: 95 → '95%', 95.5 → '95.5%'
    Values > 100 or irregular decimals: treated as regular numbers: 500 → '500', 2.3 → '2.30'
    """
    try:
        v = float(value)
        if pd.isna(v):
            return fallback
        
        # Decimal range: definitely a percentage (0.95 = 95%)
        if v <= 1.0:
            pct = v * 100
            return f"{int(pct)}%" if pct == int(pct) else f"{pct:.1f}%"
        
        # Large values (>100): definitely not percentages
        if v > 100:
            return f"{int(v)}" if v == int(v) else f"{v:.2f}"
        
        # Range 1-100: could be percentage or regular number
        # Treat as percentage if it's a whole number or has clean .5 or .X pattern
        # For thresholds like 1.05 (105%), we show as 1.05 (not a percentage)
        if v == int(v):
            # Whole number in 1-100 range: treat as percentage
            return f"{int(v)}%"
        elif (v * 10) == int(v * 10):
            # One decimal place (e.g., 95.5): treat as percentage
            return f"{v:.1f}%"
        else:
            # Irregular decimal (e.g., 2.35, 1.05): treat as regular number
            return f"{v:.2f}"
    except (TypeError, ValueError):
        return fallback

def _gap_label(gap):
    """Return a coloured label for gap: green if positive, red if negative."""
    if pd.isna(gap) or gap is None:
        return "—"
    sign = "+" if gap >= 0 else ""
    return f"{sign}{gap:.2f}"

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
    if current_label is None:
        st.markdown(text)


# =============================================================================
# Header
# =============================================================================
st.title("📊 KPI Dashboard")
st.markdown(f"**{department}** · {selected_month}")
st.divider()

# Debug info (collapsed by default)
with st.expander("🔍 Debug info", expanded=False):
    kpis_loaded    = st.session_state.get("debug_kpis_loaded", len(kpis_df))
    actuals_loaded = st.session_state.get("debug_actuals_loaded", len(actuals_df))
    weekly_count   = int((enriched.get(config.KPI_COL_WEEKLY_TRACKED, pd.Series([])).str.upper() == "YES").sum()) if config.KPI_COL_WEEKLY_TRACKED in enriched.columns else 0
    st.write(f"- KPIs loaded: **{kpis_loaded}**")
    st.write(f"- Actuals loaded (this month): **{actuals_loaded}**")
    st.write(f"- Weekly tracked KPIs: **{weekly_count}**")
    if actuals_loaded == 0:
        st.warning("No actuals found for this month. Submit data using the form below.")

# =============================================================================
# MTD formatting helpers
# =============================================================================

def _fmt_mtd_progress(actual, target_fmt):
    """Format MTD Progress to match target format."""
    if pd.isna(actual):
        return "—"
    # If target is percentage format, show as percentage
    if target_fmt and isinstance(target_fmt, str) and target_fmt.endswith("%"):
        # If actual is < 10, assume decimal format (0.94), convert to percentage
        if actual < 10:
            return f"{actual*100:.1f}%"
        else:
            return f"{actual:.1f}%"
    else:
        return f"{actual:.2f}"

def _fmt_gap(gap, target_fmt):
    """Format gap to match target format."""
    if pd.isna(gap):
        return "—"
    # If target is percentage format, show gap as percentage
    if target_fmt and isinstance(target_fmt, str) and target_fmt.endswith("%"):
        if abs(gap) < 10:
            return f"{gap*100:+.1f}%"
        else:
            return f"{gap:+.1f}%"
    else:
        return f"{gap:+.2f}"

# =============================================================================
# Section 1: MTD Progress — Weekly Tracked KPIs
# =============================================================================
st.subheader("📈 MTD Progress — Weekly Tracked KPIs")

weekly_df = enriched[
    enriched.get(config.KPI_COL_WEEKLY_TRACKED, pd.Series([""] * len(enriched))).str.upper() == "YES"
].copy() if config.KPI_COL_WEEKLY_TRACKED in enriched.columns else pd.DataFrame()

if weekly_df.empty:
    st.info("No weekly tracked KPIs for this month.")
else:
    # Sort by largest negative gap first (most behind)
    weekly_df["_gap_sort"] = pd.to_numeric(weekly_df["Gap to Target"], errors="coerce").fillna(0)
    weekly_df = weekly_df.sort_values("_gap_sort").drop(columns=["_gap_sort"])

    mtd_display = weekly_df[[
        config.KPI_COL_NAME,
        config.KPI_COL_TARGET,
        config.KPI_COL_TARGET_DESC,
        "MTD Progress",
        "Gap to Target",
    ]].copy()

    mtd_display[config.KPI_COL_TARGET] = mtd_display[config.KPI_COL_TARGET].apply(_fmt_target)
    
    # Format MTD Progress to match target format
    mtd_display["MTD Progress"] = mtd_display.apply(
        lambda row: _fmt_mtd_progress(row.get("MTD Progress"), row.get(config.KPI_COL_TARGET)),
        axis=1
    )
    
    # Format Gap to Target to match target format
    mtd_display["Gap to Target"] = mtd_display.apply(
        lambda row: _fmt_gap(row.get("Gap to Target"), row.get(config.KPI_COL_TARGET)),
        axis=1
    )
    
    mtd_display = mtd_display.rename(columns={
        config.KPI_COL_NAME:        "KPI Name",
        config.KPI_COL_TARGET:      "Target",
        config.KPI_COL_TARGET_DESC: "Target Description",
    })

    st.dataframe(
        mtd_display,
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# =============================================================================
# Section 2: All KPIs
# =============================================================================
st.subheader("📋 All KPIs")

raw_rag = enriched["RAG Status"]
b1, b2, b3, b4 = st.columns(4)
b1.metric("Total",    len(enriched))
b2.metric("🟢 Green", int((raw_rag == "Green").sum()))
b3.metric("🟡 Amber", int((raw_rag == "Amber").sum()))
b4.metric("🔴 Red",   int((raw_rag == "Red").sum()))

st.write("")

all_kpis_display = enriched[[
    config.KPI_COL_CODE,
    config.KPI_COL_NAME,
    config.KPI_COL_TARGET,
    config.KPI_COL_TARGET_DESC,
    "Latest Actual",
]].copy()

all_kpis_display[config.KPI_COL_TARGET] = all_kpis_display[config.KPI_COL_TARGET].apply(_fmt_target)

# Format Latest Actual to match target format (show as percentage if target is percentage)
def _fmt_actual(row):
    """Format actual value to match target format."""
    actual = row.get("Latest Actual")
    target = row.get(config.KPI_COL_TARGET)  # This is already formatted (e.g., "95%")
    
    if pd.isna(actual):
        return "—"
    
    # If target ends with %, format actual as percentage
    if target and isinstance(target, str) and target.endswith("%"):
        # If actual is < 10, it's likely a decimal (0.94), convert to percentage
        if actual < 10:
            return f"{actual*100:.1f}%"
        else:
            # Already in percentage format (94), just add %
            return f"{actual:.1f}%"
    else:
        # Regular numeric format
        return f"{actual:.2f}"

all_kpis_display["Latest Actual"] = all_kpis_display.apply(_fmt_actual, axis=1)
all_kpis_display = all_kpis_display.rename(columns={
    config.KPI_COL_CODE:        "Code",
    config.KPI_COL_NAME:        "KPI Name",
    config.KPI_COL_TARGET:      "Target",
    config.KPI_COL_TARGET_DESC: "Target Description",
})

st.dataframe(
    all_kpis_display,
    use_container_width=True,
    hide_index=True,
)

st.divider()

# =============================================================================
# Input Form
# =============================================================================
st.subheader("📝 Submit Actual")

kpi_options = {
    f"{r[config.KPI_COL_NAME]} ({r[config.KPI_COL_CODE]})": r[config.KPI_COL_CODE]
    for _, r in kpis_df.iterrows()
}
selected_label = st.selectbox("Select KPI", options=list(kpi_options.keys()))
selected_code  = kpi_options[selected_label]

# Determine input format from the selected KPI's target
_sel_kpi_row = kpis_df[kpis_df[config.KPI_COL_CODE] == selected_code]
_kpi_target  = _sel_kpi_row[config.KPI_COL_TARGET].iloc[0] if not _sel_kpi_row.empty else None
_target_fmt  = _fmt_target(_kpi_target)          # e.g. "95%" or "—"
_is_percent  = _target_fmt.endswith("%")

_convert_pct = False   # whether to divide input by 100 before saving
if _is_percent:
    try:
        _t = float(_kpi_target)
        # Check if target is decimal (0-1 range) OR if green threshold is decimal (0-2 range)
        # This handles both cases: target=0.95 or target=100 with green=1.05
        _green = _sel_kpi_row[config.KPI_COL_GREEN].iloc[0] if not _sel_kpi_row.empty else None
        _pct_decimal = (_t <= 1.0) or (pd.notna(_green) and _green <= 10)
    except (TypeError, ValueError):
        _pct_decimal = False
    if _pct_decimal:
        # Accept human-friendly percent input (e.g. 94 or 95), convert on save
        _actual_label  = "Actual value (%)"
        _actual_step   = 0.1
        _actual_format = "%.1f"
        _actual_max    = 100.0
        _convert_pct   = True
    else:
        _actual_label  = "Actual value (%)"
        _actual_step   = 0.1
        _actual_format = "%.1f"
        _actual_max    = None
else:
    _actual_label  = "Actual value"
    _actual_step   = 0.01
    _actual_format = "%.2f"
    _actual_max    = None

# Show last submission for selected KPI
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
        # Format Previous Actual to match target format
        if _is_percent and last[config.ACTUAL_COL_ACTUAL] < 10:
            # Decimal percentage format
            prev_actual_display = f"{last[config.ACTUAL_COL_ACTUAL]*100:.1f}%"
        elif _is_percent:
            # Regular percentage
            prev_actual_display = f"{last[config.ACTUAL_COL_ACTUAL]:.1f}%"
        else:
            # Regular numeric
            prev_actual_display = f"{last[config.ACTUAL_COL_ACTUAL]:.2f}"
        lc1.metric("Previous Actual", prev_actual_display)
        lc2.markdown(f"**Comment**\n\n{last_comment}")
else:
    st.info("No previous submission for this KPI this month.")

with st.form("actuals_form", clear_on_submit=True):
    # Build help text with instructions
    _help_text = None
    if _is_percent:
        _help_text = f"Enter the value as a percentage (0-100). Example: enter 94 for 94%. Target: {_target_fmt}"
    
    _input_kwargs = dict(
        label=_actual_label,
        min_value=0.0,
        step=_actual_step,
        format=_actual_format,
        help=_help_text,
    )
    if _actual_max is not None:
        _input_kwargs["max_value"] = _actual_max
    actual_value = st.number_input(**_input_kwargs)
    comment      = st.text_area(
        "Comment",
        placeholder="Briefly explain the result — what drove it, any context…",
        max_chars=500,
    )
    fc1, fc2 = st.columns(2)
    fc1.text_input("Date",         value=date.today().strftime("%Y-%m-%d"), disabled=True)
    fc2.text_input("Submitted by", value=user["email"],                     disabled=True)
    submitted = st.form_submit_button("Submit", width="stretch", type="primary")

if submitted:
    try:
        save_value = actual_value / 100.0 if _convert_pct else actual_value
        append_actual(
            date=date.today().strftime("%Y-%m-%d"),
            kpi_code=selected_code,
            actual=save_value,
            comment=comment.strip(),
            updated_by=user["email"],
        )
        display_value = f"{actual_value:.1f}%" if _is_percent else f"{actual_value:.2f}"
        st.success(f"Saved! {selected_label} → {display_value} on {date.today().strftime('%d %b %Y')}")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to save: {e}")

st.divider()

# =============================================================================
# Latest Comments
# =============================================================================
st.subheader("💬 Latest Comments")

if actuals_df.empty:
    st.info("No comments submitted yet.")
else:
    comments = (
        actuals_df[actuals_df[config.ACTUAL_COL_COMMENT].astype(str).str.strip().ne("")]
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
# AI Insights
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
