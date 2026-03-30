from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import folium
import geopandas as gpd
from shapely.geometry import LineString, Point

from viapps_analyzer.data_loader import ViaPPSReport


def _empty_geodataframe(crs: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)


def build_geodataframe(report: ViaPPSReport, default_crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    coords = report.coordinates.copy()
    if coords.empty:
        return _empty_geodataframe(default_crs)
    if {"longitude", "latitude"}.issubset(coords.columns):
        valid = coords.dropna(subset=["longitude", "latitude"]).copy()
        if valid.empty:
            return _empty_geodataframe("EPSG:4326")
        valid["geometry"] = [Point(xy) for xy in zip(valid["longitude"], valid["latitude"])]
        return gpd.GeoDataFrame(valid, geometry="geometry", crs="EPSG:4326")
    if {"x", "y"}.issubset(coords.columns):
        valid = coords.dropna(subset=["x", "y"]).copy()
        if valid.empty:
            return _empty_geodataframe(default_crs)
        valid["geometry"] = [Point(xy) for xy in zip(valid["x"], valid["y"])]
        return gpd.GeoDataFrame(valid, geometry="geometry", crs=default_crs)
    return _empty_geodataframe(default_crs)


def build_track_lines(reports: dict[str, ViaPPSReport], default_crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    rows = []
    for label, report in reports.items():
        gdf = build_geodataframe(report, default_crs=default_crs)
        if gdf.empty:
            continue
        if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        points = [(geom.x, geom.y) for geom in gdf.geometry if geom is not None]
        if len(points) >= 2:
            rows.append({"file": label, "geometry": LineString(points)})
    if not rows:
        return _empty_geodataframe("EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def build_map(reports: dict[str, ViaPPSReport], tiles: str = "CartoDB positron", default_crs: str = "EPSG:4326", max_points: int = 12000) -> folium.Map:
    lines = build_track_lines(reports, default_crs=default_crs)
    center = [63.4, 10.4]
    if not lines.empty:
        centroid = lines.to_crs("EPSG:4326").geometry.union_all().centroid
        center = [centroid.y, centroid.x]
    fmap = folium.Map(location=center, zoom_start=7, tiles=tiles)
    palette = ["#005f73", "#0a9396", "#ee9b00", "#ae2012", "#6a4c93", "#4d908e"]
    for idx, (label, report) in enumerate(reports.items()):
        gdf = build_geodataframe(report, default_crs=default_crs)
        if gdf.empty:
            continue
        if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        sample = gdf.iloc[:max_points]
        coords = [(geom.y, geom.x) for geom in sample.geometry if geom is not None]
        if len(coords) >= 2:
            folium.PolyLine(coords, color=palette[idx % len(palette)], weight=4, opacity=0.9, tooltip=label).add_to(fmap)
        elif len(coords) == 1:
            folium.CircleMarker(coords[0], radius=4, color=palette[idx % len(palette)], fill=True, tooltip=label).add_to(fmap)
    return fmap


def export_tracks(reports: dict[str, ViaPPSReport], fmt: str, default_crs: str = "EPSG:4326") -> tuple[bytes, str, str]:
    lines = build_track_lines(reports, default_crs=default_crs)
    if lines.empty:
        raise ValueError("No track geometry could be constructed from the selected files.")
    fmt = fmt.lower()
    if fmt == "geojson":
        return lines.to_json().encode("utf-8"), "tracks.geojson", "application/geo+json"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        if fmt == "gpkg":
            file_path = tmp_path / "tracks.gpkg"
            lines.to_file(file_path, driver="GPKG")
            return file_path.read_bytes(), "tracks.gpkg", "application/geopackage+sqlite3"
        if fmt == "shp":
            shp_path = tmp_path / "tracks.shp"
            lines.to_file(shp_path, driver="ESRI Shapefile")
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for part in tmp_path.glob("tracks.*"):
                    zf.write(part, arcname=part.name)
            return buffer.getvalue(), "tracks_shapefile.zip", "application/zip"
    raise ValueError(f"Unsupported geospatial export format: {fmt}")
