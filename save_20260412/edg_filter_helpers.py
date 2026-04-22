from typing import Any

import pandas as pd

from edg_analysis_engine import calculate_grand_totals


CUSTOM_OPERATORS = ["=", "!=", ">", ">=", "<", "<=", ">= and <="]


def apply_filter_to_df(df: pd.DataFrame, col: str, filter_text: str) -> pd.DataFrame:
    series = pd.to_numeric(df[col], errors="coerce")
    clean_filter = filter_text.strip()

    if " or " in clean_filter:
        left_part, right_part = clean_filter.split(" or ", 1)
        left_df = apply_filter_to_df(df, col, left_part)
        right_df = apply_filter_to_df(df, col, right_part)
        combined = pd.concat([left_df, right_df]).drop_duplicates()
        return combined

    if "> " in clean_filter and "<=" in clean_filter:
        low_text, high_text = clean_filter.split("and")
        low_val = float(low_text.replace(">", "").strip())
        high_val = float(high_text.replace("<=", "").strip())
        return df[(series > low_val) & (series <= high_val)]

    if clean_filter.startswith(">"):
        val = float(clean_filter.replace(">", "").strip())
        return df[series > val]

    if clean_filter.startswith("<="):
        val = float(clean_filter.replace("<=", "").strip())
        return df[series <= val]

    return df


def apply_custom_filter_to_df(
    df: pd.DataFrame,
    col: str,
    operator: str,
    value1: str,
    value2: str = "",
) -> pd.DataFrame:
    series = df[col]
    numeric_series = pd.to_numeric(series, errors="coerce")
    numeric_ratio = numeric_series.notna().mean()

    if operator == ">= and <=":
        try:
            a = float(value1)
            b = float(value2)
        except Exception:
            return df.iloc[0:0].copy()

        if b < a:
            return df.iloc[0:0].copy()

        return df[(numeric_series >= a) & (numeric_series <= b)]

    if numeric_ratio > 0.8:
        try:
            v = float(value1)
            if operator == "=":
                return df[numeric_series == v]
            if operator == "!=":
                return df[numeric_series != v]
            if operator == ">":
                return df[numeric_series > v]
            if operator == ">=":
                return df[numeric_series >= v]
            if operator == "<":
                return df[numeric_series < v]
            if operator == "<=":
                return df[numeric_series <= v]
        except Exception:
            return df.iloc[0:0].copy()

    s = series.astype(str)
    v = str(value1)
    if operator == "=":
        return df[s == v]
    if operator == "!=":
        return df[s != v]

    return df.iloc[0:0].copy()


def calculate_filter_metrics(df_filtered: pd.DataFrame, stake_col: str, profit_col: str, base_pl: float):
    totals = calculate_grand_totals(df_filtered, stake_col, profit_col)
    runs = totals["runs"]
    winners = totals["winners"]
    stake = totals["stake"]
    new_pl = totals["pl"]
    win_pct = (winners / runs * 100) if runs > 0 else 0.0
    new_roi = (new_pl / stake * 100) if stake != 0 else 0.0
    pl_increase = new_pl - base_pl

    return {
        "Rows": runs,
        "Win %": win_pct,
        "Stake": stake,
        "P/L Increase": pl_increase,
        "New P/L": new_pl,
        "New ROI%": new_roi,
    }


def _infer_custom_filter_parts(filter_text: str) -> tuple[str | None, str, str]:
    text = str(filter_text).strip()

    if text.startswith(">=") and " and <=" in text:
        left, right = text.split(" and <=", 1)
        value1 = left.replace(">=", "").strip()
        value2 = right.strip()
        return ">= and <=", value1, value2

    for op in ["!=", ">=", "<=", ">", "<", "="]:
        if text.startswith(op):
            value1 = text[len(op):].strip()
            return op, value1, ""

    return None, "", ""


def apply_saved_filter_step(df: pd.DataFrame, step: dict[str, Any]) -> pd.DataFrame:
    column_name = str(step.get("Column ID", ""))
    filter_text = str(step.get("Filter", ""))
    filter_kind = str(step.get("filter_kind", "stage_e"))

    if not column_name or not filter_text:
        return df.copy()

    if filter_kind == "custom":
        operator = step.get("operator")
        value1 = step.get("value1", "")
        value2 = step.get("value2", "")

        if operator is None:
            operator, value1, value2 = _infer_custom_filter_parts(filter_text)

        if operator is None:
            return df.copy()

        return apply_custom_filter_to_df(
            df=df,
            col=column_name,
            operator=str(operator),
            value1=str(value1),
            value2=str(value2),
        )

    return apply_filter_to_df(df, column_name, filter_text)


def apply_active_filters_sequence(df: pd.DataFrame, active_filters: list[dict[str, Any]]) -> pd.DataFrame:
    working_df = df.copy()

    for step in active_filters:
        working_df = apply_saved_filter_step(working_df, step)

    return working_df