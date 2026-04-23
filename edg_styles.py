import streamlit as st

def apply_global_styles():
    st.markdown(
        """
        <style>
        /* Future global styling goes here */
        </style>
        """,
        unsafe_allow_html=True,
    )