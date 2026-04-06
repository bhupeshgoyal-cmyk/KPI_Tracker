import streamlit as st

# ---------------------------------------------------------------------------
# Fallback user table — used when Google Sheets is not yet connected.
# Replace or extend this once data_loader.py is wired to the Users sheet.
# ---------------------------------------------------------------------------
USERS = [
    {"email": "alice@company.com",   "name": "Alice",   "department": "Finance"},
    {"email": "bob@company.com",     "name": "Bob",     "department": "Operations"},
    {"email": "carol@company.com",   "name": "Carol",   "department": "HR"},
    {"email": "david@company.com",   "name": "David",   "department": "Technology"},
]

_USER_LOOKUP = {u["email"].lower(): u for u in USERS}


def _validate_email(email: str) -> dict | None:
    """Return user dict if email is recognised, else None."""
    return _USER_LOOKUP.get(email.strip().lower())


def show_login() -> None:
    """Render the login form. Writes to st.session_state on success."""
    st.title("KPI Dashboard")
    st.subheader("Sign in")

    with st.form("login_form"):
        email = st.text_input("Work email address", placeholder="you@company.com")
        submitted = st.form_submit_button("Sign in")

    if not submitted:
        return

    if not email:
        st.error("Please enter your email address.")
        return

    user = _validate_email(email)
    if user is None:
        st.error("Email not recognised. Contact your administrator.")
        return

    st.session_state.user = {
        "email":      user["email"],
        "name":       user["name"],
        "department": user["department"],
    }
    st.rerun()


def logout() -> None:
    """Clear session state and return to the login screen."""
    st.session_state.pop("user", None)
    st.rerun()


def get_current_user() -> dict | None:
    """Return the logged-in user dict, or None if not authenticated."""
    return st.session_state.get("user")


def require_auth() -> dict:
    """
    Call at the top of any page that needs authentication.
    Shows the login screen and stops execution if no user is in session.
    Returns the user dict when authenticated.
    """
    user = get_current_user()
    if user is None:
        show_login()
        st.stop()
    return user
