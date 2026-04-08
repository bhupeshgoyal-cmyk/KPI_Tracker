import streamlit as st
import pandas as pd

# Lazy load users to avoid circular imports
_users_cache = None


def _load_users():
    """Load users from Google Sheet or fallback to hardcoded list."""
    global _users_cache
    if _users_cache is not None:
        return _users_cache
    
    try:
        # Try to load from Google Sheet
        from data_loader import _sheet_to_df
        import config
        
        users_df = _sheet_to_df(config.USERS_TAB)
        if not users_df.empty:
            # Convert DataFrame to list of dicts
            _users_cache = users_df.to_dict('records')
            return _users_cache
    except Exception:
        pass
    
    # Fallback to hardcoded user table
    _users_cache = [
        {"email": "bhupesh.goyal@stashfin.com", "name": "Bhupesh", "department": "Strategy"},
        {"email": "alice@company.com",          "name": "Alice",   "department": "Finance"},
        {"email": "bob@company.com",            "name": "Bob",     "department": "Operations"},
        {"email": "carol@company.com",          "name": "Carol",   "department": "HR"},
        {"email": "david@company.com",          "name": "David",   "department": "Technology"},
    ]
    return _users_cache


def _build_user_lookup():
    """Build a case-insensitive email lookup from users."""
    users = _load_users()
    
    # Normalize column names to handle both formats
    normalized_users = []
    for u in users:
        # Handle column name variations from Google Sheet
        email = u.get("email") or u.get("Email") or u.get(list(u.keys())[0])
        name = u.get("name") or u.get("Name")
        department = u.get("department") or u.get("Department")
        
        if email:  # Only add if email exists
            normalized_users.append({
                "email": str(email).strip(),
                "name": str(name).strip() if name else "Unknown",
                "department": str(department).strip() if department else "Unknown"
            })
    
    return {u["email"].lower(): u for u in normalized_users}


_USER_LOOKUP = None


def _get_user_lookup():
    """Get the cached user lookup dict."""
    global _USER_LOOKUP
    if _USER_LOOKUP is None:
        _USER_LOOKUP = _build_user_lookup()
    return _USER_LOOKUP


def _validate_email(email: str) -> dict | None:
    """Return user dict if email is recognised, else None."""
    lookup = _get_user_lookup()
    return lookup.get(email.strip().lower())


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
