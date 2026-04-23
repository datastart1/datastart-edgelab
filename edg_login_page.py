
import streamlit as st

from edg_auth import initialize_auth_state, login


def render_login_page() -> None:
    initialize_auth_state()

    st.markdown(
        """
        <div style="margin-top: 0.5rem; margin-bottom: 0.25rem; font-size: 28px; font-weight: 700;">
            📊 Datastart EdgeLab
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Sign in to access the application.")

    left, centre, right = st.columns([1, 1.2, 1])
    with centre:
        st.markdown("### Sign in")
        with st.form("login_form", clear_on_submit=False, enter_to_submit=False):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            success, message = login(email, password)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

        st.info(
            "This is a temporary mocked sign-in screen while the Lemon Squeezy-backed "
            "account flow is being wired in. For now, any valid email and any password "
            "with at least 6 characters will work."
        )
