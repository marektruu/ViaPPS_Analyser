from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from viapps_analyzer.analyzer import comparison_table
from viapps_analyzer.data_loader import ViaPPSReport


def build_comparison_figure(
    reports: dict[str, ViaPPSReport],
    aligned,
    fields: list[str],
    comparison_mode: str,
    template: str,
    translated_fields: dict[str, str] | None = None,
    x_axis_title: str = "Distance / Bin (m)",
    y_axis_title: str = "Value",
    legend_title: str = "Series",
) -> go.Figure:
    translated_fields = translated_fields or {}
    rows = max(1, len(fields))
    subplot_titles = [translated_fields.get(field, field) for field in fields] or ["No field selected"]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, subplot_titles=subplot_titles)
    labels = list(reports.keys())
    diff_table = comparison_table(aligned, fields, labels) if comparison_mode == "difference" else None
    for idx, field in enumerate(fields, start=1):
        display_field = translated_fields.get(field, field)
        if comparison_mode == "difference" and diff_table is not None:
            for label in labels[1:]:
                col = f"diff__{label}__{field}"
                if col in diff_table.columns:
                    fig.add_trace(go.Scatter(x=diff_table["distance_bin_m"], y=diff_table[col], mode="lines", name=f"{label} - {labels[0]} [{display_field}]"), row=idx, col=1)
            continue
        for label in labels:
            col = f"{label}__{field}"
            if col in aligned.columns:
                fig.add_trace(go.Scatter(x=aligned["distance_bin_m"], y=aligned[col], mode="lines", name=f"{label} [{display_field}]"), row=idx, col=1)
    fig.update_layout(height=max(420, 280 * rows), template=template, legend_title_text=legend_title)
    fig.update_xaxes(title_text=x_axis_title, row=rows, col=1)
    fig.update_yaxes(title_text=y_axis_title)
    return fig


def build_individual_figure(
    report: ViaPPSReport,
    fields: list[str],
    template: str,
    translated_fields: dict[str, str] | None = None,
    x_values=None,
    x_axis_title: str = "Distance / Index",
    y_axis_title: str = "Value",
) -> go.Figure:
    translated_fields = translated_fields or {}
    fig = go.Figure()
    if x_values is None:
        x_values = report.table[report.distance_column] if report.distance_column else report.table.index
    for field in fields:
        if field in report.table.columns:
            fig.add_trace(go.Scatter(x=x_values, y=report.table[field], mode="lines", name=translated_fields.get(field, field)))
    fig.update_layout(template=template, xaxis_title=x_axis_title, yaxis_title=y_axis_title)
    return fig


def export_plot_image(figure: go.Figure, image_format: str) -> bytes:
    return figure.to_image(format=image_format)


def export_plot_html(figure: go.Figure) -> bytes:
    return figure.to_html(include_plotlyjs="cdn").encode("utf-8")
