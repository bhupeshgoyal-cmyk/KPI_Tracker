import pandas as pd
import streamlit as st
from datetime import date
from auth import require_auth, logout
from data_loader import (
    load_kpis, load_actuals, load_available_months,
    enrich_with_rag, compute_mtd, append_actual, parse_month,
    get_weekly_insight_count, log_insight_usage,
)
from ai_engine import generate_insights
import config

st.set_page_config(
    page_title="Stashfin | KPI Dashboard",
    page_icon="�",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Stashfin Brand Colors and Custom Styling
st.markdown("""
<style>
    /* Hide Streamlit toolbar buttons except star and menu */
    [data-testid="toolbarButtonContainer"] {
        display: none !important;
    }
    
    .stApp [data-testid="baseButton-secondary"] {
        display: none !important;
    }
    
    /* Hide all header buttons except star and menu */
    [data-testid="stHeader"] [data-testid="baseButton-secondary"]:nth-child(1),
    [data-testid="stHeader"] [data-testid="baseButton-secondary"]:nth-child(2),
    [data-testid="stHeader"] [data-testid="baseButton-secondary"]:nth-child(3),
    [data-testid="stHeader"] [data-testid="baseButton-secondary"]:nth-child(4) {
        display: none !important;
    }
    
    /* Hide the deploy button and other toolbar elements */
    [data-testid="stHeader"] .stActionButton {
        display: none !important;
    }
    
    /* Keep only the star and hamburger menu visible */
    [data-testid="stHeader"] button:has(svg[data-testid="icon-star"]),
    [data-testid="stHeader"] button:has(svg[data-testid="icon-ellipsis"]),
    .stHeader button {
        display: inline-block !important;
    }
    
    /* Alternative approach: hide share and other deployment buttons */
    [data-testid="stDecoratedButton"] {
        display: none !important;
    }
    
    /* Stashfin Brand Colors */
    :root {
        --stashfin-primary: #1A73E8;    /* Primary Blue */
        --stashfin-accent: #34A853;     /* Success Green */
        --stashfin-warning: #FBBC04;    /* Warning Yellow */
        --stashfin-error: #EA4335;      /* Error Red */
        --stashfin-dark: #202124;       /* Dark Gray */
        --stashfin-light: #F8F9FA;      /* Light Gray */
    }
    
    /* Main container styling */
    .main {
        background-color: #F8F9FA;
    }
    
    /* Title styling */
    h1 {
        color: #1A73E8 !important;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    
    /* Subheader styling */
    h2 {
        color: #202124 !important;
        font-weight: 600;
    }
    
    /* Sidebar styling */
    [data-testid="sidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E8EAED;
    }
    
    /* Metric styling */
    [data-testid="metric-container"] {
        background-color: #FFFFFF;
        border-radius: 8px;
        border: 1px solid #E8EAED;
        padding: 1.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    
    /* Button styling */
    button {
        background-color: #1A73E8 !important;
        color: white !important;
        border-radius: 4px;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    
    button:hover {
        background-color: #155FD0 !important;
        box-shadow: 0 1px 3px rgba(26,115,232,0.3);
    }
    
    /* Divider styling */
    hr {
        border-top: 1px solid #E8EAED !important;
        margin: 2rem 0 !important;
    }
    
    /* Badge styling */
    .badge {
        background-color: #34A853;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    
    /* RAG Status Colors */
    .rag-green {
        color: #34A853 !important;
        font-weight: 600;
    }
    
    .rag-amber {
        color: #FBBC04 !important;
        font-weight: 600;
    }
    
    .rag-red {
        color: #EA4335 !important;
        font-weight: 600;
    }
    
    /* Data table styling */
    [data-testid="dataframe"] {
        border-radius: 8px;
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# Auth
# =============================================================================
user = require_auth()

# Initialize session state for department selection if not present
if "selected_dept" not in st.session_state:
    # For admins, default to "All"; for regular users, default to first department
    if user.get("is_admin", False):
        st.session_state.selected_dept = "All"
    else:
        st.session_state.selected_dept = user["department"]

department = st.session_state.selected_dept

# =============================================================================
# Sidebar
# =============================================================================
with st.sidebar:
    st.markdown(f"### {user['name']}")
    st.caption(user["email"])
    
    # Show role badge if user is admin
    if user.get("is_admin", False):
        st.markdown("✅ **Admin**")
    
    # Department selector
    user_departments = user.get("departments", [user.get("department", "Unknown")])
    
    # For admin users, add "All" option at the beginning
    if user.get("is_admin", False):
        dept_options = ["All"] + user_departments
    else:
        dept_options = user_departments
    
    if len(dept_options) > 1:
        st.caption("**Department:**")
        selected_dept = st.selectbox(
            "Select department",
            options=dept_options,
            index=dept_options.index(department) if department in dept_options else 0,
            key="dept_selector",
            label_visibility="collapsed"
        )
        if selected_dept != department:
            st.session_state.selected_dept = selected_dept
            department = selected_dept
            st.rerun()
    else:
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

def _fmt_target(value, row_index=None, is_percentage=None, fallback="—"):
    """Format a target value using per-row format tracking from Google Sheet.
    If row_index is provided, check the per-row percentage flag.
    """
    try:
        v = float(value)
        if pd.isna(v):
            return fallback
        
        # If we have per-row format info, use it
        if row_index is not None:
            col_name_pct = f"_{config.KPI_COL_TARGET}_is_pct"
            # This will be checked in context when we know the row
        
        # If we know the format from the sheet, use it
        if is_percentage is not None:
            if is_percentage:
                return f"{v:.2f}%"
            else:
                return f"{v:.2f}"
        
        # Fallback to intelligent detection
        # Decimal range: definitely a percentage (0.95 = 95%)
        if v <= 1.0:
            pct = v * 100
            return f"{int(pct)}.00%" if pct == int(pct) else f"{pct:.2f}%"
        
        # Large values (>100): definitely not percentages
        if v > 100:
            return f"{int(v)}" if v == int(v) else f"{v:.2f}"
        
        # Range 1-100: could be percentage or regular number
        # Treat as percentage if it's a whole number or has clean decimal pattern
        if v == int(v):
            return f"{int(v)}.00%"
        elif (v * 10) == int(v * 10):
            return f"{v:.2f}%"
        else:
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
st.markdown(
    '<div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem;">'
    '<div style="background: linear-gradient(135deg, #1A73E8 0%, #155FD0 100%); padding: 0.75rem 1.5rem; border-radius: 8px; display: flex; align-items: center; gap: 0.5rem;">'
    '<img src="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHJ4PSI0IiBmaWxsPSJ3aGl0ZSIvPjwvc3ZnPg==" style="width: 24px; height: 24px;"/>'
    '<span style="font-size: 1.5rem; font-weight: 700; color: white;">STASHFIN</span>'
    '</div>'
    '<div>'
    '<h1 style="margin: 0; font-size: 2rem; color: #1A73E8;">KPI Dashboard</h1>'
    '<p style="margin: 0.25rem 0 0 0; color: #5F6368; font-size: 0.9rem;">Track, Analyze, Optimize</p>'
    '</div>'
    '</div>',
    unsafe_allow_html=True
)
st.markdown(f"<p style='color: #5F6368; font-size: 0.95rem; margin-bottom: 1rem;'><strong style='color: #1A73E8;'>{department}</strong> · {selected_month}</p>", unsafe_allow_html=True)
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

def _fmt_mtd_progress(actual, target_fmt, is_percentage=None):
    """Format MTD Progress to match target format with 2 decimal places for percentages."""
    if pd.isna(actual):
        return "—"
    # If we know the format, use it
    if is_percentage is not None:
        if is_percentage:
            return f"{actual:.2f}%"
        else:
            return f"{actual:.2f}"
    # Fallback to checking target format string
    if target_fmt and isinstance(target_fmt, str) and target_fmt.endswith("%"):
        return f"{actual:.2f}%"
    else:
        return f"{actual:.2f}"

def _fmt_gap(gap, target_fmt, is_percentage=None):
    """Format gap to match target format with 2 decimal places for percentages."""
    if pd.isna(gap):
        return "—"
    # If we know the format, use it
    if is_percentage is not None:
        if is_percentage:
            return f"{gap:+.2f}%"
        else:
            return f"{gap:+.2f}"
    # Fallback to checking target format string
    if target_fmt and isinstance(target_fmt, str) and target_fmt.endswith("%"):
        return f"{gap:+.2f}%"
    else:
        return f"{gap:+.2f}"

# =============================================================================
# Section 1: MTD Progress — Weekly Tracked KPIs
# =============================================================================
st.markdown("<h2 style='color: #1A73E8; margin-bottom: 1rem;'>📈 MTD Progress — Weekly Tracked KPIs</h2>", unsafe_allow_html=True)

weekly_df = enriched[
    enriched.get(config.KPI_COL_WEEKLY_TRACKED, pd.Series([""] * len(enriched))).str.upper() == "YES"
].copy() if config.KPI_COL_WEEKLY_TRACKED in enriched.columns else pd.DataFrame()

if weekly_df.empty:
    st.info("No weekly tracked KPIs for this month.")
else:
    # Sort by largest negative gap first (most behind)
    weekly_df["_gap_sort"] = pd.to_numeric(weekly_df["Gap to Target"], errors="coerce").fillna(0)
    weekly_df = weekly_df.sort_values("_gap_sort").drop(columns=["_gap_sort"])

    # Build column list - add Owner column for admins (if it exists)
    mtd_cols = [
        config.KPI_COL_NAME,
    ]
    if user.get("is_admin", False) and config.KPI_COL_OWNER in weekly_df.columns:
        mtd_cols.append(config.KPI_COL_OWNER)
    # Add Unit column if it exists
    if config.KPI_COL_UNIT in weekly_df.columns:
        mtd_cols.append(config.KPI_COL_UNIT)
    mtd_cols.extend([
        config.KPI_COL_TARGET,
        config.KPI_COL_TARGET_DESC,
        "MTD Progress",
        "Gap to Target",
    ])
    
    # Get per-row percentage format from the marked columns
    pct_col_name = f"_{config.KPI_COL_TARGET}_is_pct"
    if pct_col_name in weekly_df.columns:
        mtd_cols.append(pct_col_name)
    
    mtd_display = weekly_df[mtd_cols].copy()
    
    # Format Target using per-row format flag
    if pct_col_name in weekly_df.columns:
        def _fmt_target_with_flag(row):
            v = row[config.KPI_COL_TARGET]
            if row[pct_col_name]:
                return f"{v * 100:.2f}%" if v <= 1.0 else f"{v:.2f}%"
            return f"{v:.2f}"
        mtd_display[config.KPI_COL_TARGET] = mtd_display.apply(_fmt_target_with_flag, axis=1)
    else:
        # Fallback if column not found
        mtd_display[config.KPI_COL_TARGET] = mtd_display[config.KPI_COL_TARGET].apply(_fmt_target)
    
    # Format MTD Progress to match target format (using per-row flag)
    def _fmt_mtd_with_flag(row):
        actual = row.get("MTD Progress")
        if pd.isna(actual):
            return "—"
        is_pct = row.get(pct_col_name, False) if pct_col_name in weekly_df.columns else False
        if is_pct:
            # Check if actual is in decimal format (0-1 range) - if so, multiply by 100
            if actual <= 1.0:
                return f"{actual * 100:.2f}%"
            else:
                return f"{actual:.2f}%"
        else:
            return f"{actual:.2f}"
    
    mtd_display["MTD Progress"] = mtd_display.apply(_fmt_mtd_with_flag, axis=1)
    
    # Gap to Target is always % of target — format uniformly
    mtd_display["Gap to Target"] = mtd_display["Gap to Target"].apply(
        lambda g: f"{g:+.2f}%" if pd.notna(g) else "—"
    )
    
    # Drop the percentage flag column before renaming/displaying
    if pct_col_name in mtd_display.columns:
        mtd_display = mtd_display.drop(columns=[pct_col_name])
    
    # Build rename mapping - include Owner for admins (if it exists)
    rename_map = {
        config.KPI_COL_NAME:        "KPI Name",
        config.KPI_COL_TARGET:      "Target",
        config.KPI_COL_TARGET_DESC: "Target Description",
    }
    if user.get("is_admin", False) and config.KPI_COL_OWNER in weekly_df.columns:
        rename_map[config.KPI_COL_OWNER] = "Owner"
    if config.KPI_COL_UNIT in weekly_df.columns:
        rename_map[config.KPI_COL_UNIT] = "Unit"
    
    mtd_display = mtd_display.rename(columns=rename_map)

    st.dataframe(
        mtd_display,
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# =============================================================================
# Section 2: All KPIs
# =============================================================================
st.markdown("<h2 style='color: #1A73E8; margin-bottom: 1rem;'>📋 All KPIs</h2>", unsafe_allow_html=True)

raw_rag = enriched["RAG Status"]
b1, b2, b3, b4 = st.columns(4)

# Custom metric styling with Stashfin colors
with b1:
    st.markdown(
        f"<div style='background: linear-gradient(135deg, #F8F9FA 0%, #FFFFFF 100%); border: 1px solid #E8EAED; border-radius: 8px; padding: 1.5rem; text-align: center;'>"
        f"<p style='color: #5F6368; font-size: 0.85rem; margin: 0; margin-bottom: 0.5rem;'>Total</p>"
        f"<p style='color: #1A73E8; font-size: 2rem; font-weight: 700; margin: 0;'>{len(enriched)}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

with b2:
    green_count = int((raw_rag == "Green").sum())
    st.markdown(
        f"<div style='background: linear-gradient(135deg, #F8F9FA 0%, #FFFFFF 100%); border: 1px solid #34A853; border-radius: 8px; padding: 1.5rem; text-align: center;'>"
        f"<p style='color: #5F6368; font-size: 0.85rem; margin: 0; margin-bottom: 0.5rem;'>🟢 Green</p>"
        f"<p style='color: #34A853; font-size: 2rem; font-weight: 700; margin: 0;'>{green_count}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

with b3:
    amber_count = int((raw_rag == "Amber").sum())
    st.markdown(
        f"<div style='background: linear-gradient(135deg, #F8F9FA 0%, #FFFFFF 100%); border: 1px solid #FBBC04; border-radius: 8px; padding: 1.5rem; text-align: center;'>"
        f"<p style='color: #5F6368; font-size: 0.85rem; margin: 0; margin-bottom: 0.5rem;'>🟡 Amber</p>"
        f"<p style='color: #FBBC04; font-size: 2rem; font-weight: 700; margin: 0;'>{amber_count}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

with b4:
    red_count = int((raw_rag == "Red").sum())
    st.markdown(
        f"<div style='background: linear-gradient(135deg, #F8F9FA 0%, #FFFFFF 100%); border: 1px solid #EA4335; border-radius: 8px; padding: 1.5rem; text-align: center;'>"
        f"<p style='color: #5F6368; font-size: 0.85rem; margin: 0; margin-bottom: 0.5rem;'>🔴 Red</p>"
        f"<p style='color: #EA4335; font-size: 2rem; font-weight: 700; margin: 0;'>{red_count}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

st.write("")

# Build column list - add Owner column for admins (if it exists)
kpi_cols = [
    config.KPI_COL_CODE,
    config.KPI_COL_NAME,
]
if user.get("is_admin", False) and config.KPI_COL_OWNER in enriched.columns:
    kpi_cols.append(config.KPI_COL_OWNER)
# Add Unit column if it exists
if config.KPI_COL_UNIT in enriched.columns:
    kpi_cols.append(config.KPI_COL_UNIT)
kpi_cols.extend([
    config.KPI_COL_TARGET,
    config.KPI_COL_TARGET_DESC,
    "Latest Actual",
    "Gap to Target",
])

# Get per-row percentage format from the marked columns
pct_col_name = f"_{config.KPI_COL_TARGET}_is_pct"
if pct_col_name in enriched.columns:
    kpi_cols.append(pct_col_name)

all_kpis_display = enriched[kpi_cols].copy()

# Get per-row percentage format from the marked columns
pct_col_name = f"_{config.KPI_COL_TARGET}_is_pct"

# Format Target using per-row format flag
def _fmt_target_all(row):
    v = row[config.KPI_COL_TARGET]
    if row.get(pct_col_name, False):
        return f"{v * 100:.2f}%" if v <= 1.0 else f"{v:.2f}%"
    return f"{v:.2f}"

if pct_col_name in enriched.columns:
    all_kpis_display[config.KPI_COL_TARGET] = all_kpis_display.apply(_fmt_target_all, axis=1)
else:
    # Fallback if column not found
    all_kpis_display[config.KPI_COL_TARGET] = all_kpis_display[config.KPI_COL_TARGET].apply(lambda x: _fmt_target(x))

# Format Latest Actual to match target format (using per-row flag)
def _fmt_actual_with_flag(row):
    """Format actual value to match target format using per-row flag."""
    actual = row.get("Latest Actual")
    if pd.isna(actual):
        return "—"
    is_pct = row.get(pct_col_name, False) if pct_col_name in enriched.columns else False
    if is_pct:
        # Check if actual is in decimal format (0-1 range) - if so, multiply by 100
        if actual <= 1.0:
            return f"{actual * 100:.2f}%"
        else:
            return f"{actual:.2f}%"
    else:
        return f"{actual:.2f}"

all_kpis_display["Latest Actual"] = all_kpis_display.apply(_fmt_actual_with_flag, axis=1)

# Gap to Target is always % of target — format uniformly
all_kpis_display["Gap to Target"] = all_kpis_display["Gap to Target"].apply(
    lambda g: f"{g:+.2f}%" if pd.notna(g) else "—"
)

# Drop the percentage flag column before renaming/displaying
if pct_col_name in all_kpis_display.columns:
    all_kpis_display = all_kpis_display.drop(columns=[pct_col_name])

all_kpis_display = all_kpis_display.rename(columns={
    config.KPI_COL_CODE:        "Code",
    config.KPI_COL_NAME:        "KPI Name",
    config.KPI_COL_TARGET:      "Target",
    config.KPI_COL_TARGET_DESC: "Target Description",
    **({
        config.KPI_COL_OWNER: "Owner"
    } if (user.get("is_admin", False) and config.KPI_COL_OWNER in enriched.columns) else {}),
    **({
        config.KPI_COL_UNIT: "Unit"
    } if config.KPI_COL_UNIT in enriched.columns else {})
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
st.markdown("<h2 style='color: #1A73E8; margin-bottom: 1rem;'>📝 Submit Actual</h2>", unsafe_allow_html=True)

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
st.markdown("<h2 style='color: #1A73E8; margin-bottom: 1rem;'>🧠 Performance Summary</h2>", unsafe_allow_html=True)

_insight_used  = get_weekly_insight_count(department)
_insight_left  = max(0, config.INSIGHTS_WEEKLY_CAP - _insight_used)

if _insight_left > 0:
    st.caption(f"✨ {_insight_left} of {config.INSIGHTS_WEEKLY_CAP} insights remaining this week")
    if st.button("Generate Insight", type="primary"):
        with st.spinner("Crunching the numbers… 🔍"):
            st.session_state["insight"] = generate_insights(department, enriched)
            log_insight_usage(department, user["email"])
            st.rerun()
else:
    st.info(
        "🎯 You've used both insights for this week — great engagement! "
        "Your next insights unlock on Monday. "
        "In the meantime, keep submitting actuals and comments for a richer briefing next time. 💪"
    )

if "insight" in st.session_state:
    _render_insight(st.session_state["insight"])
    if st.button("Clear", key="clear_insight"):
        del st.session_state["insight"]
        st.rerun()
