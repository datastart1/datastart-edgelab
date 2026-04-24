import streamlit as st

from edg_auth import login


def render_login_page() -> None:
    st.set_page_config(page_title="Datastart EdgeLab", layout="wide")

    left, centre, right = st.columns([1, 1.2, 1])

    with centre:
        st.markdown("## Datastart EdgeLab")
        st.markdown("Sign in to access the application.")

        with st.form("login_form", clear_on_submit=False, enter_to_submit=False):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            if not email.strip():
                st.error("Please enter your email address.")
            elif not password:
                st.error("Please enter your password.")
            else:
                ok = login(email.strip(), password)
                if ok:
                    st.rerun()
                else:
                    st.error(st.session_state.get("auth_error", "Login failed."))
        