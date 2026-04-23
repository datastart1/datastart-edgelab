
import streamlit as st

from edg_app import main as render_application
from edg_auth import is_authenticated
from edg_login_page import render_login_page
from edg_styles import apply_global_styles

apply_global_styles()

def main() -> None:
    st.set_page_config(page_title="Datastart EdgeLab", layout="wide")

    if is_authenticated():
        render_application()
    else:
        render_login_page()


if __name__ == "__main__":
    main()
