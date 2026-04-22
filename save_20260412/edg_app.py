import pandas as pd
import streamlit as st

from edg_analysis_engine import (
    calculate_grand_totals,
    detect_column_type,
    format_value,
    prepare_sorted_dataframe,
    run_full_analysis,
    suggest_column,
)
from edg_filter_helpers import (
    CUSTOM_OPERATORS,
    apply_custom_filter_to_df,
    apply_filter_to_df,
    calculate_filter_metrics,
)
from edg_state_helpers import (
    get_file_hash,
    get_saved_settings,
    go_to_column_by_name,
    go_to_main_menu,
    go_to_next_column,
    initialize_session_state,
    rerun_analysis_from_history,
    save_current_settings,
    set_page,
)
from edg_ui_helpers import (
    build_printable_filters_html,
    inject_css,
    make_pl_bar_chart,
    make_pl_line_chart,
    style_possible_filters_dataframe,
    style_results_dataframe,
)

TYPE_OPTIONS = ["Continuous", "Discrete", "Categorical", "Date"]
SPLIT_METHOD_OPTIONS = ["Chronological", "Random"]

st.set_page_config(page_title="Datastart EdgeFinder", layout="wide")
initialize_session_state()
inject_css()


def split_training_test_data(
    df: pd.DataFrame,
    event_date_col: str,
    training_pct: int,
    split_method: str,
) -> tuple[pd.DataFrame, pd.DataFrame, str] | tuple[None, None, str]:
    df_sorted = prepare_sorted_dataframe(df, event_date_col)

    if df_sorted.empty:
        return None, None, "No valid rows remain after converting and sorting the Event Date column."

    if split_method == "Random":
        working_df = df_sorted.sample(frac=1, random_state=42).reset_index(drop=True)
        split_label = (
            f"Random split: {training_pct}% training / {100 - training_pct}% test "
            f"(seed 42, after date cleaning)"
        )
    else:
        working_df = df_sorted.copy()
        split_label = (
            f"Chronological split: first {training_pct}% of rows for training, "
            f"final {100 - training_pct}% for test"
        )

    split_index = int(len(working_df) * training_pct / 100)

    training_df = working_df.iloc[:split_index].copy()
    test_df = working_df.iloc[split_index:].copy()

    if training_df.empty:
        return None, None, "The chosen split leaves no rows in the training dataset."

    return training_df, test_df, split_label


def render_header() -> None:
    st.markdown(
    """
    <div style="
        margin-top: -0.55rem;
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

    if st.session_state.get("analysis_ready", False):
        desc = "Review possible filters ranked by ROI improvement."
    else:
        desc = "Load a CSV, confirm column types, and choose key columns."

    st.caption(desc)

    if context is not None and st.session_state.filter_history:
        current_df = st.session_state.filter_history[-1]["df"]
        rows = len(current_df)
        step = len(st.session_state.filter_history) - 1
        filters = len(st.session_state.active_filters)

        st.caption(
            f"File: {context.get('file_name','-')} | "
            f"Training rows in play: {rows:,} | Step: {step} | Filters applied: {filters}"
        )


def render_sidebar() -> str:
    st.sidebar.radio(
        "Menu",
        ["Configuration", "Analysis", "Active Filters"],
        key="page",
    )
    return st.session_state.page


def render_configuration_page() -> None:
    uploader_col, selected_file_col = st.columns([1, 1])

    with uploader_col:
        uploaded_file = st.file_uploader(
            "Upload your CSV file",
            type="csv",
            label_visibility="collapsed",
            key="config_file_uploader",
        )

    with selected_file_col:
        st.markdown('<div class="selected-file-box">', unsafe_allow_html=True)
        if uploaded_file is not None:
            st.markdown(
                f'<div class="selected-file-pill">Selected file: {uploaded_file.name}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="selected-file-pill">Selected file: None</div>',
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    if uploaded_file is None:
        return

    try:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file)
    except pd.errors.EmptyDataError:
        st.error("The uploaded CSV could not be read. Please re-select the file.")
        return
    except Exception as e:
        st.error(f"Unable to read CSV file: {e}")
        return

    file_key = get_file_hash(uploaded_file)
    saved = get_saved_settings(file_key)

    st.subheader("Preview")
    st.dataframe(df.head(5), use_container_width=True, height=205)

    detected_types = [detect_column_type(df[col], col) for col in df.columns]

    selected_type_defaults = [
        saved.get("selected_types", {}).get(col, detected_types[i])
        for i, col in enumerate(df.columns)
    ]
    analyze_defaults = [
        saved.get("analyze_flags", {}).get(col, True)
        for col in df.columns
    ]

    config_df = pd.DataFrame({
        "Column": df.columns,
        "Detected Type": detected_types,
        "Selected Type": selected_type_defaults,
        "Analyze": analyze_defaults,
    })

    left_col, right_col = st.columns([2.5, 1.1])

    with left_col:
        st.markdown(
            '<div style="font-size: 1.35rem; font-weight: 600; margin-bottom: 0.15rem;">Configuration</div>',
            unsafe_allow_html=True,
        )

    with right_col:
        st.markdown(
            '<div style="font-size: 1.35rem; font-weight: 600; margin-bottom: 0.02rem;">Data Split</div>',
            unsafe_allow_html=True,
        )

    with left_col:
        st.write("Use the dropdown in 'Selected Type' to correct any column classifications.")

        edited_config = st.data_editor(
            config_df,
            column_config={
                "Column": st.column_config.TextColumn("Column", disabled=True),
                "Detected Type": st.column_config.TextColumn("Detected Type", disabled=True),
                "Selected Type": st.column_config.SelectboxColumn(
                    "Selected Type",
                    options=TYPE_OPTIONS,
                    required=True,
                ),
                "Analyze": st.column_config.CheckboxColumn(
                    "Analyze",
                    help="Turn off analysis for columns you do not want included in later per-column analysis.",
                ),
            },
            disabled=["Column", "Detected Type"],
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            height=405,
            key="config_data_editor",
        )

    column_types = dict(zip(edited_config["Column"], edited_config["Selected Type"]))
    analyze_flags = dict(zip(edited_config["Column"], edited_config["Analyze"]))

    numeric_candidate_cols = [
        col for col in df.columns
        if column_types.get(col) in ["Continuous", "Discrete"]
    ]

    date_candidate_cols = [
        col for col in df.columns
        if column_types.get(col) == "Date"
    ]

    if not date_candidate_cols:
        date_candidate_cols = list(df.columns)

    if not numeric_candidate_cols:
        st.warning(
            "No columns are currently marked as Continuous or Discrete. "
            "Please update the Configuration Summary so numeric columns can be selected."
        )
        return

    date_keywords = {
        "event date": 12,
        "date": 10,
        "event_time": 8,
        "event time": 8,
        "timestamp": 7,
        "time": 5,
        "day": 4,
    }

    stake_keywords = {
        "stake": 10,
        "risk": 10,
        "loss": 6,
        "sl": 5,
        "stop": 4,
        "amount": 2,
        "size": 2,
    }

    target_keywords = {
        "target": 10,
        "profit": 10,
        "pl": 8,
        "p/l": 8,
        "tp": 5,
        "reward": 6,
        "gain": 4,
        "return": 3,
    }

    suggested_event_date = saved.get("event_date_col") or suggest_column(date_candidate_cols, date_keywords)
    suggested_stake = saved.get("stake_col") or suggest_column(numeric_candidate_cols, stake_keywords)
    suggested_target = saved.get("target_col") or suggest_column(numeric_candidate_cols, target_keywords)
    suggested_split_method = saved.get("split_method", "Chronological")

    if suggested_event_date not in date_candidate_cols:
        suggested_event_date = date_candidate_cols[0]

    if suggested_stake not in numeric_candidate_cols:
        suggested_stake = numeric_candidate_cols[0]

    if suggested_target not in numeric_candidate_cols:
        suggested_target = numeric_candidate_cols[0]

    if suggested_split_method not in SPLIT_METHOD_OPTIONS:
        suggested_split_method = "Chronological"

    with right_col:
        st.markdown(
            """
            <div style="margin-top: -4.3rem;">
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="training-box">', unsafe_allow_html=True)
        
        saved_training_pct = int(saved.get("training_pct", 70))
        training_pct = st.number_input(
            "Training Data %",
            min_value=0,
            max_value=100,
            value=saved_training_pct,
            step=1,
            key="training_pct_input",
        )

        test_pct = 100 - training_pct
        st.write(f"**Test Data %:** {test_pct}")

        split_method = st.selectbox(
            "Split Method",
            SPLIT_METHOD_OPTIONS,
            index=SPLIT_METHOD_OPTIONS.index(suggested_split_method),
            key="split_method_select",
        )

        if training_pct in [0, 100]:
            st.warning("A one-sided split is allowed, but it may limit what can be validated.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.write("### Key Columns")

        event_date_index = date_candidate_cols.index(suggested_event_date)
        event_date_col = st.selectbox(
            "Select Event Date column",
            date_candidate_cols,
            index=event_date_index,
            key="event_date_select",
        )

        stake_index = numeric_candidate_cols.index(suggested_stake)
        stake_col = st.selectbox(
            "Select Stake / Risk column",
            numeric_candidate_cols,
            index=stake_index,
            key="stake_select",
        )

        target_index = numeric_candidate_cols.index(suggested_target)
        target_col = st.selectbox(
            "Select Target / Profit column",
            numeric_candidate_cols,
            index=target_index,
            key="target_select",
        )

        st.markdown("</div>", unsafe_allow_html=True)

    run_col1, run_col2 = st.columns([1, 3])

    with run_col1:
        run_clicked = st.button("Run Analysis", key="run_analysis_button")

    with run_col2:
        if st.session_state.get("show_config_finished_message", False):
            st.success('Please click "Analysis" in left-hand Menu to see possible filters')

    if run_clicked:
        training_df, test_df, split_label = split_training_test_data(
            df=df,
            event_date_col=event_date_col,
            training_pct=int(training_pct),
            split_method=split_method,
        )

        if training_df is None:
            st.error(split_label)
            st.session_state.show_config_finished_message = False
            return

        save_current_settings(
            file_key=file_key,
            edited_config=edited_config,
            training_pct=int(training_pct),
            split_method=split_method,
            event_date_col=event_date_col,
            stake_col=stake_col,
            target_col=target_col,
        )

        st.session_state.active_filters = []
        st.session_state.filter_history = [{
            "df": training_df.copy(),
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
        st.session_state.analysis_view = "main"
        st.session_state.current_column_index = 0
        st.session_state.chart_mode = None
        st.session_state.analysis_notice = ""

        st.session_state.base_analysis_context = {
            "original_df": df.copy(),
            "original_training_df": training_df.copy(),
            "original_test_df": test_df.copy(),
            "event_date_col": event_date_col,
            "stake_col": stake_col,
            "target_col": target_col,
            "column_types": column_types,
            "analyze_flags": analyze_flags,
            "file_name": uploaded_file.name,
            "training_pct": int(training_pct),
            "test_pct": 100 - int(training_pct),
            "split_method": split_method,
            "split_label": split_label,
        }

        results = run_full_analysis(
            df_input=training_df.copy(),
            event_date_col=event_date_col,
            stake_col=stake_col,
            target_col=target_col,
            column_types=column_types,
            analyze_flags=analyze_flags,
            calculate_filter_metrics_fn=calculate_filter_metrics,
            apply_filter_to_df_fn=apply_filter_to_df,
        )

        if "error" in results:
            st.session_state.analysis_ready = False
            st.session_state.analysis_results = results
            st.session_state.show_config_finished_message = False
        else:
            rerun_analysis_from_history()
            st.session_state.show_config_finished_message = True
            st.success("Analysis complete.")


def render_test_validation_panel(results) -> None:
    test_validation = results.get("test_validation")

    if not test_validation or not test_validation.get("available", False):
        if test_validation and test_validation.get("message"):
            st.info(test_validation["message"])
        return

    st.subheader("Out-of-Sample Test Data")
    st.caption(test_validation.get("split_label", ""))

    val_left, val_right = st.columns([1.5, 1])

    with val_left:
        st.dataframe(
            style_results_dataframe(test_validation["summary_df"]),
            use_container_width=True,
            hide_index=True,
            height=110,
        )

    with val_right:
        st.write(f"**Status:** {test_validation['status']}")
        st.write(f"**ROI change vs training:** {test_validation['roi_delta']:.1f} pts")
        st.write(f"**Win% change vs training:** {test_validation['win_pct_delta']:.1f} pts")
        st.write(f"**P/L change vs training:** {test_validation['pl_delta']:,.0f}")
        st.write(f"**Original test rows:** {test_validation['test_rows_original']:,}")
        st.write(f"**Test rows after filters:** {test_validation['test_rows_after_filters']:,}")


def render_analysis_main(results, context) -> None:
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

        st.subheader("Actions")
        col1, col2, col3, col4, col5 = st.columns([1.2, 1.2, 1.1, 1.2, 0.8])

        with col1:
            selected_filter_no = st.selectbox(
                "Filter No",
                options=filters_df["Filter No"].tolist(),
                index=0,
                key="apply_filter_select",
            )
            if st.button("Apply", use_container_width=True):
                selected_row = filters_df.loc[filters_df["Filter No"] == selected_filter_no].iloc[0]

                current_df = st.session_state.filter_history[-1]["df"].copy()
                new_df = apply_filter_to_df(
                    current_df,
                    selected_row["Column ID"],
                    selected_row["Filter"],
                )

                metrics = {
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

                st.session_state.filter_history.append({
                    "df": new_df.copy(),
                    "description": f"{selected_row['Column ID']} — {selected_row['Filter']}",
                    "column": selected_row["Column ID"],
                    "filter_text": selected_row["Filter"],
                    "metrics": metrics,
                })

                st.session_state.active_filters.append(metrics)

                rerun_analysis_from_history()
                go_to_main_menu()
                st.session_state.analysis_notice = (
                    f"Filter applied: {selected_row['Column ID']} — {selected_row['Filter']}"
                )
                st.rerun()

        with col2:
            selected_drill = st.selectbox(
                "Column",
                options=results["columns_to_analyze"],
                index=0,
                key="drill_down_select",
            )
            if st.button("Drill Down", use_container_width=True):
                go_to_column_by_name(selected_drill)
                st.rerun()

        with col3:
            if st.button("Scroll Columns", use_container_width=True):
                if results["columns_to_analyze"]:
                    st.session_state.current_column_index = 0
                    st.session_state.analysis_view = "detail"
                    st.rerun()

        with col4:
            if st.button("Active Filters", use_container_width=True):
                set_page("Active Filters")
                st.rerun()

        with col5:
            if st.button("Undo", use_container_width=True):
                if len(st.session_state.filter_history) > 1:
                    last_entry = st.session_state.filter_history.pop()
                    if st.session_state.active_filters:
                        st.session_state.active_filters.pop()

                    rerun_analysis_from_history()
                    go_to_main_menu()
                    st.session_state.analysis_notice = f"Removed filter: {last_entry['description']}"
                    st.rerun()

    st.subheader("Create Your Own Filter")
    custom_col1, custom_col2, custom_col3, custom_col4, custom_col5 = st.columns([1.3, 1, 0.9, 0.9, 0.8])

    with custom_col1:
        custom_column = st.selectbox(
            "Column Name",
            options=context["original_df"].columns.tolist(),
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
    with custom_col4:
        custom_value2 = st.text_input("Value b", key="custom_filter_value2")
    with custom_col5:
        st.write("")
        st.write("")
        apply_custom = st.button("Apply Custom", use_container_width=True)

    if apply_custom:
        if custom_operator == ">= and <=":
            try:
                a = float(custom_value1)
                b = float(custom_value2)
                if b < a:
                    st.error("For an inclusive range, value b cannot be less than value a.")
                    st.stop()
            except Exception:
                st.error("Please enter valid numeric values for a and b.")
                st.stop()

            filter_text = f">= {custom_value1} and <= {custom_value2}"
        else:
            filter_text = f"{custom_operator} {custom_value1}"

        current_df = st.session_state.filter_history[-1]["df"].copy()
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

            rerun_analysis_from_history()
            go_to_main_menu()
            st.session_state.analysis_notice = f"Custom filter applied: {custom_column} — {filter_text}"
            st.rerun()


def render_analysis_detail(results) -> None:
    columns_to_analyze = results["columns_to_analyze"]

    if not columns_to_analyze:
        st.info("No columns available.")
        return

    current_index = st.session_state.current_column_index
    current_index = max(0, min(current_index, len(columns_to_analyze) - 1))
    st.session_state.current_column_index = current_index

    current_col = columns_to_analyze[current_index]
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

    table_col, chart_col = st.columns([1.5, 1])

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

    nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)

    with nav_col1:
        if st.button("Back", use_container_width=True):
            go_to_main_menu()
            st.rerun()

    with nav_col2:
        next_disabled = current_index >= len(columns_to_analyze) - 1
        if st.button("Next", disabled=next_disabled, use_container_width=True):
            go_to_next_column()
            st.rerun()

    with nav_col3:
        if st.button("Bar Chart", use_container_width=True):
            st.session_state.chart_mode = "bar"
            st.rerun()

    with nav_col4:
        if st.button("Line Chart", use_container_width=True):
            st.session_state.chart_mode = "line"
            st.rerun()

    with nav_col5:
        if st.button("Main Menu", use_container_width=True):
            go_to_main_menu()
            st.rerun()

    with chart_col:
        if st.session_state.chart_mode == "line":
            fig = make_pl_line_chart(results["stage_c_results"][current_col], line_title)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)
        else:
            fig = make_pl_bar_chart(results["stage_c_results"][current_col], bar_title)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)


def render_analysis_page() -> None:
    if not st.session_state.analysis_ready:
        if st.session_state.analysis_results and "error" in st.session_state.analysis_results:
            st.error(st.session_state.analysis_results["error"])
        else:
            st.info("Run the analysis from Configuration first.")
        return

    results = st.session_state.analysis_results
    context = st.session_state.base_analysis_context

    # if "timings" in results:
    #     with st.expander("Analysis timing breakdown"):
    #         timing_df = pd.DataFrame(
    #             [{"Stage": k, "Seconds": v} for k, v in results["timings"].items()]
    #         )
    #         st.dataframe(
    #             timing_df.style.format({"Seconds": "{:.3f}"}),
    #             use_container_width=True,
    #             hide_index=True,
    #         )

    if st.session_state.analysis_notice:
        st.success(st.session_state.analysis_notice)
        st.session_state.analysis_notice = ""

    if st.session_state.analysis_view == "main":
        render_analysis_main(results, context)
    else:
        render_analysis_detail(results)


def render_active_filters_page() -> None:
    st.subheader("Active Filters")

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
                        entry["df"],
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
        height=300,
    )

    st.subheader("Menu")

    menu_col1, menu_col2, menu_col3, menu_col4 = st.columns([1, 1, 1.2, 0.8])

    with menu_col1:
        if st.button("Return to Analysis", use_container_width=True):
            set_page("Analysis")
            go_to_main_menu()
            st.rerun()

    with menu_col2:
        file_name = "selected_file"
        if st.session_state.base_analysis_context is not None:
            file_name = st.session_state.base_analysis_context.get("file_name", "selected_file")

        printable_html = build_printable_filters_html(file_name, printable_rows)
        st.download_button(
            label="Print Filters",
            data=printable_html,
            file_name=f"{file_name}_selected_filters.html",
            mime="text/html",
            use_container_width=True,
        )

    with menu_col3:
        available_steps = active_filters_df["Filter No"].tolist()
        selected_step = st.selectbox(
            "Return to Step",
            available_steps,
            index=len(available_steps) - 1 if available_steps else 0,
            key="active_filters_return_step",
        )

    with menu_col4:
        st.write("")
        st.write("")
        if st.button("Go", use_container_width=True):
            st.session_state.filter_history = st.session_state.filter_history[:selected_step + 1]

            rebuilt_active = []
            for hist_entry in st.session_state.filter_history[1:]:
                rebuilt_active.append(hist_entry["metrics"])
            st.session_state.active_filters = rebuilt_active

            rerun_analysis_from_history()
            set_page("Analysis")
            go_to_main_menu()
            st.session_state.analysis_notice = f"Returned to step {selected_step}"
            st.rerun()


def main() -> None:
    render_header()
    page = render_sidebar()

    if page == "Configuration":
        render_configuration_page()
    elif page == "Analysis":
        render_analysis_page()
    elif page == "Active Filters":
        render_active_filters_page()


if __name__ == "__main__":
    main()