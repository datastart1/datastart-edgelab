from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from edg_analysis_engine import format_value


def inject_css() -> None:
    st.markdown(
        """
    <style>
    section[data-testid="stSidebar"] {
        width: 135px !important;
        min-width: 135px !important;
    }

    html, body, [class*="css"] {
        font-size: 12px;
    }

    .stAppHeader {
        background: transparent;
    }

    .block-container {
        padding-top: 0.45rem;
        padding-bottom: 0.8rem;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
    }

    h1 {
        font-size: 20px !important;
        margin-bottom: 0.25rem !important;
        margin-top: 0rem !important;
        line-height: 1.15 !important;
        padding-top: 0rem !important;
    }

    h2 {
        font-size: 16px !important;
        margin-bottom: 0.25rem !important;
    }

    h3 {
        font-size: 14px !important;
        margin-bottom: 0.2rem !important;
    }

    p, label {
        font-size: 12px !important;
    }

    [data-testid="stDataFrame"] {
        font-size: 11px;
    }

    [data-testid="stDataEditor"] {
        font-size: 11px;
    }

    .stSelectbox, .stButton, .stFileUploader, .stNumberInput, .stCheckbox, .stTextInput {
        margin-bottom: 0.35rem;
    }

    [data-testid="stFileUploaderFile"] {
        display: none !important;
    }

    .training-box {
        padding: 0.5rem 0.7rem;
        border: 1px solid #d0d7de;
        border-radius: 0.5rem;
        margin-bottom: 0.7rem;
        background: rgba(240, 242, 246, 0.35);
    }

    .selected-file-box {
        padding-top: 0.55rem;
    }

    .selected-file-pill {
        display: inline-block;
        padding: 0.45rem 0.65rem;
        border: 1px solid #d0d7de;
        border-radius: 0.5rem;
        background: rgba(240, 242, 246, 0.35);
        font-weight: 600;
    }

    .stage-d-inline {
        padding: 0.45rem 0.7rem;
        border-left: 3px solid #94a3b8;
        background: rgba(240, 242, 246, 0.25);
        margin-top: 0.3rem;
        margin-bottom: 0.8rem;
    }

    .filters-box {
        padding: 0.5rem 0.7rem;
        border: 1px solid #d0d7de;
        border-radius: 0.5rem;
        background: rgba(240, 242, 246, 0.25);
        margin-bottom: 0.7rem;
    }

    .compact-header-meta {
        padding-top: 0.55rem;
        text-align: right;
        font-size: 12px;
    }

    div[data-testid="stCaptionContainer"] {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
    }
    # button filler
    /* STREAMLIT BUTTON COLOURING */
div.stButton > button,
div.stDownloadButton > button,
div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button {
    background: #dbeafe !important;
    background-color: #dbeafe !important;
    color: #111827 !important;
    border: 1px solid #60a5fa !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    box-shadow: none !important;
}

/* HOVER */
div.stButton > button:hover,
div.stDownloadButton > button:hover,
div[data-testid="stButton"] > button:hover,
div[data-testid="stDownloadButton"] > button:hover {
    background: #93c5fd !important;
    background-color: #93c5fd !important;
    color: #111827 !important;
    border: 1px solid #3b82f6 !important;
}

/* ACTIVE / CLICK */
div.stButton > button:active,
div.stDownloadButton > button:active,
div[data-testid="stButton"] > button:active,
div[data-testid="stDownloadButton"] > button:active {
    background: #60a5fa !important;
    background-color: #60a5fa !important;
    color: #111827 !important;
    border: 1px solid #2563eb !important;
}
button[kind="secondary"],
button[kind="primary"] {
    background: #dbeafe !important;
    background-color: #dbeafe !important;
    color: #111827 !important;
    border: 1px solid #60a5fa !important;
}
    </style>
    """,
        unsafe_allow_html=True,
    )


def negative_red_style(val: Any) -> str:
    try:
        if pd.notna(val) and float(val) < 0:
            return "color: red;"
    except Exception:
        pass
    return ""


def style_results_dataframe(df: pd.DataFrame):
    numeric_cols = [c for c in ["Runs", "Win%", "Stake", "P/L", "Cum P/L", "ROI%"] if c in df.columns]

    fmt: dict[str, Any] = {}
    if "Runs" in df.columns:
        fmt["Runs"] = "{:,.0f}"
    if "Win%" in df.columns:
        fmt["Win%"] = "{:.1f}"
    if "Stake" in df.columns:
        fmt["Stake"] = "{:,.0f}"
    if "P/L" in df.columns:
        fmt["P/L"] = "{:,.0f}"
    if "Cum P/L" in df.columns:
        fmt["Cum P/L"] = lambda x: "" if pd.isna(x) else f"{x:,.0f}"
    if "ROI%" in df.columns:
        fmt["ROI%"] = "{:.1f}"

    styler = df.style.format(fmt)

    if numeric_cols:
        styler = styler.set_properties(subset=numeric_cols, **{"text-align": "right"})

    if "P/L" in df.columns:
        styler = styler.map(negative_red_style, subset=["P/L"])
    if "Cum P/L" in df.columns:
        styler = styler.map(negative_red_style, subset=["Cum P/L"])
    if "ROI%" in df.columns:
        styler = styler.map(negative_red_style, subset=["ROI%"])

    first_col = df.columns[0]
    styler = styler.set_properties(subset=[first_col], **{"text-align": "left"})

    return styler


def style_possible_filters_dataframe(df: pd.DataFrame):
    fmt = {
        "Filter No": "{:,.0f}",
        "Rows": "{:,.0f}",
        "Win %": "{:.1f}",
        "Stake": "{:,.0f}",
        "P/L Increase": "{:,.0f}",
        "New P/L": "{:,.0f}",
        "New ROI%": "{:.1f}",
    }

    styler = df.style.format(fmt)

    right_cols = [c for c in ["Filter No", "Rows", "Win %", "Stake", "P/L Increase", "New P/L", "New ROI%"] if c in df.columns]
    left_cols = [c for c in ["Column ID", "Filter"] if c in df.columns]

    if right_cols:
        styler = styler.set_properties(subset=right_cols, **{"text-align": "right"})
    if left_cols:
        styler = styler.set_properties(subset=left_cols, **{"text-align": "left"})

    if "P/L Increase" in df.columns:
        styler = styler.map(negative_red_style, subset=["P/L Increase"])
    if "New P/L" in df.columns:
        styler = styler.map(negative_red_style, subset=["New P/L"])
    if "New ROI%" in df.columns:
        styler = styler.map(negative_red_style, subset=["New ROI%"])

    return styler


def make_pl_bar_chart(df: pd.DataFrame, title: str):
    chart_df = df.iloc[:-1].copy() if len(df) > 1 else df.copy()
    first_col = chart_df.columns[0]

    if chart_df.empty:
        return None

    colors = ["red" if v < 0 else "green" for v in chart_df["P/L"]]

    fig = go.Figure(
        data=[
            go.Bar(
                x=chart_df[first_col].astype(str),
                y=chart_df["P/L"],
                marker_color=colors,
            )
        ]
    )

    fig.update_layout(
        title=title,
        height=360,
        margin=dict(l=20, r=20, t=40, b=60),
        xaxis=dict(title=first_col),
        yaxis=dict(title="P/L"),
    )

    return fig


def make_pl_line_chart(df: pd.DataFrame, title: str):
    chart_df = df.iloc[:-1].copy() if len(df) > 1 else df.copy()
    first_col = chart_df.columns[0]

    if chart_df.empty:
        return None

    cum_col = "Cum P/L" if "Cum P/L" in chart_df.columns else "P/L"

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_df[first_col].astype(str),
            y=chart_df[cum_col],
            mode="lines+markers",
            line=dict(width=3),
            marker=dict(size=6),
        )
    )

    fig.update_layout(
        title=title,
        height=360,
        margin=dict(l=20, r=20, t=40, b=60),
        xaxis=dict(title=first_col),
        yaxis=dict(title="Cumulative P/L"),
    )

    return fig


def make_raw_cumulative_line_chart(curve_df: pd.DataFrame, column_name: str, title: str):
    if curve_df.empty:
        return None

    working = curve_df.copy()

    fig = go.Figure()

    above = working["cum_pl"].where(working["cum_pl"] >= 0)
    below = working["cum_pl"].where(working["cum_pl"] < 0)

    fig.add_trace(
        go.Scatter(
            x=working[column_name],
            y=above,
            mode="lines+markers",
            line=dict(width=3, color="green"),
            marker=dict(size=5, color="green"),
            name="Cumulative P/L (>= 0)",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=working[column_name],
            y=below,
            mode="lines+markers",
            line=dict(width=3, color="red"),
            marker=dict(size=5, color="red"),
            name="Cumulative P/L (< 0)",
        )
    )

    fig.add_hline(y=0, line_width=1, line_dash="dash", line_color="gray")

    min_idx = working["cum_pl"].idxmin()
    max_idx = working["cum_pl"].idxmax()
    last_idx = working.index[-1]

    min_x = working.loc[min_idx, column_name]
    max_x = working.loc[max_idx, column_name]
    last_x = working.loc[last_idx, column_name]
    last_y = working.loc[last_idx, "cum_pl"]

    fig.add_trace(
        go.Scatter(
            x=[min_x],
            y=[working.loc[min_idx, "cum_pl"]],
            mode="markers+text",
            text=[f"Min: {format_value(min_x)}"],
            textposition="bottom center",
            marker=dict(size=10, symbol="diamond", color="red"),
            name="Min P/L",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=[max_x],
            y=[working.loc[max_idx, "cum_pl"]],
            mode="markers+text",
            text=[f"Max: {format_value(max_x)}"],
            textposition="top center",
            marker=dict(size=10, symbol="diamond", color="green"),
            name="Max P/L",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=[last_x],
            y=[last_y],
            mode="markers+text",
            text=[f"Latest: {format_value(last_y)}"],
            textposition="middle right",
            marker=dict(size=9, symbol="circle", color="blue"),
            name="Latest",
        )
    )

    fig.update_layout(
        title=title,
        height=360,
        margin=dict(l=20, r=20, t=40, b=60),
        xaxis=dict(title=column_name),
        yaxis=dict(title="Cumulative P/L"),
    )

    return fig

def make_active_filters_cumulative_date_chart(
    df: pd.DataFrame,
    event_date_col: str,
    profit_col: str,
    title: str,
):
    if df.empty or event_date_col not in df.columns or profit_col not in df.columns:
        return None

    working = df[[event_date_col, profit_col]].copy()
    working[event_date_col] = pd.to_datetime(working[event_date_col], errors="coerce")
    working[profit_col] = pd.to_numeric(working[profit_col], errors="coerce")
    working = working.dropna(subset=[event_date_col, profit_col])

    if working.empty:
        return None

    working = working.sort_values(by=event_date_col).reset_index(drop=True)
    working["cum_pl"] = working[profit_col].cumsum()

    fig = go.Figure()

    above = working["cum_pl"].where(working["cum_pl"] >= 0)
    below = working["cum_pl"].where(working["cum_pl"] < 0)

    fig.add_trace(
        go.Scatter(
            x=working[event_date_col],
            y=above,
            mode="lines+markers",
            line=dict(width=3, color="green"),
            marker=dict(size=5, color="green"),
            name="Cumulative P/L (>= 0)",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=working[event_date_col],
            y=below,
            mode="lines+markers",
            line=dict(width=3, color="red"),
            marker=dict(size=5, color="red"),
            name="Cumulative P/L (< 0)",
        )
    )

    fig.add_hline(y=0, line_width=1, line_dash="dash", line_color="gray")

    min_idx = working["cum_pl"].idxmin()
    max_idx = working["cum_pl"].idxmax()
    last_idx = working.index[-1]

    min_date = working.loc[min_idx, event_date_col]
    max_date = working.loc[max_idx, event_date_col]
    last_date = working.loc[last_idx, event_date_col]
    last_y = working.loc[last_idx, "cum_pl"]

    fig.add_trace(
        go.Scatter(
            x=[min_date],
            y=[working.loc[min_idx, "cum_pl"]],
            mode="markers+text",
            text=[f"Min: {min_date.strftime('%Y-%m-%d')}"],
            textposition="bottom center",
            marker=dict(size=10, symbol="diamond", color="red"),
            name="Min P/L",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=[max_date],
            y=[working.loc[max_idx, "cum_pl"]],
            mode="markers+text",
            text=[f"Max: {max_date.strftime('%Y-%m-%d')}"],
            textposition="top center",
            marker=dict(size=10, symbol="diamond", color="green"),
            name="Max P/L",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=[last_date],
            y=[last_y],
            mode="markers+text",
            text=[f"Latest: {format_value(last_y)}"],
            textposition="middle right",
            marker=dict(size=9, symbol="circle", color="blue"),
            name="Latest",
        )
    )

    fig.update_layout(
        title=title,
        height=360,
        margin=dict(l=20, r=20, t=40, b=60),
        xaxis=dict(title="Date"),
        yaxis=dict(title="Cumulative P/L"),
    )

    return fig

def build_printable_filters_html(file_name: str, filter_rows: list[dict[str, Any]]) -> str:
    from datetime import datetime

    report_date = datetime.now().strftime("%d %B %Y")

    table_rows = []
    for row in filter_rows:
        table_rows.append(
            f"<tr><td>{row['Filter No']}</td><td>{row['Column ID']}</td><td>{row['Filter']}</td>"
            f"<td>{row['Rows']:,}</td><td>{row['Win %']:.1f}</td><td>{row['Stake']:,.0f}</td>"
            f"<td>{row['P/L Increase']:,.0f}</td><td>{row['New P/L']:,.0f}</td><td>{row['New ROI%']:.1f}</td></tr>"
        )

    rows_html = "\n".join(table_rows)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{file_name} Selected Filters</title>
<style>
body {{ font-family: Arial, sans-serif; padding: 20px; }}
h1 {{ font-size: 22px; margin-bottom: 6px; }}
h2 {{ font-size: 14px; font-weight: normal; color: #444; margin-top: 0; margin-bottom: 18px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #999; padding: 8px; font-size: 12px; text-align: right; }}
th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3) {{ text-align: left; }}
</style>
</head>
<body>
<h1>{file_name} Selected Filters</h1>
<h2>Generated on {report_date}</h2>
<table>
<thead>
<tr>
<th>Filter No</th>
<th>Column ID</th>
<th>Filter</th>
<th>Rows</th>
<th>Win %</th>
<th>Stake</th>
<th>P/L Increase</th>
<th>New P/L</th>
<th>New ROI%</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""

