import os
import json
from dotenv import load_dotenv

load_dotenv()

# Google Sheets
SHEET_ID = os.getenv("SHEET_ID", "")

# Credentials: prefer inline JSON string (Streamlit Cloud) over file path (local dev)
_CREDS_JSON_STR  = os.getenv("GOOGLE_CREDS_JSON_STR", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "credentials/service_account.json")

def get_google_creds_dict() -> dict | None:
    """Return credentials as a dict. Works for both local file and cloud secret."""
    if _CREDS_JSON_STR:
        return json.loads(_CREDS_JSON_STR)
    return None  # signals data_loader to fall back to file path

# Sheet tab names
KPI_REGISTRY_TAB = "KPI Registry"
ACTUALS_TAB = "Actuals"
USERS_TAB = "Users"

# Column names — Users sheet
USER_COL_EMAIL = "Email"
USER_COL_NAME = "Name"
USER_COL_DEPARTMENT = "Department"

# Column names — KPI Registry sheet
KPI_COL_CODE = "KPI Code"
KPI_COL_NAME = "KPI Name"
KPI_COL_DEPARTMENT = "Department"
KPI_COL_MONTH = "Month"
KPI_COL_TARGET = "Target"
KPI_COL_GREEN = "Green Threshold"
KPI_COL_AMBER = "Amber Threshold"
KPI_COL_RED = "Red Threshold"

# Column names — Actuals sheet
ACTUAL_COL_DATE = "Date"
ACTUAL_COL_KPI_CODE = "KPI Code"
ACTUAL_COL_ACTUAL = "Actual"
ACTUAL_COL_COMMENT = "Comment"
ACTUAL_COL_UPDATED_BY = "Updated By"

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
