import pandas as pd
import streamlit as st

from edg_analysis_engine import (
    detect_column_type,
    prepare_sorted_dataframe,
    run_full_analysis,
    suggest_column,
)
from edg_filter_helpers import (
    apply_filter_to_df,
    calculate_filter_metrics,
)
from edg_state_helpers import (
    _build_test_validation,
    get_file_hash,
    get_saved_settings,
    save_current_settings,
)

TYPE_OPTIONS = ["Numeric Continuous", "Numeric Discrete", "Categorical", "Date"]
SPLIT_METHOD_OPTIONS = ["Chronological", "Random"]

LEGACY_TYPE_MAP = {
    "Continuous": "Numeric Continuous",
    "Discrete": "Numeric Discrete",
}


def normalize_type_label(value: str) -> str:
    return LEGACY_TYPE_MAP.get(value, value)


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
        normalize_type_label(saved.get("selected_types", {}).get(col, detected_types[i]))
        for i, col in enumerate(df.columns)
    ]
    analyze_defaults = [
        saved.get("analyze_flags", {}).get(col, True)
        for col in df.columns
    ]

    selected_type_defaults = [
        value if value in TYPE_OPTIONS else detected_types[i]
        for i, value in enumerate(selected_type_defaults)
    ]

    config_df = pd.DataFrame({
        "Column": df.columns,
        "Detected Type": detected_types,
        "Selected Type": selected_type_defaults,
        "Analyze": analyze_defaults,
    })

    hdr_left, hdr_right = st.columns([2.5, 1.1])

    with hdr_left:
        st.markdown(
            '<div style="font-size: 1.35rem; font-weight: 600; margin-bottom: 0.15rem;">Configuration</div>',
            unsafe_allow_html=True,
        )

    with hdr_right:
        st.markdown(
            '<div style="font-size: 1.35rem; font-weight: 600; margin-bottom: 0.02rem;">Data Split</div>',
            unsafe_allow_html=True,
        )

    left_col, right_col = st.columns([2.5, 1.1])

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
        if column_types.get(col) in ["Numeric Continuous", "Numeric Discrete"]
    ]

    date_candidate_cols = [
        col for col in df.columns
        if column_types.get(col) == "Date"
    ]

    if not date_candidate_cols:
        date_candidate_cols = list(df.columns)

    if not numeric_candidate_cols:
        st.warning(
            "No columns are currently marked as Numeric Continuous or Numeric Discrete. "
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
        st.markdown('<div class="training-box">', unsafe_allow_html=True)

        saved_training_pct = int(saved.get("training_pct", 70))
        if saved_training_pct % 5 != 0:
            saved_training_pct = int(round(saved_training_pct / 5) * 5)
        saved_training_pct = max(50, min(95, saved_training_pct))

        training_label_col, training_input_col = st.columns([1.15, 1.0])
        with training_label_col:
            st.markdown("**Training Data %**")
        with training_input_col:
            training_pct = st.number_input(
                "Training Data %",
                min_value=50,
                max_value=95,
                value=saved_training_pct,
                step=5,
                key="training_pct_input",
                label_visibility="collapsed",
            )

        test_pct = 100 - int(training_pct)
        st.write(f"**Test Data %:** {test_pct}")

        split_label_col, split_input_col = st.columns([1.15, 1.0])
        with split_label_col:
            st.markdown("**Split Method**")
        with split_input_col:
            split_method = st.selectbox(
                "Split Method",
                SPLIT_METHOD_OPTIONS,
                index=SPLIT_METHOD_OPTIONS.index(suggested_split_method),
                key="split_method_select",
                label_visibility="collapsed",
            )

        st.markdown("</div>", unsafe_allow_html=True)

        st.write("### Key Columns")

        event_date_index = date_candidate_cols.index(suggested_event_date)
        event_label_col, event_input_col = st.columns([1.15, 1.0])
        with event_label_col:
            st.markdown("**Event Date**")
        with event_input_col:
            event_date_col = st.selectbox(
                "Select Event Date column",
                date_candidate_cols,
                index=event_date_index,
                key="event_date_select",
                label_visibility="collapsed",
            )

        stake_index = numeric_candidate_cols.index(suggested_stake)
        stake_label_col, stake_input_col = st.columns([1.15, 1.0])
        with stake_label_col:
            st.markdown("**Stake / Risk**")
        with stake_input_col:
            stake_col = st.selectbox(
                "Select Stake / Risk column",
                numeric_candidate_cols,
                index=stake_index,
                key="stake_select",
                label_visibility="collapsed",
            )

        target_index = numeric_candidate_cols.index(suggested_target)
        target_label_col, target_input_col = st.columns([1.15, 1.0])
        with target_label_col:
            st.markdown("**Target / Profit**")
        with target_input_col:
            target_col = st.selectbox(
                "Select Target / Profit column",
                numeric_candidate_cols,
                index=target_index,
                key="target_select",
                label_visibility="collapsed",
            )

        st.markdown("---")

        saved_starting_bank = saved.get("starting_bank", 0)
        try:
            saved_starting_bank_text = str(int(round(float(saved_starting_bank))))
        except Exception:
            saved_starting_bank_text = "0"

        bank_label_col, bank_input_col = st.columns([1.15, 1.0])
        with bank_label_col:
            st.markdown("**Starting Bank**")
        with bank_input_col:
            starting_bank_text = st.text_input(
                "Starting Bank",
                value=saved_starting_bank_text,
                key="starting_bank_input",
                label_visibility="collapsed",
                help="Used for drawdown percentage and equity-based drawdown calculations.",
            )

        starting_bank_text = starting_bank_text.strip()
        status_level = None
        status_message = ""
        run_analysis_disabled = False
        training_df = None
        test_df = None
        split_label = ""

        if starting_bank_text == "":
            starting_bank = 0
        else:
            try:
                starting_bank = int(starting_bank_text.replace(",", ""))
                if starting_bank < 0:
                    status_level = "error"
                    status_message = "Starting Bank must be zero or a positive whole number."
                    run_analysis_disabled = True
                    starting_bank = 0
            except ValueError:
                status_level = "error"
                status_message = "Starting Bank must be a whole number."
                run_analysis_disabled = True
                starting_bank = 0

        if not run_analysis_disabled:
            training_df, test_df, split_label = split_training_test_data(
                df=df,
                event_date_col=event_date_col,
                training_pct=int(training_pct),
                split_method=split_method,
            )

            if training_df is None:
                status_level = "error"
                status_message = split_label
                run_analysis_disabled = True
            else:
                train_rows = len(training_df)
                test_rows = len(test_df)
                total_rows = len(df)

                if total_rows < 30:
                    status_level = "error"
                    status_message = "Dataset is too small to analyse reliably. At least 30 rows are required."
                    run_analysis_disabled = True
                elif train_rows < 20:
                    status_level = "error"
                    status_message = f"Training set is too small ({train_rows} rows). Increase Training Data % or use a larger dataset."
                    run_analysis_disabled = True
                elif test_rows < 10:
                    status_level = "error"
                    status_message = f"Test set is too small ({test_rows} rows). Reduce Training Data % or use a larger dataset."
                    run_analysis_disabled = True
                elif train_rows < 50:
                    status_level = "warning"
                    status_message = f"Training set has only {train_rows} rows. Results may be unreliable."
                elif test_rows < 20:
                    status_level = "warning"
                    status_message = f"Test set has only {test_rows} rows. Validation may be unreliable."

    st.markdown("---")

    button_col, message_col = st.columns([1, 2])
    with button_col:
        run_analysis = st.button(
            "Run Analysis",
            key="run_analysis_button",
            disabled=run_analysis_disabled,
        )

    with message_col:
        if status_level == "error":
            st.error(status_message)
        elif status_level == "warning":
            st.warning(status_message)

    if run_analysis:
        save_current_settings(
            file_key=file_key,
            edited_config=edited_config,
            training_pct=int(training_pct),
            split_method=split_method,
            event_date_col=event_date_col,
            stake_col=stake_col,
            target_col=target_col,
            starting_bank=float(starting_bank),
        )

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
            "starting_bank": float(starting_bank),
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
            starting_bank=float(starting_bank),
        )

        if "error" in results:
            st.session_state.analysis_ready = False
            st.session_state.analysis_results = results
        else:
            _build_test_validation(results, st.session_state.base_analysis_context)
            st.session_state.analysis_results = results
            st.session_state.analysis_ready = True
            st.session_state.app_mode = "analysis"
            st.rerun()


