import hashlib
import json
import os
from typing import Any

import pandas as pd
import streamlit as st

from edg_analysis_engine import calculate_grand_totals, run_full_analysis
from edg_filter_helpers import (
    apply_active_filters_sequence,
    apply_filter_to_df,
    calculate_filter_metrics,
)

SETTINGS_FILE = "saved_csv_settings.json"

DEFAULT_SESSION_VALUES = {
    "app_mode": "setup",                 # setup / analysis
    "analysis_ready": False,
    "analysis_results": None,
    "analysis_view": "main",
    "current_column_index": 0,
    "active_filters": [],
    "filter_history": [],
    "base_analysis_context": None,
    "analysis_notice": "",
    "saved_csv_settings": {},
    "chart_mode": None,
    "show_config_finished_message": False,
}


def load_saved_settings_from_disk() -> dict[str, Any]:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_saved_settings_to_disk(settings: dict[str, Any]) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


def initialize_session_state() -> None:
    if "saved_csv_settings" not in st.session_state:
        st.session_state.saved_csv_settings = load_saved_settings_from_disk()

    for key, value in DEFAULT_SESSION_VALUES.items():
        if key not in st.session_state:
            if key == "saved_csv_settings":
                continue
            st.session_state[key] = value


def reset_analysis_state() -> None:
    saved_settings = st.session_state.get("saved_csv_settings", load_saved_settings_from_disk())

    for key in list(st.session_state.keys()):
        del st.session_state[key]

    st.session_state.saved_csv_settings = saved_settings

    for key, value in DEFAULT_SESSION_VALUES.items():
        if key not in st.session_state:
            if key == "saved_csv_settings":
                continue
            st.session_state[key] = value

    st.session_state.app_mode = "setup"


def get_file_hash(uploaded_file) -> str:
    return hashlib.md5(uploaded_file.getvalue()).hexdigest()


def get_saved_settings(file_key: str) -> dict[str, Any]:
    return st.session_state.saved_csv_settings.get(file_key, {})


def save_current_settings(
    file_key: str,
    edited_config,
    training_pct: int,
    split_method: str,
    event_date_col: str,
    stake_col: str,
    target_col: str,
    starting_bank: float,
) -> None:
    st.session_state.saved_csv_settings[file_key] = {
        "selected_types": dict(zip(edited_config["Column"], edited_config["Selected Type"])),
        "analyze_flags": dict(zip(edited_config["Column"], edited_config["Analyze"])),
        "training_pct": int(training_pct),
        "split_method": split_method,
        "event_date_col": event_date_col,
        "stake_col": stake_col,
        "target_col": target_col,
        "starting_bank": float(starting_bank),
    }
    save_saved_settings_to_disk(st.session_state.saved_csv_settings)


def _build_test_validation(results: dict[str, Any], context: dict[str, Any]) -> None:
    test_df_original = context.get("original_test_df")

    if test_df_original is None:
        results["test_validation"] = {
            "available": False,
            "message": "No test dataset is available.",
        }
        return

    filtered_test_df = apply_active_filters_sequence(
        test_df_original.copy(),
        st.session_state.active_filters,
    )

    stake_col = context["stake_col"]
    target_col = context["target_col"]

    training_totals = results["grand_totals"]
    test_totals = calculate_grand_totals(filtered_test_df, stake_col, target_col)

    train_runs = training_totals["runs"]
    train_stake = training_totals["stake"]
    train_pl = training_totals["pl"]
    train_win_pct = (training_totals["winners"] / train_runs * 100) if train_runs > 0 else 0.0
    train_roi = (train_pl / train_stake * 100) if train_stake != 0 else 0.0

    test_runs = test_totals["runs"]
    test_stake = test_totals["stake"]
    test_pl = test_totals["pl"]
    test_win_pct = (test_totals["winners"] / test_runs * 100) if test_runs > 0 else 0.0
    test_roi = (test_pl / test_stake * 100) if test_stake != 0 else 0.0

    summary_df = pd.DataFrame([
        {
            "Dataset": "Training",
            "Runs": train_runs,
            "Win%": train_win_pct,
            "Stake": train_stake,
            "P/L": train_pl,
            "ROI%": train_roi,
        },
        {
            "Dataset": "Test",
            "Runs": test_runs,
            "Win%": test_win_pct,
            "Stake": test_stake,
            "P/L": test_pl,
            "ROI%": test_roi,
        },
    ])

    roi_delta = test_roi - train_roi
    win_pct_delta = test_win_pct - train_win_pct
    pl_delta = test_pl - train_pl

    if test_runs == 0:
        status = "No test rows"
    elif roi_delta >= -1:
        status = "Strong"
    elif roi_delta >= -3:
        status = "Acceptable"
    else:
        status = "Weak"

    results["test_validation"] = {
        "available": True,
        "summary_df": summary_df,
        "status": status,
        "split_label": context.get("split_label", ""),
        "training_rows_original": len(context.get("original_training_df", [])),
        "test_rows_original": len(test_df_original),
        "test_rows_after_filters": len(filtered_test_df),
        "roi_delta": roi_delta,
        "win_pct_delta": win_pct_delta,
        "pl_delta": pl_delta,
    }


def rerun_analysis_from_history() -> None:
    context = st.session_state.base_analysis_context
    if context is None:
        return

    working_df = apply_active_filters_sequence(
        context["original_training_df"].copy(),
        st.session_state.active_filters,
    )

    results = run_full_analysis(
        df_input=working_df,
        event_date_col=context["event_date_col"],
        stake_col=context["stake_col"],
        target_col=context["target_col"],
        column_types=context["column_types"],
        analyze_flags=context["analyze_flags"],
        calculate_filter_metrics_fn=calculate_filter_metrics,
        apply_filter_to_df_fn=apply_filter_to_df,
        starting_bank=float(context.get("starting_bank", 0.0) or 0.0),
    )

    if "error" in results:
        st.session_state.analysis_ready = False
        st.session_state.analysis_results = results
    else:
        _build_test_validation(results, context)
        st.session_state.analysis_ready = True
        st.session_state.analysis_results = results
        st.session_state.app_mode = "analysis"