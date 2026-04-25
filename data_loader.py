import calendar
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

import config

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_EMPTY_ACTUALS = pd.DataFrame(columns=[
    config.ACTUAL_COL_DATE, config.ACTUAL_COL_KPI_CODE,
    config.ACTUAL_COL_ACTUAL, config.ACTUAL_COL_COMMENT,
    config.ACTUAL_COL_UPDATED_BY, config.ACTUAL_COL_MONTH,
])


# =============================================================================
# Connection
# =============================================================================

@st.cache_resource(show_spinner="Connecting to Google Sheets…")
def _get_client() -> gspread.Client:
    creds_dict = config.get_google_creds_dict()
    if creds_dict:
        creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
    else:
        creds = Credentials.from_service_account_file(config.GOOGLE_CREDS_JSON, scopes=_SCOPES)
    return gspread.authorize(creds)


def _get_sheet(tab_name: str) -> gspread.Worksheet:
    return _get_client().open_by_key(config.SHEET_ID).worksheet(tab_name)


def _sheet_to_df(tab_name: str) -> pd.DataFrame:
    records = _get_sheet(tab_name).get_all_records()
    df = pd.DataFrame(records)
    # Strip whitespace from all column names
    if not df.empty:
        df.columns = [c.strip() for c in df.columns]
    return df


# =============================================================================
# Month helpers
# =============================================================================

def parse_month(month_str: str) -> pd.Timestamp:
    """
    Parse month strings like 'Apr-2026' or '2026-04' into a Timestamp.
    Returns NaT on failure.
    """
    s = str(month_str).strip()
    for fmt in ("%b-%Y", "%Y-%m", "%B-%Y", "%b %Y", "%B %Y"):
        try:
            return pd.to_datetime(s, format=fmt)
        except ValueError:
            continue
    return pd.NaT


def sort_months_fy(month_strings: list[str]) -> list[str]:
    """
    Sort a list of month strings in financial year order (Apr → Mar).
    Handles 'Apr-2026' format.
    """
    parsed = []
    for s in month_strings:
        dt = parse_month(s)
        if pd.notna(dt):
            parsed.append((s, dt))

    def fy_key(item):
        _, dt = item
        fy_year  = dt.year if dt.month >= 4 else dt.year - 1
        fy_index = config.FY_MONTH_ORDER.index(dt.month)
        return (fy_year, fy_index)

    return [s for s, _ in sorted(parsed, key=fy_key)]


# =============================================================================
# KPI Registry
# =============================================================================

@st.cache_data(ttl=300, show_spinner="Loading KPI Registry…")
def _load_kpi_registry() -> pd.DataFrame:
    """Load full KPI Registry and normalise numeric columns."""
    df = _sheet_to_df(config.KPI_REGISTRY_TAB)
    if df.empty:
        return df

    # Track original format for each numeric column (before stripping %)
    for col in [config.KPI_COL_TARGET, config.KPI_COL_GREEN,
                config.KPI_COL_AMBER, config.KPI_COL_RED]:
        if col in df.columns:
            # Mark each value as percentage or not based on original format
            col_name_original = f"_{col}_is_pct"
            df[col_name_original] = df[col].astype(str).str.strip().str.contains('%', regex=False)
            # Handle percentage strings like "100%" stored in the sheet
            raw = df[col].astype(str).str.strip().str.rstrip('%')
            df[col] = pd.to_numeric(raw, errors="coerce")

    # Normalise text columns
    for col in [config.KPI_COL_DEPARTMENT, config.KPI_COL_MONTH,
                config.KPI_COL_WEEKLY_TRACKED, config.KPI_COL_UNIT,
                config.KPI_COL_TYPE, config.KPI_COL_P0]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


def load_available_months(department: str) -> list[str]:
    """
    Return months available for a department sorted in FY order.
    If department is "All", returns all available months.
    Used to populate the sidebar month selector.
    """
    df = _load_kpi_registry()
    if df.empty or config.KPI_COL_MONTH not in df.columns:
        return []

    # If department is "All", don't filter by department
    if department.upper() == "ALL":
        unique_months = df[config.KPI_COL_MONTH].dropna().unique().tolist()
    else:
        dept_df = df[df[config.KPI_COL_DEPARTMENT] == department]
        unique_months = dept_df[config.KPI_COL_MONTH].dropna().unique().tolist()
    
    unique_months = [m for m in unique_months if m and m.lower() != "nan"]
    return sort_months_fy(unique_months)


@st.cache_data(ttl=300, show_spinner="Loading KPIs…")
def load_kpis(department: str, month: str) -> pd.DataFrame:
    """Return KPIs for a given department and month.
    
    If department is "All", returns KPIs for all departments (for admin users).
    """
    df = _load_kpi_registry()
    if df.empty:
        return df

    # If department is "All", don't filter by department
    if department.upper() == "ALL":
        mask = (df[config.KPI_COL_MONTH] == str(month).strip())
    else:
        mask = (
            (df[config.KPI_COL_DEPARTMENT] == department) &
            (df[config.KPI_COL_MONTH] == str(month).strip())
        )
    result = df[mask].reset_index(drop=True)
    st.session_state["debug_kpis_loaded"] = len(result)
    return result


# =============================================================================
# Actuals
# =============================================================================

@st.cache_data(ttl=60, show_spinner="Loading actuals…")
def load_actuals(department: str, month: str) -> pd.DataFrame:
    """
    Return actuals for a department's KPIs, filtered to the selected month.
    """
    actuals_df = _sheet_to_df(config.ACTUALS_TAB)
    kpis_df    = load_kpis(department, month)

    if actuals_df.empty or config.ACTUAL_COL_KPI_CODE not in actuals_df.columns:
        st.session_state["debug_actuals_loaded"] = 0
        return _EMPTY_ACTUALS.copy()

    # Filter to department's KPI codes
    dept_codes = kpis_df[config.KPI_COL_CODE].tolist()
    filtered   = actuals_df[actuals_df[config.ACTUAL_COL_KPI_CODE].isin(dept_codes)].copy()

    filtered[config.ACTUAL_COL_DATE]   = pd.to_datetime(filtered[config.ACTUAL_COL_DATE], errors="coerce")
    filtered[config.ACTUAL_COL_ACTUAL] = pd.to_numeric(filtered[config.ACTUAL_COL_ACTUAL], errors="coerce")

    # Filter to selected month:
    # - Prefer the explicit Month column (set at submit time from the sidebar selector)
    # - Fall back to date's year/month for legacy rows where Month is empty
    month_str = str(month).strip()
    month_dt  = parse_month(month)

    if config.ACTUAL_COL_MONTH in filtered.columns:
        month_col   = filtered[config.ACTUAL_COL_MONTH].astype(str).str.strip()
        month_match = month_col == month_str
        legacy_mask = month_col.isin(["", "nan", "NaN", "None"])
    else:
        month_match = pd.Series(False, index=filtered.index)
        legacy_mask = pd.Series(True,  index=filtered.index)

    if pd.notna(month_dt):
        date_match = (
            (filtered[config.ACTUAL_COL_DATE].dt.year  == month_dt.year) &
            (filtered[config.ACTUAL_COL_DATE].dt.month == month_dt.month)
        )
    else:
        date_match = pd.Series(False, index=filtered.index)

    filtered = filtered[month_match | (legacy_mask & date_match)]

    result = filtered.sort_values(config.ACTUAL_COL_DATE, ascending=False).reset_index(drop=True)
    st.session_state["debug_actuals_loaded"] = len(result)
    return result


def get_weekly_insight_count(department: str) -> int:
    """Return how many insights have been generated for this department in the current ISO week."""
    from datetime import date as _date
    try:
        ws = _get_sheet(config.INSIGHTS_LOG_TAB)
        records = ws.get_all_records()
        if not records:
            return 0
        today = _date.today()
        iso_week = today.isocalendar()[1]
        iso_year = today.isocalendar()[0]
        return sum(
            1 for r in records
            if str(r.get("Department", "")).strip() == department
            and int(r.get("Week", 0)) == iso_week
            and int(r.get("Year", 0)) == iso_year
        )
    except Exception:
        return 0  # fail open — don't block insights if sheet missing


def log_insight_usage(department: str, user_email: str) -> None:
    """Append one usage record to the Insights Log sheet."""
    from datetime import date as _date, datetime as _dt
    try:
        today = _date.today()
        iso = today.isocalendar()
        _get_sheet(config.INSIGHTS_LOG_TAB).append_row(
            [_dt.now().strftime("%Y-%m-%d %H:%M:%S"), department, user_email, iso[1], iso[0]],
            value_input_option="USER_ENTERED",
        )
    except Exception:
        pass  # non-critical — don't crash if logging fails


@st.cache_resource(show_spinner=False)
def _ensure_actuals_month_column() -> bool:
    """Add a 'Month' header to the Actuals sheet if it isn't there yet.
    Idempotent and cached for the session so it runs at most once per process."""
    ws = _get_sheet(config.ACTUALS_TAB)
    headers = [h.strip() for h in ws.row_values(1)]
    if config.ACTUAL_COL_MONTH not in headers:
        ws.update_cell(1, len(headers) + 1, config.ACTUAL_COL_MONTH)
    return True


def append_actual(date: str, kpi_code: str, actual: float,
                  comment: str, updated_by: str, month: str) -> None:
    """Append a row to Actuals and clear caches."""
    _ensure_actuals_month_column()
    _get_sheet(config.ACTUALS_TAB).append_row(
        [date, kpi_code, actual, comment, updated_by, month],
        value_input_option="USER_ENTERED",
    )
    load_actuals.clear()
    load_kpis.clear()
    _load_kpi_registry.clear()


# =============================================================================
# RAG status
# =============================================================================

def _prorating_factor(actual_date_str, month_str) -> float:
    """
    Return elapsed_days / days_in_month for the submission date.
    Used to scale monthly thresholds to the appropriate MTD checkpoint.
    e.g. day 9 of a 30-day month → 0.30  (thresholds scaled to 30% of full value)
    Returns 1.0 on any parse failure (no pro-rating applied).
    """
    try:
        actual_date = pd.to_datetime(actual_date_str).date()
        month_ts    = parse_month(str(month_str).strip())
        if pd.isna(month_ts):
            return 1.0
        days_in_month = calendar.monthrange(month_ts.year, month_ts.month)[1]
        elapsed       = actual_date.day
        return min(elapsed / days_in_month, 1.0)
    except Exception:
        return 1.0


def compute_rag(actual, green, amber, red, prorated_factor: float = 1.0) -> str:
    """
    Compare actual directly against thresholds using the same units as the
    KPI Registry (no normalisation — what you see in the sheet is what is used).

    For MTD / weekly-tracked KPIs pass prorated_factor = elapsed_days / days_in_month
    so the thresholds are scaled to the current point in the month before comparison.

    Example: green=400, day 9 of 30 → effective_green = 400 × (9/30) = 120.
    Higher-is-better: actual >= effective_green → Green, etc.
    """
    try:
        if pd.isna(actual):
            return "Unknown"
        actual = float(actual)

        def effective(thresh):
            if pd.isna(thresh):
                return None
            return float(thresh) * prorated_factor

        g = effective(green)
        a = effective(amber)
        r = effective(red)

        if g is not None and actual >= g:
            return "Green"
        if a is not None and actual >= a:
            return "Amber"
        if r is not None and actual >= r:
            return "Red"
        return "Red"
    except Exception:
        return "Unknown"


def enrich_with_rag(kpis_df: pd.DataFrame, actuals_df: pd.DataFrame) -> pd.DataFrame:
    """
    Join latest actual + latest comment onto each KPI row.
    Adds: Latest Actual, Latest Comment, RAG Status.
    """
    df = kpis_df.copy()

    if actuals_df.empty:
        df["Latest Actual"]  = None
        df["Latest Comment"] = ""
        df["RAG Status"]     = "Unknown"
        return df

    latest = (
        actuals_df.sort_values(config.ACTUAL_COL_DATE)
        .groupby(config.ACTUAL_COL_KPI_CODE)
        .last()
        .reset_index()[[
            config.ACTUAL_COL_KPI_CODE,
            config.ACTUAL_COL_ACTUAL,
            config.ACTUAL_COL_COMMENT,
            config.ACTUAL_COL_DATE,
        ]]
        .rename(columns={
            config.ACTUAL_COL_ACTUAL:  "Latest Actual",
            config.ACTUAL_COL_COMMENT: "Latest Comment",
            config.ACTUAL_COL_DATE:    "Latest Date",
        })
    )

    merged = df.merge(
        latest,
        left_on=config.KPI_COL_CODE,
        right_on=config.ACTUAL_COL_KPI_CODE,
        how="left",
    )
    # Drop duplicate join key if it appeared
    if config.ACTUAL_COL_KPI_CODE in merged.columns and config.ACTUAL_COL_KPI_CODE != config.KPI_COL_CODE:
        merged = merged.drop(columns=[config.ACTUAL_COL_KPI_CODE])

    merged["Latest Comment"] = merged["Latest Comment"].fillna("")

    pct_flag_col = f"_{config.KPI_COL_TARGET}_is_pct"

    def _rag_for_row(row):
        # Prorate only when the target is NOT stored as a percentage.
        # Percentage / ratio KPIs don't accumulate over the month, so scaling
        # their thresholds by elapsed_days/days_in_month would be wrong.
        target_is_pct = bool(row.get(pct_flag_col, False))
        factor = (
            1.0 if target_is_pct
            else _prorating_factor(row.get("Latest Date"), row.get(config.KPI_COL_MONTH))
        )
        return compute_rag(
            row.get("Latest Actual"),
            row.get(config.KPI_COL_GREEN),
            row.get(config.KPI_COL_AMBER),
            row.get(config.KPI_COL_RED),
            prorated_factor=factor,
        )

    merged["RAG Status"] = merged.apply(_rag_for_row, axis=1)
    return merged


# =============================================================================
# MTD computation (weekly tracked KPIs only)
# =============================================================================

def compute_mtd(enriched_df: pd.DataFrame) -> pd.DataFrame:
    """
    For weekly tracked KPIs (Weekly Tracked = 'Yes'):
      - MTD Progress  = latest reported value
      - Gap to Target = MTD Progress - Target
                        (positive = ahead, negative = behind)
    
    Handles format normalization: if actual is stored as percentage (0-100)
    and target is decimal (0-1), normalizes actual to decimal before subtracting.

    Columns added: MTD Progress, Gap to Target.
    Non-weekly KPIs get NaN in these columns.
    """
    df = enriched_df.copy()

    if config.KPI_COL_WEEKLY_TRACKED not in df.columns:
        df["MTD Progress"]  = None
        df["Gap to Target"] = None
        return df

    is_weekly = df[config.KPI_COL_WEEKLY_TRACKED].str.upper() == "YES"

    df["MTD Progress"]  = None
    df["Gap to Target"] = None

    # Weekly KPIs: MTD Progress = latest submitted value
    df.loc[is_weekly, "MTD Progress"] = df.loc[is_weekly, "Latest Actual"]

    # Gap to Target for ALL KPIs = (latest_actual - target) / target * 100
    def _gap_for_row(row):
        actual = row.get("Latest Actual")
        target = row.get(config.KPI_COL_TARGET)
        if pd.notna(actual) and pd.notna(target):
            return _calculate_gap(float(actual), float(target))
        return None

    df["Gap to Target"] = df.apply(_gap_for_row, axis=1)

    return df


def _calculate_gap(actual: float, target: float) -> float | None:
    """Gap = (actual - target) / target * 100, expressed as a percentage of target.
    Returns None if target is zero to avoid division by zero.
    e.g. actual=150, target=424 → (150-424)/424*100 = -64.6 (%)
         actual=0.92, target=1.0 → (0.92-1.0)/1.0*100 = -8.0 (%)
    """
    if target == 0:
        return None
    return (actual - target) / target * 100
