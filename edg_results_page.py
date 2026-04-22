from typing import Any

import pandas as pd
import streamlit as st

from edg_analysis_engine import (
    build_stage_d_curve_data,
    calculate_grand_totals,
    format_value,
    prepare_sorted_dataframe,
)
from edg_filter_helpers import (
    CUSTOM_OPERATORS,
    apply_active_filters_sequence,
    apply_custom_filter_to_df,
    apply_filter_to_df,
    calculate_filter_metrics,
)
from edg_state_helpers import rerun_analysis_from_history
from edg_ui_helpers import (
    build_printable_filters_html,
    make_active_filters_cumulative_date_chart,
    make_pl_bar_chart,
    make_pl_line_chart,
    make_raw_cumulative_line_chart,
    style_possible_filters_dataframe,
    style_results_dataframe,
)

def build_filters_csv_bytes(filter_rows: list[dict]) -> bytes:
    from datetime import datetime
    from io import StringIO

    df = pd.DataFrame(filter_rows).copy()

    if not df.empty:
        if "Rows" in df:
            df["Rows"] = df["Rows"].round(0).astype(int)

        if "Win %" in df:
            df["Win %"] = df["Win %"].round(1)

        if "Stake" in df:
            df["Stake"] = df["Stake"].round(0).astype(int)

        if "P/L Increase" in df:
            df["P/L Increase"] = df["P/L Increase"].round(0).astype(int)

        if "New P/L" in df:
            df["New P/L"] = df["New P/L"].round(0).astype(int)

        if "New ROI%" in df:
            df["New ROI%"] = df["New ROI%"].round(1)

    context = st.session_state.get("base_analysis_context", {})

    file_name = context.get("file_name", "Unknown File")
    split_method = context.get("split_method", "Unknown")
    training_pct = context.get("training_pct", "-")
    test_pct = context.get("test_pct", "-")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    metadata = [
        ["File Name", file_name],
        ["Generated On", now],
        ["Split Method", split_method],
        ["Training %", training_pct],
        ["Test %", test_pct],
        ["Filters Applied", max(len(filter_rows) - 1, 0)],
        [],
    ]

    meta_df = pd.DataFrame(metadata)

    buffer = StringIO()
    meta_df.to_csv(buffer, index=False, header=False)
    df.to_csv(buffer, index=False)

    return buffer.getvalue().encode("utf-8")

def get_active_filters_table_height(n_rows: int) -> int:
    return max(90, min(320, 38 + (n_rows * 35)))

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


    col1, col2, spacer, col3, col4 = st.columns([1, 1, 0.35, 1, 1])

    with col1:
        st.write(f"**Longest Winning Run:** {results['grand_totals']['longest_winning_run']}")

    with col2:
        st.write(f"**Longest Losing Run:** {results['grand_totals']['longest_losing_run']}")

    with col3:
        st.write(f"**Max Drawdown:** {results['grand_totals'].get('max_drawdown', 0.0):,.2f}")

    with col4:
        st.write(f"**Max Drawdown %:** {results['grand_totals'].get('max_drawdown_pct', 0.0):.2f}%")

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
