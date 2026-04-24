import streamlit as st

from edg_auth import logout
from edg_state_helpers import (
    initialize_session_state,
    reset_analysis_state,
)
from edg_ui_helpers import inject_css

from edg_auto_build import ensure_auto_build_state, render_auto_build_tab
from edg_results_page import (
    get_current_filtered_training_df,
    render_active_filters_tab,
    render_column_detail_tab,
    render_results_tab,
)
from edg_setup_page import render_configuration_page

def render_header() -> None:
    st.markdown(
        """
        <div style="
            margin-top: -0.35rem;
            margin-bottom: 0.15rem;
            padding-top: 0;
            line-height: 1.0;
            font-size: 20px;
            font-weight: 700;
        ">
            📊 Datastart EdgeLab
        </div>
        """,
        unsafe_allow_html=True,
    )

    context = st.session_state.base_analysis_context

    if not st.session_state.get("analysis_ready", False):
        st.caption("Load a CSV, confirm column types, and choose key columns.")

    if context is not None and st.session_state.filter_history:
        current_df = get_current_filtered_training_df(context)
        rows = len(current_df)
        step = len(st.session_state.filter_history) - 1
        filters = len(st.session_state.active_filters)

        st.caption(
            f"File: {context.get('file_name','-')} | "
            f"Training rows in play: {rows:,} | Step: {step} | Filters applied: {filters}"
        )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### Account")
        user_email = st.session_state.get("auth_email", "Signed in")
        user_plan = st.session_state.get("auth_plan", "")

        st.caption(user_email)

        if user_plan:
            st.caption(f"Plan: {user_plan}")

        if st.button("Sign out", use_container_width=True):
            logout()
            reset_analysis_state()
            st.rerun()

        st.markdown("---")
        st.markdown("### Controls")

        if st.button("Start New Analysis", use_container_width=True):
            reset_analysis_state()
            st.rerun()

        if st.session_state.analysis_ready and st.session_state.base_analysis_context is not None:
            st.markdown("---")
            ctx = st.session_state.base_analysis_context
            st.markdown("### Current Session")
            st.write(f"**File:** {ctx.get('file_name', '-')}")
            st.write(f"**Split:** {ctx.get('split_method', 'Chronological')}")
            st.write(f"**Training/Test:** {ctx.get('training_pct', 70)}/{ctx.get('test_pct', 30)}")
            st.write(f"**Filters applied:** {len(st.session_state.active_filters)}")

        st.markdown("---")

        with st.expander("Help"):
            st.markdown(
                """
                **Workflow**

                1. Upload CSV  
                2. Configure columns  
                3. Run analysis  
                4. Apply filters  
                5. Validate on test data  

                **Tip:** Prefer simple filters and trust test data more than training.
                """
            )


def render_help_tab() -> None:
    st.markdown(
        """
        ## EdgeLab Help

        **What this tool does**  
        Finds potentially profitable patterns in your data and validates them using out-of-sample testing.

        **Basic workflow**
        1. Upload CSV
        2. Configure columns
        3. Run analysis
        4. Apply suggested or custom filters
        5. Validate on test data
        6. Export selected filters

        **Guidance**
        - Prefer simpler filters
        - Avoid very small filtered samples
        - Chronological split is usually best
        - Trust test data more than training
        """
    )


def render_analysis_workspace() -> None:
    if not st.session_state.analysis_ready:
        st.info("Run the analysis from Configuration first.")
        return

    results = st.session_state.analysis_results
    context = st.session_state.base_analysis_context

    if st.session_state.analysis_notice:
        st.success(st.session_state.analysis_notice)
        st.session_state.analysis_notice = ""

    tabs = st.tabs([
        "Possible Filters",
        "Column Detail",
        "Active Filters",
        "Auto Build",
        "Help",
    ])

    with tabs[0]:
        render_results_tab(results, context)

    with tabs[1]:
        render_column_detail_tab(results)

    with tabs[2]:
        render_active_filters_tab()

    with tabs[3]:
        render_auto_build_tab(results, context)

    with tabs[4]:
        render_help_tab()


def main() -> None:
    st.set_page_config(page_title="Datastart EdgeLab", layout="wide")
    initialize_session_state()
    ensure_auto_build_state()
    inject_css()

    render_header()
    render_sidebar()

    if st.session_state.app_mode == "analysis" and st.session_state.analysis_ready:
        render_analysis_workspace()
    else:
        render_configuration_page()


if __name__ == "__main__":
    main()