from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


COORDINATE_HINTS = {
    "lat": ["lat", "latitude", "breddegrad", "y_wgs84", "gps_lat"],
    "lon": ["lon", "lng", "longitude", "lengdegrad", "x_wgs84", "gps_lon"],
    "x": ["x", "east", "easting", "ost", "utm_x"],
    "y": ["y", "north", "northing", "nord", "utm_y"],
}
DISTANCE_HINTS = ["distance", "avstand", "chainage", "station", "stasjon", "km", "meter", "m"]
DATE_HINTS = ["date", "dato", "tid", "time", "timestamp"]
FILENAME_PATTERN = re.compile(
    r"^PPS_[A-Za-z]+\d+_(?P<road>\d+)_(?P<section>\d+)_.+?felt(?P<direction>\d+)_+(?P<timestamp>\d{8}-\d{6})$",
    re.IGNORECASE,
)
REPORT_METADATA_FIELDS = {
    "file_name": ("Filnavn", "File name"),
    "report_date": ("Rapportdato", "Report date"),
    "recording_date": ("Opptaksdato", "Recording date"),
    "measurement_length_m": ("Malingslengdem", "Measurement length m"),
    "start_county": ("Startposisjon: Fylke", "Start position: County"),
    "start_road": ("Startposisjon: Veg", "Start position: Road"),
    "start_section": ("Startposisjon: Strekning", "Start position: Section"),
}


@dataclass
class ViaPPSReport:
    path: Path
    table: pd.DataFrame
    metadata_before: dict[str, str]
    metadata_after: dict[str, str]
    coordinates: pd.DataFrame
    coordinate_columns: dict[str, str | None]
    distance_column: str | None
    datetime_column: str | None
    table_start_line: int
    table_end_line: int
    file_metadata: dict[str, str] = field(default_factory=dict)
    display_name: str = ""

    @property
    def metadata(self) -> dict[str, str]:
        merged = dict(self.metadata_before)
        merged.update(self.metadata_after)
        return merged


def list_tsv_files(directory: str | Path, recursive: bool = False) -> list[Path]:
    path = Path(directory)
    if not path.exists():
        return []
    iterator = path.rglob("*") if recursive else path.iterdir()
    return sorted([p for p in iterator if p.suffix.lower() in {".tsv", ".txt"} and p.is_file()])


def shorten_report_filename(path: str | Path) -> str:
    file_path = Path(path)
    match = FILENAME_PATTERN.search(file_path.stem)
    if match:
        return "{road}_{section}_{direction}_{timestamp}".format(**match.groupdict())
    return file_path.stem


def _split_line(line: str) -> list[str]:
    return [cell.strip() for cell in line.rstrip("\n").split("\t")]


def _looks_numeric(value: str) -> bool:
    cleaned = value.strip().replace(" ", "").replace(",", ".")
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _score_header(cells: list[str], next_cells: list[str] | None) -> float:
    if len(cells) < 2:
        return -1
    unique_ratio = len(set(cells)) / max(len(cells), 1)
    alpha_ratio = sum(bool(re.search(r"[A-Za-zÆØÅæøå]", cell)) for cell in cells) / len(cells)
    next_numeric_ratio = 0.0
    if next_cells and len(next_cells) == len(cells):
        next_numeric_ratio = sum(_looks_numeric(cell) for cell in next_cells) / len(next_cells)
    return unique_ratio + alpha_ratio + next_numeric_ratio


def _extract_metadata(lines: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    unnamed_index = 1
    for line in lines:
        cells = [cell for cell in _split_line(line) if cell != ""]
        if not cells:
            continue
        if len(cells) == 1:
            meta[f"note_{unnamed_index}"] = cells[0]
            unnamed_index += 1
            continue
        key = cells[0]
        value = " | ".join(cells[1:])
        meta[key] = value
    return meta


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _metadata_value(metadata: dict[str, str], *aliases: str) -> str:
    normalized = {_normalize_key(key): value for key, value in metadata.items()}
    for alias in aliases:
        value = normalized.get(_normalize_key(alias))
        if value:
            return str(value)
    return ""


def extract_report_file_metadata(path: str | Path, metadata: dict[str, str]) -> dict[str, str]:
    file_path = Path(path)
    return {
        "file_name": shorten_report_filename(file_path),
        "report_date": _metadata_value(metadata, "Rapportdato", "Report date"),
        "recording_date": _metadata_value(metadata, "Opptaksdato", "Recording date"),
        "measurement_length_m": _metadata_value(metadata, "Malingslengdem", "Målingslengde", "Measurement length m"),
        "start_county": _metadata_value(metadata, "Startposisjon: Fylke", "Start position: County"),
        "start_road": _metadata_value(metadata, "Startposisjon: Veg", "Start position: Road"),
        "start_section": _metadata_value(metadata, "Startposisjon: Strekning", "Start position: Section"),
    }


def _find_main_table(lines: list[str]) -> tuple[int, int]:
    split_lines = [_split_line(line) for line in lines]
    best: tuple[int, int, int, float] | None = None
    idx = 0
    while idx < len(split_lines) - 1:
        cells = split_lines[idx]
        col_count = len(cells)
        if col_count < 5:
            idx += 1
            continue
        next_cells = split_lines[idx + 1]
        if len(next_cells) != col_count:
            idx += 1
            continue
        header_score = _score_header(cells, next_cells)
        if header_score < 1.2:
            idx += 1
            continue
        end = idx + 1
        while end < len(split_lines):
            row = split_lines[end]
            non_empty = sum(cell != "" for cell in row)
            if len(row) == col_count:
                end += 1
                continue
            if len(row) >= max(2, col_count - 2) and non_empty >= max(2, col_count // 2):
                end += 1
                continue
            break
        length = end - idx
        score = length * col_count
        if best is None or score > best[3]:
            best = (idx, end, length, float(score))
        idx = end
    if best is None:
        raise ValueError("Could not detect a main tabular section in the TSV file.")
    return best[0], best[1]


def _build_dataframe(lines: list[str], start: int, end: int) -> pd.DataFrame:
    block = "".join(lines[start:end])
    df = pd.read_csv(io.StringIO(block), sep="\t", dtype=str)
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all").reset_index(drop=True)
    df.columns = [str(col).strip() for col in df.columns]
    return _normalize_dataframe(df)


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    for column in normalized.columns:
        series = normalized[column].astype(str).str.strip()
        series = series.replace({"": np.nan, "nan": np.nan, "None": np.nan})
        numeric_candidate = pd.to_numeric(series.str.replace(" ", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
        if numeric_candidate.notna().sum() >= max(3, int(len(series) * 0.6)):
            normalized[column] = numeric_candidate
            continue
        datetime_candidate = pd.to_datetime(series, errors="coerce", dayfirst=True)
        if datetime_candidate.notna().sum() >= max(3, int(len(series) * 0.6)):
            normalized[column] = datetime_candidate
            continue
        normalized[column] = series
    return normalized


def _find_column(columns: list[str], hints: list[str]) -> str | None:
    lowered = {col: col.lower() for col in columns}
    for hint in hints:
        for col, value in lowered.items():
            if hint in value:
                return col
    return None


def _extract_coordinates(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str | None]]:
    columns = list(df.columns)
    lat_col = _find_column(columns, COORDINATE_HINTS["lat"])
    lon_col = _find_column(columns, COORDINATE_HINTS["lon"])
    x_col = _find_column(columns, COORDINATE_HINTS["x"])
    y_col = _find_column(columns, COORDINATE_HINTS["y"])
    coord_df = pd.DataFrame(index=df.index)
    if lat_col and lon_col:
        coord_df["latitude"] = pd.to_numeric(df[lat_col], errors="coerce")
        coord_df["longitude"] = pd.to_numeric(df[lon_col], errors="coerce")
    elif x_col and y_col:
        coord_df["x"] = pd.to_numeric(df[x_col], errors="coerce")
        coord_df["y"] = pd.to_numeric(df[y_col], errors="coerce")
    distance_col = _find_column(columns, DISTANCE_HINTS)
    if distance_col:
        coord_df["distance_m"] = pd.to_numeric(df[distance_col], errors="coerce")
    date_col = _find_column(columns, DATE_HINTS)
    if date_col and pd.api.types.is_datetime64_any_dtype(df[date_col]):
        coord_df["timestamp"] = df[date_col]
    return coord_df.dropna(how="all"), {"lat": lat_col, "lon": lon_col, "x": x_col, "y": y_col}


def _detect_datetime_column(df: pd.DataFrame) -> str | None:
    for column in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            return column
    return None


def _detect_distance_column(df: pd.DataFrame) -> str | None:
    for column in df.columns:
        lower = column.lower()
        if any(hint in lower for hint in DISTANCE_HINTS) and pd.api.types.is_numeric_dtype(df[column]):
            return column
    return None


def parse_report_text(name: str | Path, content: str) -> ViaPPSReport:
    file_path = Path(name)
    lines = content.splitlines(keepends=True)
    start, end = _find_main_table(lines)
    table = _build_dataframe(lines, start, end)
    metadata_before = _extract_metadata(lines[:start])
    metadata_after = _extract_metadata(lines[end:])
    combined_metadata = dict(metadata_before)
    combined_metadata.update(metadata_after)
    coordinates, coordinate_columns = _extract_coordinates(table)
    return ViaPPSReport(
        path=file_path,
        table=table,
        metadata_before=metadata_before,
        metadata_after=metadata_after,
        coordinates=coordinates,
        coordinate_columns=coordinate_columns,
        distance_column=_detect_distance_column(table),
        datetime_column=_detect_datetime_column(table),
        table_start_line=start + 1,
        table_end_line=end,
        file_metadata=extract_report_file_metadata(file_path, combined_metadata),
        display_name=shorten_report_filename(file_path),
    )


def parse_report_bytes(name: str | Path, data: bytes) -> ViaPPSReport:
    return parse_report_text(name, data.decode("utf-8-sig", errors="ignore"))


def parse_report(path: str | Path) -> ViaPPSReport:
    file_path = Path(path)
    return parse_report_text(file_path, file_path.read_text(encoding="utf-8-sig", errors="ignore"))


def numeric_fields(report: ViaPPSReport) -> list[str]:
    return [col for col in report.table.columns if pd.api.types.is_numeric_dtype(report.table[col])]


def filter_report(report: ViaPPSReport, date_range: tuple[pd.Timestamp, pd.Timestamp] | None = None, coordinate_bounds: tuple[float, float, float, float] | None = None) -> ViaPPSReport:
    df = report.table.copy()
    if date_range and report.datetime_column:
        start, end = date_range
        df = df[df[report.datetime_column].between(start, end)]
    if coordinate_bounds and not report.coordinates.empty:
        min_x, min_y, max_x, max_y = coordinate_bounds
        if {"longitude", "latitude"}.issubset(report.coordinates.columns):
            mask = report.coordinates["longitude"].between(min_x, max_x) & report.coordinates["latitude"].between(min_y, max_y)
            df = df.loc[mask.fillna(False)]
        elif {"x", "y"}.issubset(report.coordinates.columns):
            mask = report.coordinates["x"].between(min_x, max_x) & report.coordinates["y"].between(min_y, max_y)
            df = df.loc[mask.fillna(False)]
    coordinates, coordinate_columns = _extract_coordinates(df)
    return ViaPPSReport(
        path=report.path,
        table=df.reset_index(drop=True),
        metadata_before=report.metadata_before,
        metadata_after=report.metadata_after,
        coordinates=coordinates.reset_index(drop=True),
        coordinate_columns=coordinate_columns,
        distance_column=_detect_distance_column(df),
        datetime_column=_detect_datetime_column(df),
        table_start_line=report.table_start_line,
        table_end_line=report.table_end_line,
        file_metadata=report.file_metadata,
        display_name=report.display_name,
    )
