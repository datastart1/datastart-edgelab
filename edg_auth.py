import json
from pathlib import Path
from typing import Optional

import requests
import streamlit as st
import time

API_BASE_URL = "https://datastart-edgelab-api.onrender.com"
AUTH_FILE = Path(".edgelab_auth.json")


def ensure_auth_state() -> None:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "auth_token" not in st.session_state:
        st.session_state.auth_token = ""
    if "auth_email" not in st.session_state:
        st.session_state.auth_email = ""
    if "auth_full_name" not in st.session_state:
        st.session_state.auth_full_name = ""
    if "auth_plan" not in st.session_state:
        st.session_state.auth_plan = ""
    if "auth_error" not in st.session_state:
        st.session_state.auth_error = ""

    _load_saved_auth()


def _load_saved_auth() -> None:
    if st.session_state.authenticated:
        return
    if not AUTH_FILE.exists():
        return

    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    token = data.get("token", "").strip()
    if not token:
        return

    user = fetch_current_user(token)
    if not user:
        clear_auth_file()
        return

    st.session_state.authenticated = True
    st.session_state.auth_token = token
    st.session_state.auth_email = user["email"]
    st.session_state.auth_full_name = user["full_name"]
    st.session_state.auth_plan = user["plan"]


def _save_auth_file(token: str) -> None:
    AUTH_FILE.write_text(json.dumps({"token": token}), encoding="utf-8")


def clear_auth_file() -> None:
    if AUTH_FILE.exists():
        AUTH_FILE.unlink()


def is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated", False))


def login(email: str, password: str) -> bool:
    st.session_state.auth_error = ""

    response = None

    for attempt in range(2):
        try:
            response = requests.post(
                f"{API_BASE_URL}/auth/login",
                json={"email": email, "password": password},
                timeout=60,
            )
            break
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(5)  # give Render time to wake up
            else:
                st.session_state.auth_error = f"Could not reach the login service: {exc}"
                return False
    
    if response.status_code != 200:
        try:
            detail = response.json().get("detail", "Login failed.")
        except Exception:
            detail = "Login failed."
        st.session_state.auth_error = detail
        return False

    payload = response.json()
    token = payload.get("token", "").strip()
    if not token:
        st.session_state.auth_error = "Login succeeded but no token was returned."
        return False

    st.session_state.authenticated = True
    st.session_state.auth_token = token
    st.session_state.auth_email = payload.get("email", email)
    st.session_state.auth_full_name = payload.get("full_name", "")
    st.session_state.auth_plan = payload.get("plan", "")
    _save_auth_file(token)
    return True


def fetch_current_user(token: Optional[str] = None) -> Optional[dict]:
    token = token or st.session_state.get("auth_token", "")
    if not token:
        return None

    try:
        response = requests.get(
            f"{API_BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    data = response.json()
    if not data.get("authenticated"):
        return None
    return data


def logout() -> None:
    st.session_state.authenticated = False
    st.session_state.auth_token = ""
    st.session_state.auth_email = ""
    st.session_state.auth_full_name = ""
    st.session_state.auth_plan = ""
    st.session_state.auth_error = ""
    clear_auth_file()