from __future__ import annotations

import io
from itertools import combinations

import numpy as np
import pandas as pd

from viapps_analyzer.data_loader import REPORT_METADATA_FIELDS, ViaPPSReport


LINEAR_REFERENCE_DEFAULTS = {
    "start_meter": 1.0,
    "direction": "ascending",
    "analysis_begin_m": None,
    "analysis_end_m": None,
}


def compute_linear_reference(report: ViaPPSReport, start_meter: float, direction: str) -> pd.Series:
    df = report.table
    if report.distance_column and report.distance_column in df.columns:
        base = pd.to_numeric(df[report.distance_column], errors="coerce")
    else:
        base = pd.Series(np.arange(1, len(df) + 1, dtype=float), index=df.index)
    if base.dropna().empty:
        return pd.Series(np.nan, index=df.index, dtype=float)
    first_value = float(base.dropna().iloc[0])
    offset = base - first_value
    sign = 1.0 if direction == "ascending" else -1.0
    return pd.Series(float(start_meter) + sign * offset, index=df.index, dtype=float)


def _normalize_linear_reference_settings(settings: dict[str, float | str] | None) -> dict[str, float | str | None]:
    merged = dict(LINEAR_REFERENCE_DEFAULTS)
    if settings:
        merged.update(settings)
    begin = merged.get("analysis_begin_m")
    end = merged.get("analysis_end_m")
    begin_value = float(begin) if begin not in (None, "") else None
    end_value = float(end) if end not in (None, "") else None
    if begin_value is not None and end_value is not None and begin_value > end_value:
        begin_value, end_value = end_value, begin_value
    merged["analysis_begin_m"] = begin_value
    merged["analysis_end_m"] = end_value
    merged["start_meter"] = float(merged.get("start_meter", 1.0))
    merged["direction"] = str(merged.get("direction", "ascending"))
    return merged


def apply_linear_reference_window(report: ViaPPSReport, settings: dict[str, float | str] | None = None) -> ViaPPSReport:
    normalized = _normalize_linear_reference_settings(settings)
    df = report.table.copy()
    df["linear_reference_m"] = compute_linear_reference(report, normalized["start_meter"], normalized["direction"])
    mask = pd.Series(True, index=df.index)
    begin = normalized["analysis_begin_m"]
    end = normalized["analysis_end_m"]
    if begin is not None:
        mask &= df["linear_reference_m"] >= begin
    if end is not None:
        mask &= df["linear_reference_m"] <= end
    kept_index = df.index[mask.fillna(False)]
    df = df.loc[kept_index].reset_index(drop=True)
    coordinates = report.coordinates.reindex(kept_index).reset_index(drop=True) if not report.coordinates.empty else report.coordinates.copy()
    if not coordinates.empty:
        coordinates["linear_reference_m"] = df.get("linear_reference_m")
    return ViaPPSReport(
        path=report.path,
        table=df,
        metadata_before=report.metadata_before,
        metadata_after=report.metadata_after,
        coordinates=coordinates,
        coordinate_columns=report.coordinate_columns,
        distance_column=report.distance_column,
        datetime_column=report.datetime_column,
        table_start_line=report.table_start_line,
        table_end_line=report.table_end_line,
        file_metadata=report.file_metadata,
        display_name=report.display_name,
    )


def resample_report(report: ViaPPSReport, interval_m: int, start_meter: float = 1.0, direction: str = "ascending") -> pd.DataFrame:
    df = report.table.copy()
    if "linear_reference_m" not in df.columns:
        df["linear_reference_m"] = compute_linear_reference(report, start_meter, direction)
    df = df.dropna(subset=["linear_reference_m"]).sort_values("linear_reference_m")
    if df.empty:
        return df
    df["distance_bin_m"] = (df["linear_reference_m"] / interval_m).round().astype(int) * interval_m
    numeric_columns = [col for col in df.select_dtypes(include=["number"]).columns if col != "distance_bin_m"]
    aggregated = df.groupby("distance_bin_m", as_index=False)[numeric_columns].mean(numeric_only=True)
    non_numeric_columns = [col for col in df.columns if col not in numeric_columns + ["distance_bin_m"]]
    grouped = df.groupby("distance_bin_m")
    for column in non_numeric_columns:
        aggregated[column] = grouped[column].first().values
    return aggregated


def align_reports(reports: dict[str, ViaPPSReport], interval_m: int, fields: list[str], linear_reference_settings: dict[str, dict[str, float | str]] | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    linear_reference_settings = linear_reference_settings or {}
    for label, report in reports.items():
        settings = _normalize_linear_reference_settings(linear_reference_settings.get(label, {}))
        sampled = resample_report(report, interval_m, start_meter=float(settings["start_meter"]), direction=str(settings["direction"]))
        if sampled.empty:
            continue
        keep_fields = [field for field in fields if field in sampled.columns]
        subset = sampled[["distance_bin_m", *keep_fields]].copy()
        subset = subset.rename(columns={field: f"{label}__{field}" for field in keep_fields})
        frames.append(subset)
    if not frames:
        return pd.DataFrame()
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="distance_bin_m", how="outer")
    return merged.sort_values("distance_bin_m").reset_index(drop=True)


def comparison_table(aligned: pd.DataFrame, fields: list[str], labels: list[str]) -> pd.DataFrame:
    if aligned.empty or len(labels) < 2:
        return pd.DataFrame()
    base = labels[0]
    result = aligned.copy()
    for field in fields:
        base_col = f"{base}__{field}"
        if base_col not in result.columns:
            continue
        for other in labels[1:]:
            other_col = f"{other}__{field}"
            if other_col not in result.columns:
                continue
            result[f"diff__{other}__{field}"] = result[other_col] - result[base_col]
            result[f"ratio__{other}__{field}"] = np.where(result[base_col] != 0, result[other_col] / result[base_col], np.nan)
    return result


def correlation_summary(aligned: pd.DataFrame, fields: list[str], labels: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if aligned.empty or len(labels) < 2:
        return pd.DataFrame(columns=["field", "file_a", "file_b", "correlation", "overlap_count"])
    for field in fields:
        for file_a, file_b in combinations(labels, 2):
            col_a = f"{file_a}__{field}"
            col_b = f"{file_b}__{field}"
            if col_a not in aligned.columns or col_b not in aligned.columns:
                continue
            pair = aligned[[col_a, col_b]].dropna()
            correlation = pair[col_a].corr(pair[col_b]) if len(pair) >= 2 else np.nan
            rows.append({
                "field": field,
                "file_a": file_a,
                "file_b": file_b,
                "correlation": correlation,
                "overlap_count": int(len(pair)),
            })
    return pd.DataFrame(rows)


def summary_statistics(report: ViaPPSReport, fields: list[str]) -> pd.DataFrame:
    if not fields:
        return pd.DataFrame(columns=["field", "count", "mean", "std", "min", "max"])
    stats = report.table[fields].describe().transpose()
    for column in ["mean", "std", "min", "max"]:
        if column not in stats.columns:
            stats[column] = np.nan
    return stats[["count", "mean", "std", "min", "max"]].reset_index(names="field")


def metadata_table(report: ViaPPSReport) -> pd.DataFrame:
    return pd.DataFrame([{"field": key, "value": value} for key, value in report.metadata.items()])


def file_metadata_table(reports: dict[str, ViaPPSReport]) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for label, report in reports.items():
        row = {key: report.file_metadata.get(key, "") for key in REPORT_METADATA_FIELDS}
        row["file_name"] = report.file_metadata.get("file_name") or report.display_name or label
        rows.append(row)
    return pd.DataFrame(rows)


def export_dataframe_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def export_dataframe_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=(sheet_name[:31] or "Sheet1"), index=False)
    return buffer.getvalue()


def build_summary_report(reports: dict[str, ViaPPSReport], fields: list[str]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for label, report in reports.items():
        keep = [field for field in fields if field in report.table.columns]
        summary = summary_statistics(report, keep)
        if summary.empty:
            continue
        summary.insert(0, "file", label)
        parts.append(summary)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


