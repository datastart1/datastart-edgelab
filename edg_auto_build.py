import math
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from edg_analysis_engine import calculate_grand_totals, run_full_analysis
from edg_filter_helpers import (
    apply_active_filters_sequence,
    apply_filter_to_df,
    calculate_filter_metrics,
)
from edg_state_helpers import rerun_analysis_from_history

AUTO_BUILD_START_OPTIONS = ["All Training Data", "Current Filter State"]
def ensure_auto_build_state() -> None:
    defaults = {
        "auto_build_candidate_steps": [],
        "auto_build_candidate_preview_df": pd.DataFrame(),
        "auto_build_stop_reason": "",
        "auto_build_summary": {},
        "auto_build_rejections_df": pd.DataFrame(),
        "auto_build_progress_df": pd.DataFrame(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def make_stage_e_metric_row(selected_row: pd.Series) -> dict[str, Any]:
    return {
        "Filter No": int(selected_row["Filter No"]),
        "Column ID": str(selected_row["Column ID"]),
        "Filter": str(selected_row["Filter"]),
        "Rows": int(selected_row["Rows"]),
        "Win %": float(selected_row["Win %"]),
        "Stake": float(selected_row["Stake"]),
        "P/L Increase": float(selected_row["P/L Increase"]),
        "New P/L": float(selected_row["New P/L"]),
        "New ROI%": float(selected_row["New ROI%"]),
        "filter_kind": "stage_e",
    }

def calculate_roi_from_totals(totals: dict[str, Any]) -> float:
    stake = totals.get("stake", 0.0)
    pl = totals.get("pl", 0.0)
    return (pl / stake * 100) if stake != 0 else 0.0

def build_auto_build_progress_chart(progress_df: pd.DataFrame):
    if progress_df.empty:
        return None

    working = progress_df.copy()

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=working["Step"],
            y=working["Training ROI%"],
            mode="lines+markers",
            line=dict(width=3, color="green"),
            marker=dict(size=6, color="green"),
            name="Training ROI%",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=working["Step"],
            y=working["Test ROI%"],
            mode="lines+markers",
            line=dict(width=3, color="blue"),
            marker=dict(size=6, color="blue"),
            name="Test ROI%",
        )
    )

    fig.update_layout(
        title="Auto Build Progress – Training vs Test ROI",
        height=320,
        margin=dict(l=20, r=20, t=40, b=50),
        xaxis=dict(title="Step"),
        yaxis=dict(title="ROI%"),
    )

    return fig

def get_current_filtered_training_df(context: dict[str, Any] | None) -> pd.DataFrame:
    if context is None:
        return pd.DataFrame()

    original_training_df = context.get("original_training_df", pd.DataFrame())
    if original_training_df.empty:
        return pd.DataFrame()

    return apply_active_filters_sequence(
        original_training_df.copy(),
        st.session_state.active_filters,
    )

def get_current_start_state(start_mode: str, context: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if start_mode == "Current Filter State" and st.session_state.active_filters:
        working_training_df = get_current_filtered_training_df(context)
        accepted_steps = [m.copy() for m in st.session_state.active_filters]
        return working_training_df, accepted_steps

    return context["original_training_df"].copy(), []

def run_auto_build_candidate(
    context: dict[str, Any],
    start_mode: str,
    max_filters: int,
    min_training_rows_pct: int,
    min_roi_improvement: float,
    max_test_roi_drop: float,
    min_test_rows: int,
) -> tuple[list[dict[str, Any]], pd.DataFrame, str, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    original_training_df = context["original_training_df"].copy()
    original_test_df = context.get("original_test_df", pd.DataFrame()).copy()

    event_date_col = context["event_date_col"]
    stake_col = context["stake_col"]
    target_col = context["target_col"]
    column_types = context["column_types"]
    analyze_flags = context["analyze_flags"]

    working_training_df, accepted_steps = get_current_start_state(start_mode, context)

    preview_rows: list[dict[str, Any]] = []
    rejection_rows: list[dict[str, Any]] = []
    progress_rows: list[dict[str, Any]] = []

    current_training_totals = calculate_grand_totals(working_training_df, stake_col, target_col)
    current_training_roi = calculate_roi_from_totals(current_training_totals)

    if not original_test_df.empty:
        current_test_df = apply_active_filters_sequence(original_test_df.copy(), accepted_steps)
        current_test_totals = calculate_grand_totals(current_test_df, stake_col, target_col)
        current_test_roi = calculate_roi_from_totals(current_test_totals)
        current_test_rows = current_test_totals["runs"]
    else:
        current_test_roi = 0.0
        current_test_rows = 0

    progress_rows.append({
        "Step": 0,
        "Label": "Start",
        "Training ROI%": round(current_training_roi, 1),
        "Test ROI%": round(current_test_roi, 1),
        "Training Rows": current_training_totals["runs"],
        "Test Rows": current_test_rows,
    })

    stop_reason = "No candidate filters were accepted."

    min_training_rows_abs = math.ceil(len(original_training_df) * (min_training_rows_pct / 100))

    starting_step_number = len(accepted_steps)

    for local_step_no in range(1, max_filters + 1):
        analysis_results = run_full_analysis(
            df_input=working_training_df.copy(),
            event_date_col=event_date_col,
            stake_col=stake_col,
            target_col=target_col,
            column_types=column_types,
            analyze_flags=analyze_flags,
            calculate_filter_metrics_fn=calculate_filter_metrics,
            apply_filter_to_df_fn=apply_filter_to_df,
        )

        if "error" in analysis_results:
            stop_reason = f"Stopped because analysis returned an error: {analysis_results['error']}"
            break

        filters_df = analysis_results["stage_e_filters"]

        if filters_df.empty:
            stop_reason = "Stopped because no further suggested filters were available."
            break

        accepted_this_round = False
        global_step_no = starting_step_number + local_step_no

        for _, selected_row in filters_df.iterrows():
            candidate_metric = make_stage_e_metric_row(selected_row)

            candidate_training_df = apply_filter_to_df(
                working_training_df.copy(),
                candidate_metric["Column ID"],
                candidate_metric["Filter"],
            )

            if candidate_training_df.empty:
                rejection_rows.append({
                    "Step": global_step_no,
                    "Column ID": candidate_metric["Column ID"],
                    "Filter": candidate_metric["Filter"],
                    "Rejected Because": "Returned no training rows",
                })
                continue

            candidate_training_totals = calculate_grand_totals(candidate_training_df, stake_col, target_col)
            candidate_training_rows = candidate_training_totals["runs"]
            candidate_training_roi = calculate_roi_from_totals(candidate_training_totals)
            roi_gain = candidate_training_roi - current_training_roi

            if candidate_training_rows < min_training_rows_abs:
                rejection_rows.append({
                    "Step": global_step_no,
                    "Column ID": candidate_metric["Column ID"],
                    "Filter": candidate_metric["Filter"],
                    "Rejected Because": f"Training rows {candidate_training_rows} below minimum {min_training_rows_abs}",
                })
                continue

            if roi_gain < min_roi_improvement:
                rejection_rows.append({
                    "Step": global_step_no,
                    "Column ID": candidate_metric["Column ID"],
                    "Filter": candidate_metric["Filter"],
                    "Rejected Because": f"ROI gain {roi_gain:.1f} below minimum {min_roi_improvement:.1f}",
                })
                continue

            tentative_steps = accepted_steps + [candidate_metric]

            if not original_test_df.empty:
                candidate_test_df = apply_active_filters_sequence(original_test_df.copy(), tentative_steps)
                candidate_test_totals = calculate_grand_totals(candidate_test_df, stake_col, target_col)
                candidate_test_rows = candidate_test_totals["runs"]
                candidate_test_roi = calculate_roi_from_totals(candidate_test_totals)
            else:
                candidate_test_rows = 0
                candidate_test_roi = 0.0

            if not original_test_df.empty and candidate_test_rows < min_test_rows:
                rejection_rows.append({
                    "Step": global_step_no,
                    "Column ID": candidate_metric["Column ID"],
                    "Filter": candidate_metric["Filter"],
                    "Rejected Because": f"Test rows {candidate_test_rows} below minimum {min_test_rows}",
                })
                continue

            test_roi_drop = current_test_roi - candidate_test_roi
            if not original_test_df.empty and test_roi_drop > max_test_roi_drop:
                rejection_rows.append({
                    "Step": global_step_no,
                    "Column ID": candidate_metric["Column ID"],
                    "Filter": candidate_metric["Filter"],
                    "Rejected Because": f"Test ROI drop {test_roi_drop:.1f} exceeds maximum {max_test_roi_drop:.1f}",
                })
                continue

            accepted_steps.append(candidate_metric)
            working_training_df = candidate_training_df.copy()
            current_training_roi = candidate_training_roi
            current_test_roi = candidate_test_roi
            current_test_rows = candidate_test_rows

            preview_rows.append({
                "Step": global_step_no,
                "Column ID": candidate_metric["Column ID"],
                "Filter": candidate_metric["Filter"],
                "Training Rows": candidate_training_rows,
                "Training ROI%": round(candidate_training_roi, 1),
                "ROI Gain": round(roi_gain, 1),
                "Test Rows": candidate_test_rows,
                "Test ROI%": round(candidate_test_roi, 1),
            })

            progress_rows.append({
                "Step": global_step_no,
                "Label": f"{candidate_metric['Column ID']} | {candidate_metric['Filter']}",
                "Training ROI%": round(candidate_training_roi, 1),
                "Test ROI%": round(candidate_test_roi, 1),
                "Training Rows": candidate_training_rows,
                "Test Rows": candidate_test_rows,
            })

            accepted_this_round = True
            break

        if not accepted_this_round:
            stop_reason = "Stopped because no remaining suggested filter passed the stopping rules."
            break

    if len(preview_rows) >= max_filters:
        stop_reason = f"Stopped after reaching the maximum of {max_filters} new filter(s)."

    preview_df = pd.DataFrame(preview_rows)
    rejection_df = pd.DataFrame(rejection_rows)
    progress_df = pd.DataFrame(progress_rows)

    final_training_totals = calculate_grand_totals(working_training_df, stake_col, target_col)
    final_test_df = apply_active_filters_sequence(original_test_df.copy(), accepted_steps) if not original_test_df.empty else pd.DataFrame()
    final_test_totals = calculate_grand_totals(final_test_df, stake_col, target_col) if not final_test_df.empty else {"runs": 0, "stake": 0.0, "pl": 0.0}

    summary = {
        "accepted_filters_total": len(accepted_steps),
        "accepted_filters_new": len(preview_rows),
        "final_training_rows": final_training_totals["runs"],
        "final_training_roi": round(calculate_roi_from_totals(final_training_totals), 1),
        "final_test_rows": final_test_totals["runs"],
        "final_test_roi": round(calculate_roi_from_totals(final_test_totals), 1),
        "start_mode": start_mode,
    }

    return accepted_steps, preview_df, stop_reason, summary, rejection_df, progress_df

def apply_auto_build_candidate_to_live_state() -> None:
    context = st.session_state.base_analysis_context
    candidate_steps = st.session_state.get("auto_build_candidate_steps", [])

    if context is None or not candidate_steps:
        return

    original_training_df = context["original_training_df"].copy()

    st.session_state.active_filters = []
    st.session_state.filter_history = [{
        "description": "All Training Data",
        "column": None,
        "filter_text": None,
        "metrics": {
            "Filter No": 0,
            "Column ID": "",
            "Filter": "All Training Data",
            "Rows": 0,
            "Win %": 0.0,
            "Stake": 0.0,
            "P/L Increase": 0.0,
            "New P/L": 0.0,
            "New ROI%": 0.0,
        },
    }]

    working_df = original_training_df.copy()

    for step in candidate_steps:
        working_df = apply_filter_to_df(
            working_df,
            step["Column ID"],
            step["Filter"],
        )

        metric = step.copy()

        st.session_state.filter_history.append({
            "description": f"{metric['Column ID']} — {metric['Filter']}",
            "column": metric["Column ID"],
            "filter_text": metric["Filter"],
            "metrics": metric,
        })
        st.session_state.active_filters.append(metric)

    rerun_analysis_from_history()
    st.session_state.analysis_notice = f"Auto Build candidate applied: {len(candidate_steps)} total filter(s)."


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
            📊 Datastart EdgeFinder
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


def render_test_validation_panel(results) -> None:
    test_validation = results.get("test_validation")

    if not test_validation or not test_validation.get("available", False):
        if test_validation and test_validation.get("message"):
            st.info(test_validation["message"])
        return

    st.subheader("Training and Test Data Comparison")
    st.caption(test_validation.get("split_label", ""))

    context = st.session_state.base_analysis_context
    latest_training_df = get_current_filtered_training_df(context)

    test_df_original = context.get("original_test_df", pd.DataFrame()) if context is not None else pd.DataFrame()
    filtered_test_df = apply_active_filters_sequence(
        test_df_original.copy(),
        st.session_state.active_filters,
    ) if not test_df_original.empty else pd.DataFrame()

    top_left, top_right = st.columns([0.95, 1.05])

    with top_left:
        st.dataframe(
            style_results_dataframe(test_validation["summary_df"]),
            use_container_width=True,
            hide_index=True,
            height=110,
        )

    with top_right:
        st.write(f"**Status:** {test_validation['status']}")
        st.write(f"**ROI change vs training:** {test_validation['roi_delta']:.1f} pts")
        st.write(f"**Win% change vs training:** {test_validation['win_pct_delta']:.1f} pts")
        st.write(f"**P/L change vs training:** {test_validation['pl_delta']:,.0f}")
        st.write(f"**Original test rows:** {test_validation['test_rows_original']:,}")
        st.write(f"**Test rows after filters:** {test_validation['test_rows_after_filters']:,}")

    chart_left, chart_right = st.columns(2)

    with chart_left:
        if context is not None and not latest_training_df.empty:
            fig_train = make_active_filters_cumulative_date_chart(
                df=latest_training_df,
                event_date_col=context["event_date_col"],
                profit_col=context["target_col"],
                title="Training Data – Cumulative P/L by Date",
            )
            if fig_train is not None:
                st.plotly_chart(fig_train, use_container_width=True, key="possible_filters_training_date_chart")
            else:
                st.info("No usable training date/profit data available.")
        else:
            st.info("No filtered training data available.")

    with chart_right:
        if context is not None and not filtered_test_df.empty:
            fig_test = make_active_filters_cumulative_date_chart(
                df=filtered_test_df,
                event_date_col=context["event_date_col"],
                profit_col=context["target_col"],
                title="Test Data – Cumulative P/L by Date",
            )
            if fig_test is not None:
                st.plotly_chart(fig_test, use_container_width=True, key="possible_filters_test_date_chart")
            else:
                st.info("No usable test date/profit data available.")
        else:
            st.info("No filtered test data available.")


def render_results_tab(results, context) -> None:
    if st.session_state.get("clear_custom_filter_inputs", False):
        st.session_state.custom_filter_value1 = ""
        st.session_state.custom_filter_value2 = ""
        st.session_state.clear_custom_filter_inputs = False

    st.caption("Review possible filters ranked by ROI improvement.")

    st.caption(
        f"Training dataset analysis. "
        f"Split method: {context.get('split_method', 'Chronological')} | "
        f"Training/Test: {context.get('training_pct', 70)}/{context.get('test_pct', 30)}"
    )

    stats_left, stats_right = st.columns(2)
    with stats_left:
        st.write(f"**Longest Winning Run:** {results['grand_totals']['longest_winning_run']}")
    with stats_right:
        st.write(f"**Longest Losing Run:** {results['grand_totals']['longest_losing_run']}")

    render_test_validation_panel(results)

    st.subheader("Possible Filters")
    filters_df = results["stage_e_filters"]

    if filters_df.empty:
        st.info("No meaningful filters found.")
    else:
        st.dataframe(
            style_possible_filters_dataframe(filters_df),
            use_container_width=True,
            hide_index=True,
            height=250,
        )

        action_col1, action_col2, action_col3, action_col4, spacer_col = st.columns([0.45, 0.7, 0.7, 0.7, 2.2])

        with action_col1:
            selected_filter_no = st.selectbox(
                "Filter No",
                options=filters_df["Filter No"].tolist(),
                index=0,
                key="apply_filter_select",
            )

        with action_col2:
            st.write("")
            st.write("")
            apply_clicked = st.button("Apply Filter", use_container_width=True)

        with action_col3:
            st.write("")
            st.write("")
            undo_clicked = st.button("Undo Last Filter", use_container_width=True)

        with action_col4:
            st.write("")
            st.write("")
            refresh_clicked = st.button("Refresh Analysis", use_container_width=True)

        if apply_clicked:
            selected_row = filters_df.loc[filters_df["Filter No"] == selected_filter_no].iloc[0]

            current_df = get_current_filtered_training_df(context)
            new_df = apply_filter_to_df(
                current_df,
                selected_row["Column ID"],
                selected_row["Filter"],
            )

            metrics = make_stage_e_metric_row(selected_row)

            st.session_state.filter_history.append({
                "df": new_df.copy(),
                "description": f"{selected_row['Column ID']} — {selected_row['Filter']}",
                "column": selected_row["Column ID"],
                "filter_text": selected_row["Filter"],
                "metrics": metrics,
            })

            st.session_state.active_filters.append(metrics)

            rerun_analysis_from_history()
            st.session_state.analysis_notice = (
                f"Filter applied: {selected_row['Column ID']} — {selected_row['Filter']}"
            )
            st.rerun()

        if undo_clicked:
            if len(st.session_state.filter_history) > 1:
                last_entry = st.session_state.filter_history.pop()
                if st.session_state.active_filters:
                    st.session_state.active_filters.pop()

                rerun_analysis_from_history()
                st.session_state.analysis_notice = f"Removed filter: {last_entry['description']}"
                st.rerun()

        if refresh_clicked:
            rerun_analysis_from_history()
            st.rerun()

    st.subheader("Create Your Own Filter")
    custom_col1, custom_col2, custom_col3, custom_col4, custom_col5 = st.columns([1.3, 1, 0.9, 0.9, 0.9])

    with custom_col1:
        custom_column = st.selectbox(
            "Column Name",
            options=results["columns_to_analyze"],
            key="custom_filter_column",
        )

    with custom_col2:
        custom_operator = st.selectbox(
            "Operator",
            options=CUSTOM_OPERATORS,
            key="custom_filter_operator",
        )

    with custom_col3:
        custom_value1 = st.text_input("Value a", key="custom_filter_value1")

    needs_value_b = custom_operator in [">= and <=", "< a or > b"]

    with custom_col4:
        custom_value2 = st.text_input(
            "Value b",
            key="custom_filter_value2",
            disabled=not needs_value_b,
        )

    with custom_col5:
        st.write("")
        st.write("")
        apply_custom = st.button("Apply Custom Filter", use_container_width=True)

    if apply_custom:
        if custom_operator == ">= and <=":
            try:
                a = float(custom_value1)
                b = float(custom_value2)
                if b < a:
                    st.error("For an inclusive range, value b must be greater than or equal to value a.")
                    st.stop()
            except Exception:
                st.error("Please enter valid numeric values for a and b.")
                st.stop()

            filter_text = f">= {custom_value1} and <= {custom_value2}"

        elif custom_operator == "< a or > b":
            try:
                a = float(custom_value1)
                b = float(custom_value2)
                if b < a:
                    st.error("For an outside-range filter, value b must be greater than or equal to value a.")
                    st.stop()
            except Exception:
                st.error("Please enter valid numeric values for a and b.")
                st.stop()

            filter_text = f"< {custom_value1} or > {custom_value2}"

        else:
            filter_text = f"{custom_operator} {custom_value1}"

        current_df = get_current_filtered_training_df(context)
        new_df = apply_custom_filter_to_df(
            current_df,
            custom_column,
            custom_operator,
            custom_value1,
            custom_value2,
        )

        if new_df.empty:
            st.error("That custom filter returned no rows.")
        else:
            base_pl = calculate_grand_totals(current_df, context["stake_col"], context["target_col"])["pl"]
            metrics = calculate_filter_metrics(new_df, context["stake_col"], context["target_col"], base_pl)
            metrics_row = {
                "Filter No": len(st.session_state.active_filters) + 1,
                "Column ID": custom_column,
                "Filter": filter_text,
                **metrics,
                "filter_kind": "custom",
                "operator": custom_operator,
                "value1": custom_value1,
                "value2": custom_value2,
            }

            st.session_state.filter_history.append({
                "df": new_df.copy(),
                "description": f"{custom_column} — {filter_text}",
                "column": custom_column,
                "filter_text": filter_text,
                "metrics": metrics_row,
            })
            st.session_state.active_filters.append(metrics_row)

            st.session_state.clear_custom_filter_inputs = True

            rerun_analysis_from_history()
            st.session_state.analysis_notice = f"Custom filter applied: {custom_column} — {filter_text}"
            st.rerun()


def render_column_detail_tab(results) -> None:
    st.caption("Possible filter columns analysed by band")

    columns_to_analyze = results["columns_to_analyze"]

    if not columns_to_analyze:
        st.info("No columns available.")
        return

    col_select_col, _ = st.columns([0.125, 0.875])

    with col_select_col:
        current_col = st.selectbox(
            "Column",
            options=columns_to_analyze,
            key="detail_column_select",
        )

    plan = results["stage_b_plans"][current_col]

    hdr_left, hdr_right = st.columns([1.8, 2.2])
    with hdr_left:
        st.subheader(f"Column Detail: {current_col}")
    with hdr_right:
        st.markdown(
            f"""
            <div class="compact-header-meta">
                <strong>Type:</strong> {plan['selected_type']}
                &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>Plan:</strong> {plan['plan_type']}
                &nbsp;&nbsp;|&nbsp;&nbsp;
                <strong>Groups:</strong> {plan['category_count']}
            </div>
            """,
            unsafe_allow_html=True,
        )

    if current_col in results["stage_d_results"]:
        stage_d = results["stage_d_results"][current_col]
        if stage_d.get("available", False):
            st.markdown(
                f"""
                <div class="stage-d-inline">
                    <strong>Min P/L Point:</strong> {format_value(stage_d['min_value'])}
                    &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
                    <strong>Max P/L Point:</strong> {format_value(stage_d['max_value'])}
                    &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
                    <strong>Filter idea:</strong> {stage_d['suggested_filter']}
                </div>
                """,
                unsafe_allow_html=True,
            )

    table_col, chart_col = st.columns([1.2, 1.8])

    with table_col:
        st.dataframe(
            style_results_dataframe(results["stage_c_results"][current_col]),
            use_container_width=True,
            hide_index=True,
            height=360,
        )

    header_name = results["stage_c_results"][current_col].columns[0]
    bar_title = f"{current_col} – Profit and Loss by {header_name}"
    line_title = f"{current_col} – Cumulative Profit and Loss by {header_name}"

    chart_choice = st.radio(
        "Chart Type",
        ["Bar Chart", "Line Chart"],
        horizontal=True,
        key="detail_chart_choice",
    )

    with chart_col:
        if chart_choice == "Line Chart" and plan["selected_type"] in ["Numeric Continuous", "Numeric Discrete"]:
            current_df = apply_active_filters_sequence(
                st.session_state.base_analysis_context["original_training_df"].copy(),
                st.session_state.active_filters,
            )
            current_df = prepare_sorted_dataframe(
                current_df,
                st.session_state.base_analysis_context["event_date_col"],
            )
            curve_df = build_stage_d_curve_data(
                df_sorted=current_df,
                column_name=current_col,
                profit_col=st.session_state.base_analysis_context["target_col"],
            )
            fig = make_raw_cumulative_line_chart(
                curve_df=curve_df,
                column_name=current_col,
                title=f"{current_col} – Raw Cumulative Profit and Loss",
            )
        elif chart_choice == "Line Chart":
            fig = make_pl_line_chart(results["stage_c_results"][current_col], line_title)
        else:
            fig = make_pl_bar_chart(results["stage_c_results"][current_col], bar_title)

        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key=f"column_detail_chart_{current_col}_{chart_choice}")


def render_active_filters_tab() -> None:
    st.subheader("Active Filters")
    st.caption("Currently active filters with impact on P/L and ROI")

    printable_rows = []

    if not st.session_state.filter_history:
        active_filters_df = pd.DataFrame([{
            "Filter No": 0,
            "Column ID": "None",
            "Filter": "All Training Data",
            "Rows": 0,
            "Win %": 0.0,
            "Stake": 0.0,
            "P/L Increase": 0.0,
            "New P/L": 0.0,
            "New ROI%": 0.0,
        }])
        printable_rows = active_filters_df.to_dict(orient="records")
    else:
        filter_rows = []

        for i, entry in enumerate(st.session_state.filter_history):
            if i == 0:
                context = st.session_state.base_analysis_context

                if context is not None:
                    totals = calculate_grand_totals(
                        context["original_training_df"],
                        context["stake_col"],
                        context["target_col"]
                    )

                    runs = totals["runs"]
                    winners = totals["winners"]
                    stake = totals["stake"]
                    pl = totals["pl"]
                    win_pct = (winners / runs * 100) if runs > 0 else 0.0
                    roi_pct = (pl / stake * 100) if stake != 0 else 0.0
                else:
                    runs = 0
                    win_pct = 0.0
                    stake = 0.0
                    pl = 0.0
                    roi_pct = 0.0

                filter_rows.append({
                    "Filter No": 0,
                    "Column ID": "None",
                    "Filter": "All Training Data",
                    "Rows": runs,
                    "Win %": win_pct,
                    "Stake": stake,
                    "P/L Increase": 0.0,
                    "New P/L": pl,
                    "New ROI%": roi_pct,
                })
            else:
                metrics = entry["metrics"].copy()

                filter_rows.append({
                    "Filter No": i,
                    "Column ID": metrics.get("Column ID", "None"),
                    "Filter": metrics.get("Filter", ""),
                    "Rows": 0 if metrics.get("Rows") is None else metrics.get("Rows"),
                    "Win %": 0.0 if metrics.get("Win %") is None else metrics.get("Win %"),
                    "Stake": 0.0 if metrics.get("Stake") is None else metrics.get("Stake"),
                    "P/L Increase": 0.0 if metrics.get("P/L Increase") is None else metrics.get("P/L Increase"),
                    "New P/L": 0.0 if metrics.get("New P/L") is None else metrics.get("New P/L"),
                    "New ROI%": 0.0 if metrics.get("New ROI%") is None else metrics.get("New ROI%"),
                })

        active_filters_df = pd.DataFrame(filter_rows)
        printable_rows = active_filters_df.to_dict(orient="records")

    table_height = get_active_filters_table_height(len(active_filters_df))

    st.dataframe(
        active_filters_df.style.format({
            "Filter No": "{:,.0f}",
            "Rows": "{:,.0f}",
            "Win %": "{:.1f}",
            "Stake": "{:,.0f}",
            "P/L Increase": "{:,.0f}",
            "New P/L": "{:,.0f}",
            "New ROI%": "{:.1f}",
        }),
        use_container_width=True,
        hide_index=True,
        height=table_height,
    )

    context = st.session_state.base_analysis_context
    latest_training_df = get_current_filtered_training_df(context)

    test_df_original = context.get("original_test_df", pd.DataFrame()) if context is not None else pd.DataFrame()
    filtered_test_df = apply_active_filters_sequence(
        test_df_original.copy(),
        st.session_state.active_filters,
    ) if not test_df_original.empty else pd.DataFrame()

    chart_left, chart_right = st.columns(2)

    with chart_left:
        if context is not None and not latest_training_df.empty:
            fig_train = make_active_filters_cumulative_date_chart(
                df=latest_training_df,
                event_date_col=context["event_date_col"],
                profit_col=context["target_col"],
                title="Training Data – Cumulative P/L by Date",
            )
            if fig_train is not None:
                st.plotly_chart(fig_train, use_container_width=True, key="active_filters_training_date_chart")
            else:
                st.info("No usable training date/profit data available.")
        else:
            st.info("No filtered training data available.")

    with chart_right:
        if context is not None and not filtered_test_df.empty:
            fig_test = make_active_filters_cumulative_date_chart(
                df=filtered_test_df,
                event_date_col=context["event_date_col"],
                profit_col=context["target_col"],
                title="Test Data – Cumulative P/L by Date",
            )
            if fig_test is not None:
                st.plotly_chart(fig_test, use_container_width=True, key="active_filters_test_date_chart")
            else:
                st.info("No usable test date/profit data available.")
        else:
            st.info("No filtered test data available.")

    file_name = "selected_file"
    if st.session_state.base_analysis_context is not None:
        file_name = st.session_state.base_analysis_context.get("file_name", "selected_file")

    if file_name.lower().endswith(".csv"):
        default_save_name = file_name
    else:
        default_save_name = f"{file_name}.csv"

    save_name_col, controls_spacer = st.columns([0.35, 0.65])

    with save_name_col:
        save_as_name = st.text_input(
            "Save As",
            value=default_save_name,
            key="active_filters_save_as_name",
        )

    printable_html = build_printable_filters_html(file_name, printable_rows)
    csv_bytes = build_filters_csv_bytes(printable_rows)

    available_steps = []
    if len(active_filters_df) > 1:
        available_steps = active_filters_df["Filter No"].tolist()[:-1]

    controls_left, controls_mid, controls_right = st.columns([1.2, 1.2, 2.0])

    with controls_left:
        st.download_button(
            label="Save Filters",
            data=csv_bytes,
            file_name=save_as_name,
            mime="text/csv",
            use_container_width=False,
            key="save_filters_csv_btn",
        )

    with controls_mid:
        st.download_button(
            label="Print Filters",
            data=printable_html,
            file_name=f"{file_name}_selected_filters.html",
            mime="text/html",
            use_container_width=False,
            key="print_filters_html_btn",
        )

    with controls_right:
        st.markdown("**Return to Filter No (and undo Filter since)**")

        if available_steps:
            selected_step = st.selectbox(
                "Return target",
                available_steps,
                index=len(available_steps) - 1,
                key="active_filters_return_step",
                label_visibility="collapsed",
            )

            if st.button("Go", key="active_filters_go", use_container_width=False):
                st.session_state.filter_history = st.session_state.filter_history[:selected_step + 1]

                rebuilt_active = []
                for hist_entry in st.session_state.filter_history[1:]:
                    rebuilt_active.append(hist_entry["metrics"])
                st.session_state.active_filters = rebuilt_active

                rerun_analysis_from_history()
                st.session_state.analysis_notice = f"Returned to filter {selected_step}"
                st.rerun()
        else:
            st.info("No earlier filter step is available to return to.")

def render_auto_build_tab(results, context) -> None:
    st.subheader("Auto Build")
    st.caption("Builds a candidate filter sequence automatically using the current training dataset and your stopping rules.")

    cfg_col0, cfg_col1, cfg_col2, cfg_col3, cfg_col4, cfg_col5 = st.columns(6)

    with cfg_col0:
        start_mode = st.selectbox(
            "Start From",
            AUTO_BUILD_START_OPTIONS,
            index=0,
            key="auto_build_start_mode",
        )

    with cfg_col1:
        max_filters = st.number_input(
            "Max Filters",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="auto_build_max_filters",
        )

    with cfg_col2:
        min_training_rows_pct = st.number_input(
            "Min Training Rows %",
            min_value=1,
            max_value=100,
            value=25,
            step=1,
            key="auto_build_min_training_rows_pct",
        )

    with cfg_col3:
        min_roi_improvement = st.number_input(
            "Min ROI Gain / Step",
            min_value=0.0,
            max_value=100.0,
            value=1.0,
            step=0.5,
            key="auto_build_min_roi_improvement",
        )

    with cfg_col4:
        max_test_roi_drop = st.number_input(
            "Max Test ROI Drop / Step",
            min_value=0.0,
            max_value=100.0,
            value=2.0,
            step=0.5,
            key="auto_build_max_test_roi_drop",
        )

    with cfg_col5:
        default_min_test_rows = max(10, int(len(context.get("original_test_df", pd.DataFrame())) * 0.1))
        min_test_rows = st.number_input(
            "Min Test Rows",
            min_value=0,
            max_value=max(0, len(context.get("original_test_df", pd.DataFrame()))),
            value=default_min_test_rows,
            step=1,
            key="auto_build_min_test_rows",
        )

    run_col, apply_col, clear_col, _ = st.columns([1.0, 1.2, 1.0, 2.0])

    with run_col:
        run_clicked = st.button("Run Auto Build", key="run_auto_build_btn", use_container_width=False)

    with apply_col:
        apply_clicked = st.button(
            "Apply Candidate Sequence",
            key="apply_auto_build_candidate_btn",
            use_container_width=False,
            disabled=len(st.session_state.get("auto_build_candidate_steps", [])) == 0,
        )

    with clear_col:
        clear_clicked = st.button("Clear Candidate", key="clear_auto_build_candidate_btn", use_container_width=False)

    if run_clicked:
        steps, preview_df, stop_reason, summary, rejection_df, progress_df = run_auto_build_candidate(
            context=context,
            start_mode=start_mode,
            max_filters=int(max_filters),
            min_training_rows_pct=int(min_training_rows_pct),
            min_roi_improvement=float(min_roi_improvement),
            max_test_roi_drop=float(max_test_roi_drop),
            min_test_rows=int(min_test_rows),
        )
        st.session_state.auto_build_candidate_steps = steps
        st.session_state.auto_build_candidate_preview_df = preview_df
        st.session_state.auto_build_stop_reason = stop_reason
        st.session_state.auto_build_summary = summary
        st.session_state.auto_build_rejections_df = rejection_df
        st.session_state.auto_build_progress_df = progress_df
        st.rerun()

    if apply_clicked:
        apply_auto_build_candidate_to_live_state()
        st.rerun()

    if clear_clicked:
        st.session_state.auto_build_candidate_steps = []
        st.session_state.auto_build_candidate_preview_df = pd.DataFrame()
        st.session_state.auto_build_stop_reason = ""
        st.session_state.auto_build_summary = {}
        st.session_state.auto_build_rejections_df = pd.DataFrame()
        st.session_state.auto_build_progress_df = pd.DataFrame()
        st.rerun()

    summary = st.session_state.get("auto_build_summary", {})
    preview_df = st.session_state.get("auto_build_candidate_preview_df", pd.DataFrame())
    stop_reason = st.session_state.get("auto_build_stop_reason", "")
    rejection_df = st.session_state.get("auto_build_rejections_df", pd.DataFrame())
    progress_df = st.session_state.get("auto_build_progress_df", pd.DataFrame())

    if summary:
        st.markdown("### Candidate Summary")
        sum_col1, sum_col2, sum_col3, sum_col4, sum_col5, sum_col6 = st.columns(6)

        with sum_col1:
            st.write(f"**Start Mode:** {summary.get('start_mode', '-')}")
        with sum_col2:
            st.write(f"**New Filters Added:** {summary.get('accepted_filters_new', 0)}")
        with sum_col3:
            st.write(f"**Total Filters in Candidate:** {summary.get('accepted_filters_total', 0)}")
        with sum_col4:
            st.write(f"**Final Training ROI%:** {summary.get('final_training_roi', 0.0):.1f}")
        with sum_col5:
            st.write(f"**Final Test ROI%:** {summary.get('final_test_roi', 0.0):.1f}")
        with sum_col6:
            st.write(f"**Final Test Rows:** {summary.get('final_test_rows', 0):,}")

    if stop_reason:
        st.info(stop_reason)

    if not progress_df.empty:
        fig = build_auto_build_progress_chart(progress_df)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key="auto_build_progress_chart")

    if not preview_df.empty:
        st.markdown("### Accepted Candidate Sequence")
        st.dataframe(
            preview_df,
            use_container_width=True,
            hide_index=True,
            height=min(320, 45 + (len(preview_df) * 35)),
        )
    else:
        st.info("No candidate sequence has been generated yet.")

    if not rejection_df.empty:
        st.markdown("### Rejected Filters Log")
        st.dataframe(
            rejection_df,
            use_container_width=True,
            hide_index=True,
            height=min(280, 45 + (len(rejection_df) * 35)),
        )
