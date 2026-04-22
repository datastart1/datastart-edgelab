import math
import re
import time
from typing import Any

import pandas as pd


def format_value(v: Any) -> str:
    if pd.isna(v):
        return "Missing"

    try:
        f = float(v)
    except Exception:
        return str(v)

    if f.is_integer():
        return f"{int(f)}"
    if abs(f) >= 100:
        return f"{f:.0f}"
    if abs(f) >= 10:
        return f"{f:.1f}".rstrip("0").rstrip(".")
    if abs(f) >= 1:
        return f"{f:.2f}".rstrip("0").rstrip(".")
    return f"{f:.3f}".rstrip("0").rstrip(".")


def prepare_sorted_dataframe(df: pd.DataFrame, event_date_col: str) -> pd.DataFrame:
    df_sorted = df.copy()
    df_sorted[event_date_col] = pd.to_datetime(df_sorted[event_date_col], errors="coerce")
    df_sorted = df_sorted.dropna(subset=[event_date_col])
    df_sorted = df_sorted.sort_values(by=event_date_col, ascending=True).reset_index(drop=True)
    return df_sorted


def looks_like_date_name(column_name: str) -> bool:
    name = column_name.strip().lower()
    date_words = ["date", "time", "year", "month", "day", "timestamp"]
    return any(word in name for word in date_words)


def detect_column_type(series: pd.Series, column_name: str) -> str:
    non_null = series.dropna()

    if non_null.empty:
        return "Categorical"

    if pd.api.types.is_numeric_dtype(series):
        unique_ratio = non_null.nunique() / max(len(non_null), 1)
        if unique_ratio < 0.05:
            return "Discrete"
        return "Continuous"

    numeric = pd.to_numeric(non_null, errors="coerce")
    numeric_success_ratio = numeric.notna().mean()

    if numeric_success_ratio > 0.9:
        unique_ratio = numeric.dropna().nunique() / max(len(numeric.dropna()), 1)
        if unique_ratio < 0.05:
            return "Discrete"
        return "Continuous"

    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        sample = non_null.astype(str).head(20)
        date_pattern = re.compile(r"[-/:]")
        values_look_date_like = sample.str.contains(date_pattern, regex=True).mean() > 0.6

        if looks_like_date_name(column_name) or values_look_date_like:
            parsed_dates = pd.to_datetime(non_null, errors="coerce")
            date_success_ratio = parsed_dates.notna().mean()
            if date_success_ratio > 0.9:
                return "Date"

    return "Categorical"


def suggest_column(columns: list[str], keywords: dict[str, int]) -> str | None:
    best_col = None
    best_score = -1

    for col in columns:
        name = col.strip().lower()
        score = 0
        for kw, points in keywords.items():
            if kw in name:
                score += points

        if score > best_score:
            best_score = score
            best_col = col

    return best_col if best_score > 0 else None


def sort_mixed_unique_values(values: list[Any]) -> list[Any]:
    try:
        numeric = pd.to_numeric(pd.Series(values), errors="coerce")
        if numeric.notna().all():
            return list(numeric.sort_values().tolist())
    except Exception:
        pass

    return sorted(values, key=lambda x: str(x).lower())


def nice_step(raw_step: float) -> float:
    if raw_step <= 0:
        return 1

    exponent = math.floor(math.log10(raw_step))
    fraction = raw_step / (10 ** exponent)
    nice_fractions = [1, 2, 2.5, 5, 10]

    for nf in nice_fractions:
        if fraction <= nf:
            return nf * (10 ** exponent)

    return 10 ** (exponent + 1)


def choose_target_bin_count(min_val: float, max_val: float, non_null_count: int) -> int:
    value_range = max_val - min_val

    if non_null_count < 20:
        return 4
    if value_range <= 1.0 and min_val >= 0 and max_val <= 1:
        return 10
    if value_range <= 10 and min_val >= 0 and max_val <= 10:
        return 10
    if value_range <= 100 and min_val >= 0 and max_val <= 100:
        return 10
    if non_null_count < 40:
        return 5
    if non_null_count < 80:
        return 6
    if non_null_count < 150:
        return 8
    if non_null_count < 300:
        return 10
    return 12


def build_numeric_bin_plan(series: pd.Series) -> list[dict[str, Any]]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()

    if numeric.empty:
        return []

    min_val = float(numeric.min())
    max_val = float(numeric.max())

    if min_val == max_val:
        return [{
            "label": format_value(min_val),
            "lower": min_val,
            "upper": max_val,
            "kind": "equal",
        }]

    target_bins = choose_target_bin_count(min_val, max_val, len(numeric))
    raw_step = (max_val - min_val) / target_bins
    step = nice_step(raw_step)

    start = math.floor(min_val / step) * step
    end = math.ceil(max_val / step) * step

    if min_val >= 0 and start < 0:
        start = 0.0

    def count_bins(local_start: float, local_end: float, local_step: float) -> int:
        return int(round((local_end - local_start) / local_step))

    bin_count = count_bins(start, end, step)

    while bin_count > 15:
        step = nice_step(step * 1.25)
        start = math.floor(min_val / step) * step
        end = math.ceil(max_val / step) * step
        if min_val >= 0 and start < 0:
            start = 0.0
        bin_count = count_bins(start, end, step)

    attempts = 0
    while bin_count < 4 and attempts < 10:
        step = nice_step(step / 2)
        start = math.floor(min_val / step) * step
        end = math.ceil(max_val / step) * step
        if min_val >= 0 and start < 0:
            start = 0.0
        bin_count = count_bins(start, end, step)
        attempts += 1

    boundaries: list[float] = []
    current = start
    while current <= end + (step / 10):
        boundaries.append(round(current, 10))
        current += step

    if len(boundaries) < 2:
        boundaries = [min_val, max_val]

    categories: list[dict[str, Any]] = []

    if len(boundaries) >= 2:
        categories.append({
            "label": f"< {format_value(boundaries[1])}",
            "lower": float("-inf"),
            "upper": boundaries[1],
            "kind": "lt",
        })

    for i in range(1, len(boundaries) - 2):
        lower = boundaries[i]
        upper = boundaries[i + 1]
        categories.append({
            "label": f"{format_value(lower)} - < {format_value(upper)}",
            "lower": lower,
            "upper": upper,
            "kind": "range",
        })

    if len(boundaries) >= 2:
        categories.append({
            "label": f">= {format_value(boundaries[-2])}",
            "lower": boundaries[-2],
            "upper": float("inf"),
            "kind": "ge",
        })

    deduped = []
    seen = set()
    for cat in categories:
        if cat["label"] not in seen:
            deduped.append(cat)
            seen.add(cat["label"])

    return deduped


def build_discrete_category_plan(series: pd.Series) -> list[dict[str, Any]]:
    non_null = series.dropna()
    unique_values = list(pd.Series(non_null.unique()).tolist())
    unique_values = sort_mixed_unique_values(unique_values)

    return [{
        "label": str(v),
        "value": v,
        "kind": "exact",
    } for v in unique_values]


def build_categorical_category_plan(series: pd.Series) -> list[dict[str, Any]]:
    non_null = series.dropna()
    unique_values = list(pd.Series(non_null.unique()).tolist())
    unique_values = sorted(unique_values, key=lambda x: str(x).lower())

    return [{
        "label": str(v),
        "value": v,
        "kind": "exact",
    } for v in unique_values]


def build_column_category_plan(
    df: pd.DataFrame,
    column_name: str,
    selected_type: str,
) -> tuple[list[dict[str, Any]], str]:
    if selected_type == "Discrete":
        return build_discrete_category_plan(df[column_name]), "unique_values"

    if selected_type == "Continuous":
        return build_numeric_bin_plan(df[column_name]), "numeric_bins"

    if selected_type == "Categorical":
        return build_categorical_category_plan(df[column_name]), "categorical_values"

    return [], "not_applicable"


def calculate_grand_totals(df: pd.DataFrame, stake_col: str, profit_col: str) -> dict[str, Any]:
    stake_series = pd.to_numeric(df[stake_col], errors="coerce")
    profit_series = pd.to_numeric(df[profit_col], errors="coerce")

    valid_mask = stake_series.notna() & profit_series.notna()
    stake_valid = stake_series.loc[valid_mask].astype(float)
    profit_valid = profit_series.loc[valid_mask].astype(float)

    runs = int(len(profit_valid))
    stake = float(stake_valid.sum()) if runs > 0 else 0.0
    pl = float(profit_valid.sum()) if runs > 0 else 0.0
    winners = int((profit_valid > 0).sum()) if runs > 0 else 0
    losers = runs - winners

    longest_winning_run = 0
    longest_losing_run = 0

    if runs > 0:
        is_win = (profit_valid > 0).tolist()

        current_win = 0
        current_loss = 0

        for flag in is_win:
            if flag:
                current_win += 1
                current_loss = 0
            else:
                current_loss += 1
                current_win = 0

            if current_win > longest_winning_run:
                longest_winning_run = current_win
            if current_loss > longest_losing_run:
                longest_losing_run = current_loss

    return {
        "runs": runs,
        "stake": stake,
        "pl": pl,
        "winners": winners,
        "losers": losers,
        "longest_winning_run": longest_winning_run,
        "longest_losing_run": longest_losing_run,
    }


def build_stage_a_summary(totals: dict[str, Any]) -> pd.DataFrame:
    runs = totals["runs"]
    stake = totals["stake"]
    pl = totals["pl"]
    winners = totals["winners"]

    win_pct = (winners / runs * 100) if runs > 0 else 0.0
    roi_pct = (pl / stake * 100) if stake != 0 else 0.0

    return pd.DataFrame([{
        "Category": "All",
        "Runs": runs,
        "Win%": win_pct,
        "Stake": stake,
        "P/L": pl,
        "ROI%": roi_pct,
    }])


def get_columns_to_analyze(
    df_columns: list[str],
    analyze_flags: dict[str, bool],
    column_types: dict[str, str],
    event_date_col: str,
    target_col: str,
) -> list[str]:
    excluded = {event_date_col, target_col}

    return [
        col for col in df_columns
        if analyze_flags.get(col, True)
        and col not in excluded
        and column_types.get(col) in ["Continuous", "Discrete", "Categorical"]
    ]


def build_stage_b_plans(
    df_sorted: pd.DataFrame,
    columns_to_analyze: list[str],
    column_types: dict[str, str],
) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}

    for col in columns_to_analyze:
        categories, plan_type = build_column_category_plan(
            df=df_sorted,
            column_name=col,
            selected_type=column_types[col],
        )

        plans[col] = {
            "selected_type": column_types[col],
            "plan_type": plan_type,
            "category_count": len(categories),
            "categories": categories,
        }

    return plans


def build_stage_c_results(
    df_sorted: pd.DataFrame,
    columns_to_analyze: list[str],
    stage_b_plans: dict[str, dict[str, Any]],
    stake_col: str,
    profit_col: str,
) -> dict[str, pd.DataFrame]:
    results: dict[str, pd.DataFrame] = {}

    stake_series = pd.to_numeric(df_sorted[stake_col], errors="coerce")
    profit_series = pd.to_numeric(df_sorted[profit_col], errors="coerce")
    valid_mask = stake_series.notna() & profit_series.notna()

    base_df = df_sorted.loc[valid_mask].copy()
    base_df["_stake"] = stake_series.loc[valid_mask].astype(float)
    base_df["_profit"] = profit_series.loc[valid_mask].astype(float)
    base_df["_winner"] = (base_df["_profit"] > 0).astype(int)

    for col in columns_to_analyze:
        plan = stage_b_plans[col]
        label_header = "Band" if plan["plan_type"] == "numeric_bins" else "Category"
        category_order = [cat["label"] for cat in plan["categories"]]

        working = base_df[[col, "_stake", "_profit", "_winner"]].copy()

        if plan["plan_type"] == "numeric_bins":
            numeric_col = pd.to_numeric(working[col], errors="coerce")
            labels = pd.Series(pd.NA, index=working.index, dtype="object")

            for cat in plan["categories"]:
                kind = cat["kind"]

                if kind == "equal":
                    mask = numeric_col == cat["lower"]
                elif kind == "lt":
                    mask = numeric_col < cat["upper"]
                elif kind == "range":
                    mask = (numeric_col >= cat["lower"]) & (numeric_col < cat["upper"])
                elif kind == "ge":
                    mask = numeric_col >= cat["lower"]
                else:
                    mask = pd.Series(False, index=working.index)

                labels.loc[mask] = cat["label"]

            working["_category"] = labels

        elif plan["plan_type"] in ["unique_values", "categorical_values"]:
            value_to_label = {str(cat["value"]): cat["label"] for cat in plan["categories"]}
            working["_category"] = working[col].astype(str).map(value_to_label)

        else:
            working["_category"] = pd.NA

        grouped = (
            working.dropna(subset=["_category"])
            .groupby("_category", dropna=False)
            .agg(
                Runs=("_profit", "size"),
                Winners=("_winner", "sum"),
                Stake=("_stake", "sum"),
                PL=("_profit", "sum"),
            )
        )

        rows = []
        cumulative_pl = 0.0
        total_runs = 0
        total_winners = 0
        total_stake = 0.0
        total_pl = 0.0

        for label in category_order:
            if label in grouped.index:
                runs = int(grouped.loc[label, "Runs"])
                winners = int(grouped.loc[label, "Winners"])
                stake = float(grouped.loc[label, "Stake"])
                pl = float(grouped.loc[label, "PL"])
            else:
                runs = 0
                winners = 0
                stake = 0.0
                pl = 0.0

            win_pct = (winners / runs * 100) if runs > 0 else 0.0
            roi_pct = (pl / stake * 100) if stake != 0 else 0.0

            cumulative_pl += pl
            total_runs += runs
            total_winners += winners
            total_stake += stake
            total_pl += pl

            rows.append({
                label_header: label,
                "Runs": runs,
                "Win%": win_pct,
                "Stake": stake,
                "P/L": pl,
                "Cum P/L": cumulative_pl,
                "ROI%": roi_pct,
            })

        total_win_pct = (total_winners / total_runs * 100) if total_runs > 0 else 0.0
        total_roi_pct = (total_pl / total_stake * 100) if total_stake != 0 else 0.0

        rows.append({
            label_header: "Total",
            "Runs": total_runs,
            "Win%": total_win_pct,
            "Stake": total_stake,
            "P/L": total_pl,
            "Cum P/L": None,
            "ROI%": total_roi_pct,
        })

        results[col] = pd.DataFrame(rows)

    return results


def build_filter_text_from_stage_d(
    n_rows: int,
    min_pos: int,
    max_pos: int,
    min_value: Any,
    max_value: Any,
    total_pl: float,
    max_cum_pl: float,
    min_cum_pl: float,
) -> str:
    if n_rows == 0:
        return "No usable numeric rows for filter analysis."

    edge_threshold = max(3, math.ceil(n_rows * 0.05))
    lower_is_worth_using = min_pos >= edge_threshold
    upper_is_worth_using = max_pos <= (n_rows - edge_threshold - 1)

    min_val_text = format_value(min_value)
    max_val_text = format_value(max_value)

    if min_pos < max_pos:
        if lower_is_worth_using and upper_is_worth_using:
            return f"> {min_val_text} and <= {max_val_text}"
        if lower_is_worth_using:
            return f"> {min_val_text}"
        if upper_is_worth_using:
            return f"<= {max_val_text}"
        return "No strong simple filter identified."

    left_segment_pl = max_cum_pl
    right_segment_pl = total_pl - min_cum_pl

    left_good = left_segment_pl > 0 and upper_is_worth_using
    right_good = right_segment_pl > 0 and lower_is_worth_using

    if left_good and right_good:
        return f"<= {max_val_text} or > {min_val_text}"
    if left_good:
        return f"<= {max_val_text}"
    if right_good:
        return f"> {min_val_text}"

    return "No strong simple filter identified."


def build_stage_d_results(
    df_sorted: pd.DataFrame,
    columns_to_analyze: list[str],
    column_types: dict[str, str],
    profit_col: str,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}

    for col in columns_to_analyze:
        if column_types.get(col) not in ["Continuous", "Discrete"]:
            continue

        working = df_sorted[[col, profit_col]].copy()
        working[col] = pd.to_numeric(working[col], errors="coerce")
        working[profit_col] = pd.to_numeric(working[profit_col], errors="coerce")
        working = working.dropna(subset=[col, profit_col]).sort_values(by=col, ascending=True).reset_index(drop=True)

        if working.empty:
            results[col] = {
                "available": False,
                "message": "No usable numeric rows for Stage D.",
            }
            continue

        working["cum_pl"] = working[profit_col].cumsum()

        min_idx = int(working["cum_pl"].idxmin())
        max_idx = int(working["cum_pl"].idxmax())

        min_value = working.loc[min_idx, col]
        max_value = working.loc[max_idx, col]
        min_cum_pl = float(working.loc[min_idx, "cum_pl"])
        max_cum_pl = float(working.loc[max_idx, "cum_pl"])
        total_pl = float(working[profit_col].sum())

        filter_text = build_filter_text_from_stage_d(
            n_rows=len(working),
            min_pos=min_idx,
            max_pos=max_idx,
            min_value=min_value,
            max_value=max_value,
            total_pl=total_pl,
            max_cum_pl=max_cum_pl,
            min_cum_pl=min_cum_pl,
        )

        results[col] = {
            "available": True,
            "rows_used": len(working),
            "min_value": min_value,
            "min_cum_pl": min_cum_pl,
            "min_position": min_idx + 1,
            "max_value": max_value,
            "max_cum_pl": max_cum_pl,
            "max_position": max_idx + 1,
            "suggested_filter": filter_text,
        }

    return results


def build_stage_e_filters(
    df_sorted: pd.DataFrame,
    stage_d_results: dict[str, dict[str, Any]],
    stake_col: str,
    profit_col: str,
    calculate_filter_metrics_fn,
    apply_filter_to_df_fn,
) -> pd.DataFrame:
    base_totals = calculate_grand_totals(df_sorted, stake_col, profit_col)
    base_pl = base_totals["pl"]

    rows = []

    for col, d in stage_d_results.items():
        if not d.get("available", False):
            continue

        filter_text = d.get("suggested_filter", "")
        if "No strong" in filter_text or not filter_text.strip():
            continue

        filtered_df = apply_filter_to_df_fn(df_sorted, col, filter_text)

        if filtered_df.empty:
            continue

        metrics = calculate_filter_metrics_fn(filtered_df, stake_col, profit_col, base_pl)

        rows.append({
            "Column ID": col,
            "Filter": filter_text,
            **metrics,
        })

    filters_df = pd.DataFrame(rows)

    if filters_df.empty:
        return filters_df

    filters_df = filters_df.sort_values(by="New ROI%", ascending=False).reset_index(drop=True)
    filters_df.insert(0, "Filter No", range(1, len(filters_df) + 1))

    return filters_df


def run_full_analysis(
    df_input: pd.DataFrame,
    event_date_col: str,
    stake_col: str,
    target_col: str,
    column_types: dict[str, str],
    analyze_flags: dict[str, bool],
    calculate_filter_metrics_fn,
    apply_filter_to_df_fn,
) -> dict[str, Any]:
    timings = {}

    t0 = time.perf_counter()
    df_sorted = prepare_sorted_dataframe(df_input, event_date_col)
    timings["prepare_sorted_dataframe"] = time.perf_counter() - t0

    if df_sorted.empty:
        return {
            "error": "No valid rows remain after converting and sorting the Event Date column."
        }

    t1 = time.perf_counter()
    grand_totals = calculate_grand_totals(df_sorted, stake_col, target_col)
    summary_df = build_stage_a_summary(grand_totals)
    timings["stage_a"] = time.perf_counter() - t1

    t2 = time.perf_counter()
    columns_to_analyze = get_columns_to_analyze(
        df_columns=df_input.columns.tolist(),
        analyze_flags=analyze_flags,
        column_types=column_types,
        event_date_col=event_date_col,
        target_col=target_col,
    )
    timings["get_columns_to_analyze"] = time.perf_counter() - t2

    t3 = time.perf_counter()
    stage_b_plans = build_stage_b_plans(
        df_sorted=df_sorted,
        columns_to_analyze=columns_to_analyze,
        column_types=column_types,
    )
    timings["stage_b"] = time.perf_counter() - t3

    t4 = time.perf_counter()
    stage_c_results = build_stage_c_results(
        df_sorted=df_sorted,
        columns_to_analyze=columns_to_analyze,
        stage_b_plans=stage_b_plans,
        stake_col=stake_col,
        profit_col=target_col,
    )
    timings["stage_c"] = time.perf_counter() - t4

    t5 = time.perf_counter()
    stage_d_results = build_stage_d_results(
        df_sorted=df_sorted,
        columns_to_analyze=columns_to_analyze,
        column_types=column_types,
        profit_col=target_col,
    )
    timings["stage_d"] = time.perf_counter() - t5

    t6 = time.perf_counter()
    stage_e_filters = build_stage_e_filters(
        df_sorted=df_sorted,
        stage_d_results=stage_d_results,
        stake_col=stake_col,
        profit_col=target_col,
        calculate_filter_metrics_fn=calculate_filter_metrics_fn,
        apply_filter_to_df_fn=apply_filter_to_df_fn,
    )
    timings["stage_e"] = time.perf_counter() - t6

    timings["total_analysis_time"] = sum(timings.values())

    return {
        "summary_df": summary_df,
        "grand_totals": grand_totals,
        "stage_b_plans": stage_b_plans,
        "stage_c_results": stage_c_results,
        "stage_d_results": stage_d_results,
        "stage_e_filters": stage_e_filters,
        "columns_to_analyze": columns_to_analyze,
        "df_sorted_preview": df_sorted.head(10).copy(),
        "timings": timings,
    }