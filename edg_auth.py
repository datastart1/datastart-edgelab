
import re
from typing import Optional, Tuple

import streamlit as st

AUTH_STATE_KEY = "auth_state"


def _default_auth_state() -> dict:
    return {
        "is_authenticated": False,
        "email": "",
        "token": "",
    }


def initialize_auth_state() -> None:
    if AUTH_STATE_KEY not in st.session_state:
        st.session_state[AUTH_STATE_KEY] = _default_auth_state()


def is_authenticated() -> bool:
    initialize_auth_state()
    return bool(st.session_state[AUTH_STATE_KEY].get("is_authenticated", False))


def get_auth_user() -> Optional[str]:
    initialize_auth_state()
    email = st.session_state[AUTH_STATE_KEY].get("email", "").strip()
    return email or None


def _validate_credentials(email: str, password: str) -> Tuple[bool, str]:
    email = email.strip()
    if not email:
        return False, "Please enter your email address."
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False, "Please enter a valid email address."
    if not password:
        return False, "Please enter your password."
    if len(password) < 6:
        return False, "Password must be at least 6 characters long."
    return True, ""


def login(email: str, password: str) -> Tuple[bool, str]:
    initialize_auth_state()
    ok, message = _validate_credentials(email, password)
    if not ok:
        return False, message

    # Mock authentication only for now. Replace this with a real API call later.
    st.session_state[AUTH_STATE_KEY] = {
        "is_authenticated": True,
        "email": email.strip(),
        "token": f"mock-token-for:{email.strip().lower()}",
    }
    return True, "Signed in successfully."


def logout() -> None:
    st.session_state[AUTH_STATE_KEY] = _default_auth_state()
