import os
import json
from dotenv import load_dotenv

load_dotenv()

# Google Sheets
SHEET_ID = os.getenv("SHEET_ID", "")

# Credentials: prefer inline JSON string (Streamlit Cloud) over file path (local dev)
_CREDS_JSON_STR   = os.getenv("GOOGLE_CREDS_JSON_STR", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "credentials/service_account.json")

def get_google_creds_dict() -> dict | None:
    """Return credentials as a dict. Works for both local file and cloud secret."""
    if _CREDS_JSON_STR:
        return json.loads(_CREDS_JSON_STR)
    return None

# Sheet tab names
KPI_REGISTRY_TAB  = "KPI Registry"
ACTUALS_TAB       = "Actuals"
USERS_TAB         = "Users"
INSIGHTS_LOG_TAB  = "Insights Log"

INSIGHTS_WEEKLY_CAP = 2

# Column names — Users sheet
USER_COL_EMAIL      = "Email"
USER_COL_NAME       = "Name"
USER_COL_DEPARTMENT = "Department"

# Column names — KPI Registry sheet
KPI_COL_CODE           = "KPI Code"
KPI_COL_NAME           = "KPI Name"
KPI_COL_OWNER          = "Owner"  # Name of person responsible for the KPI
KPI_COL_UNIT           = "Unit"   # Unit of measurement (e.g., %, $, Count)
KPI_COL_DEPARTMENT     = "Department"
KPI_COL_MONTH          = "Month"
KPI_COL_TARGET         = "Target"
KPI_COL_TARGET_DESC    = "Target Description"
KPI_COL_GREEN          = "Green Threshold"
KPI_COL_AMBER          = "Amber Threshold"
KPI_COL_RED            = "Red Threshold"
KPI_COL_WEEKLY_TRACKED = "Weekly Tracked"
KPI_COL_TYPE           = "KPI Type"  # "Input" or "Output"
KPI_COL_P0             = "P0"        # "P0" or blank

# Column names — Actuals sheet
ACTUAL_COL_DATE       = "Date"
ACTUAL_COL_KPI_CODE   = "KPI Code"
ACTUAL_COL_ACTUAL     = "Actual"
ACTUAL_COL_COMMENT    = "Comment"
ACTUAL_COL_UPDATED_BY = "Updated By"
ACTUAL_COL_MONTH      = "Month"

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = "gpt-4o-mini"

# Financial year month order: Apr → Mar
FY_MONTH_ORDER = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
