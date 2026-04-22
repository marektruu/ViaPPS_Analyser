from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from viapps_analyzer.data_loader import REPORT_METADATA_FIELDS, ViaPPSReport, list_tsv_files, parse_report
from viapps_analyzer.map_utils import build_geodataframe


CONFIG_PREFIX = "viapps_export_"
CONFIG_GLOB = f"{CONFIG_PREFIX}*.json"
DATASET_BASENAME = "viapps_overview_dataset"


@dataclass
class ExporterConfig:
    input_directory: str = ""
    output_directory: str = ""
    config_directory: str = ""
    selected_fields: list[str] = field(default_factory=list)
    selected_field_groups: list[str] = field(default_factory=list)
    export_formats: list[str] = field(default_factory=lambda: ["parquet"])
    default_crs: str = "EPSG:4326"
    recursive: bool = False
    include_metadata: bool = True
    created_at: str = ""
    config_version: int = 1


@dataclass
class ExportSummary:
    processed_files: int
    total_files: int
    failed_files: list[str]
    output_files: dict[str, str]
    dataset: pd.DataFrame


ProgressCallback = Callable[[int, int, str], None]


def timestamped_config_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    return f"{CONFIG_PREFIX}{stamp}.json"


def default_bundle_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    return f"viapps_exporter_bundle_{stamp}.zip"


def config_to_json_bytes(config: ExporterConfig) -> bytes:
    payload = asdict(config)
    if not payload.get("created_at"):
        payload["created_at"] = datetime.now().isoformat(timespec="seconds")
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def load_exporter_config(path: str | Path) -> ExporterConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    data = {**ExporterConfig().__dict__, **payload}
    data["selected_fields"] = list(data.get("selected_fields", []))
    data["selected_field_groups"] = list(data.get("selected_field_groups", []))
    data["export_formats"] = list(data.get("export_formats", [])) or ["parquet"]
    return ExporterConfig(**data)


def find_latest_config(directory: str | Path | Iterable[str | Path]) -> Path | None:
    directories = directory if isinstance(directory, Iterable) and not isinstance(directory, (str, Path)) else [directory]
    matches: list[Path] = []
    for item in directories:
        path = Path(item)
        if not path.exists():
            continue
        matches.extend(path.glob(CONFIG_GLOB))
    matches = sorted(matches, key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def estimate_directory_workload(directory: str | Path, recursive: bool = False) -> tuple[int, int]:
    files = list_tsv_files(directory, recursive=recursive)
    total_bytes = sum(path.stat().st_size for path in files if path.exists())
    return len(files), int(total_bytes)


def export_overview_dataset(config: ExporterConfig, progress_callback: ProgressCallback | None = None) -> ExportSummary:
    files = list_tsv_files(config.input_directory, recursive=config.recursive)
    rows: list[dict[str, object]] = []
    geometries: list[dict[str, object]] = []
    failed_files: list[str] = []

    total_files = len(files)
    if progress_callback:
        progress_callback(0, total_files, "Scanning files")

    for index, path in enumerate(files, start=1):
        if progress_callback:
            progress_callback(index - 1, total_files, f"Parsing {path.name}")
        try:
            report = parse_report(path)
            rows.append(_report_to_row(report, config.selected_fields, config.default_crs, include_metadata=config.include_metadata))
            geometry_row = _report_to_geometry_row(report, config.default_crs)
            if geometry_row is not None:
                geometries.append(geometry_row)
        except Exception as exc:
            failed_files.append(f"{path.name}: {exc}")
        if progress_callback:
            progress_callback(index, total_files, f"Processed {path.name}")

    dataset = pd.DataFrame(rows).sort_values("display_name").reset_index(drop=True) if rows else pd.DataFrame()
    output_files = _write_output_files(dataset, geometries, config)
    return ExportSummary(
        processed_files=len(rows),
        total_files=total_files,
        failed_files=failed_files,
        output_files=output_files,
        dataset=dataset,
    )


def _report_to_row(report: ViaPPSReport, selected_fields: list[str], default_crs: str, include_metadata: bool = True) -> dict[str, object]:
    row: dict[str, object] = {
        "display_name": report.display_name or report.path.stem,
        "file_name": report.path.name,
        "source_path": str(report.path),
        "row_count": int(len(report.table)),
        "table_start_line": int(report.table_start_line),
        "table_end_line": int(report.table_end_line),
    }
    if include_metadata:
        for key in REPORT_METADATA_FIELDS:
            row[key] = report.file_metadata.get(key, "")

    lat_lon = _report_lat_lon_bounds(report, default_crs)
    row.update(lat_lon)
    row["track_coordinates_json"] = _report_track_coordinates_json(report, default_crs)

    for field in selected_fields:
        if field not in report.table.columns:
            row[f"{field}__count"] = 0
            row[f"{field}__mean"] = pd.NA
            row[f"{field}__min"] = pd.NA
            row[f"{field}__max"] = pd.NA
            continue
        series = pd.to_numeric(report.table[field], errors="coerce")
        row[f"{field}__count"] = int(series.notna().sum())
        row[f"{field}__mean"] = float(series.mean()) if series.notna().any() else pd.NA
        row[f"{field}__min"] = float(series.min()) if series.notna().any() else pd.NA
        row[f"{field}__max"] = float(series.max()) if series.notna().any() else pd.NA
    return row


def _report_lat_lon_bounds(report: ViaPPSReport, default_crs: str) -> dict[str, object]:
    gdf = build_geodataframe(report, default_crs=default_crs)
    if gdf.empty:
        return {
            "start_latitude": pd.NA,
            "start_longitude": pd.NA,
            "end_latitude": pd.NA,
            "end_longitude": pd.NA,
            "min_latitude": pd.NA,
            "min_longitude": pd.NA,
            "max_latitude": pd.NA,
            "max_longitude": pd.NA,
        }
    if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    coords = [(geom.y, geom.x) for geom in gdf.geometry if geom is not None]
    if not coords:
        return {
            "start_latitude": pd.NA,
            "start_longitude": pd.NA,
            "end_latitude": pd.NA,
            "end_longitude": pd.NA,
            "min_latitude": pd.NA,
            "min_longitude": pd.NA,
            "max_latitude": pd.NA,
            "max_longitude": pd.NA,
        }
    lats = [item[0] for item in coords]
    lons = [item[1] for item in coords]
    return {
        "start_latitude": coords[0][0],
        "start_longitude": coords[0][1],
        "end_latitude": coords[-1][0],
        "end_longitude": coords[-1][1],
        "min_latitude": min(lats),
        "min_longitude": min(lons),
        "max_latitude": max(lats),
        "max_longitude": max(lons),
    }


def _report_to_geometry_row(report: ViaPPSReport, default_crs: str) -> dict[str, object] | None:
    gdf = build_geodataframe(report, default_crs=default_crs)
    if gdf.empty:
        return None
    if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    points = [(geom.x, geom.y) for geom in gdf.geometry if geom is not None]
    points = _downsample_points(points, max_points=160)
    if len(points) < 2:
        return None
    return {"display_name": report.display_name or report.path.stem, "file_name": report.path.name, "geometry": LineString(points)}


def _report_track_coordinates_json(report: ViaPPSReport, default_crs: str) -> str:
    gdf = build_geodataframe(report, default_crs=default_crs)
    if gdf.empty:
        return ""
    if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    points = [(geom.y, geom.x) for geom in gdf.geometry if geom is not None]
    points = _downsample_points(points, max_points=160)
    if len(points) < 2:
        return ""
    return json.dumps(points, ensure_ascii=False, separators=(",", ":"))


def _downsample_points(points: list[tuple[float, float]], max_points: int = 120) -> list[tuple[float, float]]:
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / max(1, max_points - 1)
    sampled = [points[min(len(points) - 1, int(round(index * step)))] for index in range(max_points)]
    deduped: list[tuple[float, float]] = []
    for point in sampled:
        if not deduped or point != deduped[-1]:
            deduped.append(point)
    return deduped if len(deduped) >= 2 else points[:2]


def _write_output_files(dataset: pd.DataFrame, geometries: list[dict[str, object]], config: ExporterConfig) -> dict[str, str]:
    output_dir = Path(config.output_directory or config.input_directory or ".")
    output_dir.mkdir(parents=True, exist_ok=True)
    formats = {fmt.lower() for fmt in config.export_formats}
    output_files: dict[str, str] = {}

    if "parquet" in formats:
        parquet_path = output_dir / f"{DATASET_BASENAME}.parquet"
        dataset.to_parquet(parquet_path, index=False)
        output_files["parquet"] = str(parquet_path)

    if "csv" in formats:
        csv_path = output_dir / f"{DATASET_BASENAME}.csv"
        dataset.to_csv(csv_path, index=False, encoding="utf-8")
        output_files["csv"] = str(csv_path)

    if "geojson" in formats and geometries:
        geojson_path = output_dir / f"{DATASET_BASENAME}.geojson"
        gdf = gpd.GeoDataFrame(geometries, geometry="geometry", crs="EPSG:4326")
        geojson_path.write_text(gdf.to_json(), encoding="utf-8")
        output_files["geojson"] = str(geojson_path)

    return output_files
