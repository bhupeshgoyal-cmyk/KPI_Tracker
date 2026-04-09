import streamlit as st
import pandas as pd

# Lazy load users to avoid circular imports
_users_cache = None


def _load_users(force_refresh=False):
    """Load users from Google Sheet or fallback to hardcoded list."""
    global _users_cache
    if _users_cache is not None and not force_refresh:
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


def clear_user_cache():
    """Clear the user cache to force reload from Google Sheet on next login."""
    global _users_cache, _USER_LOOKUP
    _users_cache = None
    _USER_LOOKUP = None


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
        role = u.get("role") or u.get("Role") or "User"  # Default role is "User"
        
        if email:  # Only add if email exists
            # Parse multiple departments if comma-separated
            dept_list = []
            if department:
                dept_str = str(department).strip()
                # Split by comma if multiple departments, otherwise single department
                dept_list = [d.strip() for d in dept_str.split(",") if d.strip()]
            
            # Check if user is admin
            is_admin = role.strip().lower() in ["admin", "administrator"]
            
            normalized_users.append({
                "email": str(email).strip(),
                "name": str(name).strip() if name else "Unknown",
                "departments": dept_list if dept_list else ["Unknown"],  # Store as list
                "role": role.strip(),
                "is_admin": is_admin
            })
    
    return {u["email"].lower(): u for u in normalized_users}


_USER_LOOKUP = None


def _get_user_lookup(force_refresh=False):
    """Get the cached user lookup dict."""
    global _USER_LOOKUP
    if _USER_LOOKUP is None or force_refresh:
        if force_refresh:
            _load_users(force_refresh=True)
        _USER_LOOKUP = _build_user_lookup()
    return _USER_LOOKUP


def _validate_email(email: str, force_refresh=False) -> dict | None:
    """Return user dict if email is recognised, else None.
    
    Args:
        email: Email address to validate
        force_refresh: If True, reload users from Google Sheet
    """
    lookup = _get_user_lookup(force_refresh=force_refresh)
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

    # Try to validate email (with cache)
    user = _validate_email(email)
    
    # If not found and cache exists, try force refresh in case users sheet was updated
    if user is None:
        user = _validate_email(email, force_refresh=True)
    
    if user is None:
        st.error("Email not recognised. Contact your administrator.")
        return

    st.session_state.user = {
        "email":       user["email"],
        "name":        user["name"],
        "departments": user["departments"],  # Store as list
        "department":  user["departments"][0] if user["departments"] else "Unknown",  # Default to first
        "is_admin":    user.get("is_admin", False),  # Store admin status
        "role":        user.get("role", "User"),
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
