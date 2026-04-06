import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

import config

# Google Sheets API scopes required for read/write access
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Connecting to Google Sheets…")
def _get_client() -> gspread.Client:
    """Authenticate and return a gspread client. Cached for the app lifetime."""
    creds_dict = config.get_google_creds_dict()
    if creds_dict:
        creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
    else:
        creds = Credentials.from_service_account_file(config.GOOGLE_CREDS_JSON, scopes=_SCOPES)
    return gspread.authorize(creds)


def _get_sheet(tab_name: str) -> gspread.Worksheet:
    """Return a worksheet by tab name."""
    client = _get_client()
    spreadsheet = client.open_by_key(config.SHEET_ID)
    return spreadsheet.worksheet(tab_name)


def _sheet_to_df(tab_name: str) -> pd.DataFrame:
    """Read an entire sheet tab into a DataFrame."""
    sheet = _get_sheet(tab_name)
    records = sheet.get_all_records()
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# KPI Registry
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner="Loading KPIs…")
def load_kpis(department: str, month: str) -> pd.DataFrame:
    """
    Return KPIs for a given department and month (format: YYYY-MM).
    Results are cached for 5 minutes.
    """
    df = _sheet_to_df(config.KPI_REGISTRY_TAB)

    for col in [config.KPI_COL_TARGET, config.KPI_COL_GREEN,
                config.KPI_COL_AMBER, config.KPI_COL_RED]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    mask = (
        (df[config.KPI_COL_DEPARTMENT] == department) &
        (df[config.KPI_COL_MONTH].astype(str) == month)
    )
    return df[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Actuals
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner="Loading actuals…")
def load_actuals(department: str, month: str) -> pd.DataFrame:
    """
    Return all actuals for KPIs belonging to the given department and month.
    Results are cached for 60 seconds.
    """
    actuals_df = _sheet_to_df(config.ACTUALS_TAB)
    kpis_df = load_kpis(department, month)

    if actuals_df.empty or config.ACTUAL_COL_KPI_CODE not in actuals_df.columns:
        return pd.DataFrame(columns=[
            config.ACTUAL_COL_DATE, config.ACTUAL_COL_KPI_CODE,
            config.ACTUAL_COL_ACTUAL, config.ACTUAL_COL_COMMENT,
            config.ACTUAL_COL_UPDATED_BY,
        ])

    dept_kpi_codes = kpis_df[config.KPI_COL_CODE].tolist()

    filtered = actuals_df[
        actuals_df[config.ACTUAL_COL_KPI_CODE].isin(dept_kpi_codes)
    ].copy()

    filtered[config.ACTUAL_COL_DATE] = pd.to_datetime(
        filtered[config.ACTUAL_COL_DATE], errors="coerce"
    )
    filtered[config.ACTUAL_COL_ACTUAL] = pd.to_numeric(
        filtered[config.ACTUAL_COL_ACTUAL], errors="coerce"
    )

    return filtered.sort_values(config.ACTUAL_COL_DATE, ascending=False).reset_index(drop=True)


def append_actual(
    date: str,
    kpi_code: str,
    actual: float,
    comment: str,
    updated_by: str,
) -> None:
    """
    Append one row to the Actuals sheet.
    Clears the load_actuals cache so the next read picks up the new row.
    """
    sheet = _get_sheet(config.ACTUALS_TAB)
    sheet.append_row(
        [date, kpi_code, actual, comment, updated_by],
        value_input_option="USER_ENTERED",
    )
    load_actuals.clear()
    load_kpis.clear()


# ---------------------------------------------------------------------------
# RAG status
# ---------------------------------------------------------------------------

def compute_rag(actual: float, target: float, green: float, amber: float) -> str:
    """
    Return 'Green', 'Amber', or 'Red' based on how actual compares to thresholds.

    Convention (higher = better):
      actual >= green threshold  →  Green
      actual >= amber threshold  →  Amber
      otherwise                  →  Red

    Adjust the comparison direction in config if your KPIs are lower-is-better.
    """
    if pd.isna(actual):
        return "Unknown"
    if actual >= green:
        return "Green"
    if actual >= amber:
        return "Amber"
    return "Red"


def enrich_with_rag(kpis_df: pd.DataFrame, actuals_df: pd.DataFrame) -> pd.DataFrame:
    """
    Join the latest actual onto each KPI row and add a RAG Status column.
    Returns a copy of kpis_df with extra columns: Latest Actual, RAG Status.
    """
    if actuals_df.empty:
        kpis_df = kpis_df.copy()
        kpis_df["Latest Actual"] = None
        kpis_df["RAG Status"] = "Unknown"
        return kpis_df

    latest = (
        actuals_df.sort_values(config.ACTUAL_COL_DATE)
        .groupby(config.ACTUAL_COL_KPI_CODE)
        .last()
        .reset_index()[[config.ACTUAL_COL_KPI_CODE, config.ACTUAL_COL_ACTUAL]]
        .rename(columns={config.ACTUAL_COL_ACTUAL: "Latest Actual"})
    )

    merged = kpis_df.merge(latest, on=config.KPI_COL_CODE, how="left")

    merged["RAG Status"] = merged.apply(
        lambda row: compute_rag(
            row["Latest Actual"],
            row[config.KPI_COL_TARGET],
            row[config.KPI_COL_GREEN],
            row[config.KPI_COL_AMBER],
        ),
        axis=1,
    )

    return merged
