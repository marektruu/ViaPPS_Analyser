from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from viapps_analyzer.analyzer import (
    align_reports,
    apply_linear_reference_window,
    build_summary_report,
    compute_linear_reference,
    correlation_summary,
    export_dataframe_csv,
    export_dataframe_excel,
    file_metadata_table,
    metadata_table,
)
from viapps_analyzer.config import AppConfig, load_config, save_config
from viapps_analyzer.data_loader import (
    REPORT_METADATA_FIELDS,
    ViaPPSReport,
    filter_report,
    list_tsv_files,
    numeric_fields,
    parse_report,
)
from viapps_analyzer.map_utils import build_map, export_tracks
from viapps_analyzer.plotting import build_comparison_figure, build_individual_figure, export_plot_html, export_plot_image
from viapps_analyzer.translations import (
    SUPPORTED_LANGUAGES,
    dataframe_to_translations,
    ensure_translation_terms,
    load_translations,
    save_translations,
    tr,
    translate_field_name,
    translations_to_dataframe,
)


st.set_page_config(page_title="ViaPPS Analyzer +", layout="wide")

METHOD_GROUPS = ["CEN 13036", "Bunn", "Krum", "Metode", "Regresjon", "Snor"]
GENERAL_GROUP_KEY = "general"
FIELD_TRANSLATION_TEMPLATES = {
    "Areal [cm^2]": {"no": "Areal [cm^2]", "en": "Area [cm^2]", "et": "Roopa pindala [cm^2]"},
    "Hyre spordybde [mm]": {"no": "Hyre spordybde [mm]", "en": "Rut depth right [mm]", "et": "Roopa sügavus paremal [mm]"},
    "Hyre sporposisjon [cm]": {"no": "Hyre sporposisjon [cm]", "en": "Rut position right [cm]", "et": "Roopa asukoht paremal [cm]"},
    "Max spordybde [mm]": {"no": "Max spordybde [mm]", "en": "Rut depth max [mm]", "et": "Roopa sügavus max [mm]"},
    "Max sporposisjon [cm]": {"no": "Max sporposisjon [cm]", "en": "Rut position max [cm]", "et": "Roopa asukoht max [cm]"},
    "Sporbredde [cm]": {"no": "Sporbredde [cm]", "en": "Rut width [cm]", "et": "Roopa laius [cm]"},
    "Tverrfall [%]": {"no": "Tverrfall [%]", "en": "Tverrfall [%]", "et": "Põikkalle [%]"},
    "Venstre spordybde [mm]": {"no": "Venstre spordybde [mm]", "en": "Rut depth left [mm]", "et": "Roopa sügavus vasakul [mm]"},
    "Venstre sporposisjon [cm]": {"no": "Venstre sporposisjon [cm]", "en": "Rut position left [cm]", "et": "Roopa asukoht vasakul [cm]"},
}


@st.cache_data(show_spinner=False)
def cached_file_list(directory: str) -> list[str]:
    return [str(path) for path in list_tsv_files(directory)]


@st.cache_data(show_spinner=False)
def cached_report(path: str) -> ViaPPSReport:
    return parse_report(path)


def _localized_fields(translations: dict, language: str, fields: list[str]) -> dict[str, str]:
    return {field: translate_field_name(translations, language, field) for field in fields}


def _field_selector_label(field: str, field_map: dict[str, str]) -> str:
    translated = field_map.get(field, field)
    return field if translated == field else f"{translated} ({field})"


def _field_group_for(field: str) -> str:
    for group in METHOD_GROUPS:
        prefix = f"{group} "
        if field.startswith(prefix):
            return group
    return GENERAL_GROUP_KEY


def _group_label(translations: dict, language: str, group: str) -> str:
    if group == GENERAL_GROUP_KEY:
        return tr(translations, language, "general_group")
    return group


def _group_fields(fields: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {GENERAL_GROUP_KEY: []}
    for group in METHOD_GROUPS:
        grouped[group] = []
    for field in fields:
        grouped.setdefault(_field_group_for(field), []).append(field)
    return {group: sorted(items) for group, items in grouped.items() if items}


def _localize_summary_dataframe(df: pd.DataFrame, translations: dict, language: str) -> pd.DataFrame:
    if df.empty:
        return df
    localized = df.copy()
    rename_map = {column: tr(translations, language, column) for column in localized.columns if column in translations.get("ui", {})}
    localized = localized.rename(columns=rename_map)
    field_column = tr(translations, language, "field")
    if field_column in localized.columns:
        localized[field_column] = localized[field_column].map(lambda value: translate_field_name(translations, language, str(value)))
    return localized


def _build_file_label_map(paths: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    counts: dict[str, int] = {}
    display_names = {path: cached_report(path).display_name for path in paths}
    for display_name in display_names.values():
        counts[display_name] = counts.get(display_name, 0) + 1
    for path in paths:
        display_name = display_names[path]
        if counts[display_name] > 1:
            display_name = f"{display_name} ({Path(path).name})"
        labels[display_name] = path
    return labels


def _persist_report_directory(config: AppConfig, report_directory: str) -> AppConfig:
    updated = AppConfig(
        report_directory=report_directory,
        default_language=config.default_language,
        default_interval_m=config.default_interval_m,
        available_intervals_m=config.available_intervals_m,
        map_tiles=config.map_tiles,
        chart_template=config.chart_template,
        default_crs=config.default_crs,
        max_map_points=config.max_map_points,
        default_selected_fields=config.default_selected_fields,
    )
    save_config(updated)
    return updated


def _render_settings(config: AppConfig, selected_fields: list[str], translations: dict, language: str) -> AppConfig:
    with st.sidebar.expander(tr(translations, language, "settings"), expanded=False):
        default_interval = st.selectbox(
            tr(translations, language, "averaging_interval"),
            options=config.available_intervals_m,
            index=max(0, config.available_intervals_m.index(config.default_interval_m)) if config.default_interval_m in config.available_intervals_m else 0,
        )
        map_tiles = st.text_input("Map tiles", value=config.map_tiles)
        chart_template = st.text_input("Plotly template", value=config.chart_template)
        default_crs = st.text_input("Fallback CRS", value=config.default_crs)
        max_map_points = st.number_input("Max map points", min_value=1000, max_value=100000, value=config.max_map_points, step=1000)
        updated = AppConfig(
            report_directory=config.report_directory,
            default_language=config.default_language,
            default_interval_m=int(default_interval),
            available_intervals_m=config.available_intervals_m,
            map_tiles=map_tiles,
            chart_template=chart_template,
            default_crs=default_crs,
            max_map_points=int(max_map_points),
            default_selected_fields=selected_fields,
        )
        if st.button(tr(translations, language, "save_settings")):
            save_config(updated)
            st.success(tr(translations, language, "configuration_saved"))
        return updated


def _render_translation_editor(translations: dict, language: str) -> dict:
    st.subheader(tr(translations, language, "translation_editor"))
    edited = st.data_editor(translations_to_dataframe(translations), num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button(tr(translations, language, "save_translations")):
        payload = dataframe_to_translations(edited)
        save_translations(payload)
        st.success(tr(translations, language, "configuration_saved"))
        return payload
    return translations


def _render_metadata(reports: dict[str, ViaPPSReport], translations: dict, language: str) -> None:
    st.subheader(tr(translations, language, "metadata"))
    file_meta = file_metadata_table(reports)
    if not file_meta.empty:
        localized_columns = {key: tr(translations, language, key) for key in REPORT_METADATA_FIELDS}
        st.dataframe(file_meta.rename(columns=localized_columns), use_container_width=True, hide_index=True)
    for label, report in reports.items():
        with st.expander(f"{tr(translations, language, 'raw_metadata')} [{label}]", expanded=False):
            meta = metadata_table(report)
            meta["field"] = meta["field"].map(lambda item: translate_field_name(translations, language, str(item)))
            meta = meta.rename(columns={"field": tr(translations, language, "field"), "value": tr(translations, language, "value")})
            st.dataframe(meta, use_container_width=True, hide_index=True)


def _render_preview(reports: dict[str, ViaPPSReport], translations: dict, language: str) -> None:
    st.subheader(tr(translations, language, "main_table_preview"))
    selected = st.selectbox(tr(translations, language, "preview_file"), options=list(reports.keys()))
    preview = reports[selected].table.head(50).copy()
    preview = preview.rename(columns={column: _field_selector_label(column, _localized_fields(translations, language, list(preview.columns))) for column in preview.columns})
    st.dataframe(preview, use_container_width=True)


def _render_linear_reference_controls(reports: dict[str, ViaPPSReport], translations: dict, language: str) -> dict[str, dict[str, float | str | None]]:
    settings: dict[str, dict[str, float | str | None]] = {}
    with st.expander(tr(translations, language, "linear_reference"), expanded=False):
        for label in reports:
            st.markdown(f"**{label}**")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                start_meter = st.number_input(
                    f"{tr(translations, language, 'start_meter')} [{label}]",
                    value=1.0,
                    step=1.0,
                    key=f"start_meter::{label}",
                )
            with col2:
                direction_option = st.selectbox(
                    f"{tr(translations, language, 'direction')} [{label}]",
                    options=[("ascending", tr(translations, language, "ascending")), ("descending", tr(translations, language, "descending"))],
                    format_func=lambda item: item[1],
                    key=f"direction::{label}",
                )
            with col3:
                analysis_begin_m = st.number_input(
                    f"{tr(translations, language, 'analysis_begin_m')} [{label}]",
                    value=0.0,
                    step=1.0,
                    key=f"analysis_begin::{label}",
                )
            with col4:
                analysis_end_m = st.number_input(
                    f"{tr(translations, language, 'analysis_end_m')} [{label}]",
                    value=0.0,
                    step=1.0,
                    key=f"analysis_end::{label}",
                )
            settings[label] = {
                "start_meter": float(start_meter),
                "direction": direction_option[0],
                "analysis_begin_m": None if float(analysis_begin_m) <= 0 else float(analysis_begin_m),
                "analysis_end_m": None if float(analysis_end_m) <= 0 else float(analysis_end_m),
            }
    return settings


def _render_exports(reports: dict[str, ViaPPSReport], aligned: pd.DataFrame, summary: pd.DataFrame, correlation: pd.DataFrame, figure, config: AppConfig, translations: dict, language: str) -> None:
    st.subheader(tr(translations, language, "exports"))
    st.download_button(tr(translations, language, "comparison_csv"), export_dataframe_csv(aligned), "comparison.csv", "text/csv", disabled=aligned.empty)
    excel_bytes = export_dataframe_excel(
        {
            "comparison": aligned if not aligned.empty else pd.DataFrame(),
            "summary": summary if not summary.empty else pd.DataFrame(),
            "correlation": correlation if not correlation.empty else pd.DataFrame(),
        }
    )
    st.download_button(tr(translations, language, "comparison_excel"), excel_bytes, "analysis.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button(tr(translations, language, "chart_html"), export_plot_html(figure), "chart.html", "text/html")
    image_format = st.selectbox(tr(translations, language, "chart_image_format"), ["png", "pdf"], index=0)
    if st.button(tr(translations, language, "prepare_chart_image")):
        try:
            image_bytes = export_plot_image(figure, image_format)
            st.download_button(tr(translations, language, "download_chart_image"), image_bytes, f"chart.{image_format}", f"image/{image_format}")
        except Exception as exc:
            st.warning(f"{tr(translations, language, 'chart_export_note')} Details: {exc}")
    geo_format = st.selectbox(tr(translations, language, "track_export_format"), ["geojson", "gpkg", "shp"], index=0)
    if st.button(tr(translations, language, "prepare_track_export")):
        try:
            data, name, mime = export_tracks(reports, geo_format, default_crs=config.default_crs)
            st.download_button(tr(translations, language, "download_track_export"), data, name, mime)
        except Exception as exc:
            st.warning(str(exc))


def _apply_field_translation_templates(translations: dict) -> tuple[dict, bool]:
    updated = {
        section: {key: dict(values) for key, values in entries.items()}
        for section, entries in translations.items()
    }
    updated.setdefault("fields", {})
    changed = False
    for suffix, localized in FIELD_TRANSLATION_TEMPLATES.items():
        current = updated["fields"].get(suffix)
        if current != localized:
            updated["fields"][suffix] = dict(localized)
            changed = True
        for group in METHOD_GROUPS:
            candidate = f"{group} {suffix}"
            grouped_localized = {
                "no": f"{group} {localized['no']}",
                "en": f"{group} {localized['en']}",
                "et": f"{group} {localized['et']}",
            }
            current = updated["fields"].get(candidate)
            if current != grouped_localized:
                updated["fields"][candidate] = grouped_localized
                changed = True
    return updated, changed


def _ensure_report_header_translations(translations: dict, reports: dict[str, ViaPPSReport]) -> dict:
    header_terms = [column for report in reports.values() for column in report.table.columns]
    meta_terms = [label for values in REPORT_METADATA_FIELDS.values() for label in values]
    updated, changed = ensure_translation_terms(translations, header_terms + meta_terms, section="fields")
    updated, templated = _apply_field_translation_templates(updated)
    if changed or templated:
        save_translations(updated)
    return updated


def run_app() -> None:
    config = load_config()
    translations = load_translations()
    translations, initial_templates_changed = _apply_field_translation_templates(translations)
    if initial_templates_changed:
        save_translations(translations)

    if "report_directory_input" not in st.session_state:
        st.session_state.report_directory_input = config.report_directory
    if "files_loaded" not in st.session_state:
        st.session_state.files_loaded = False
    if "file_paths" not in st.session_state:
        st.session_state.file_paths = []

    report_directory = st.sidebar.text_input(
        tr(translations, config.default_language, "report_directory"),
        value=st.session_state.report_directory_input,
        key="report_directory_input",
    )
    if st.sidebar.button(tr(translations, config.default_language, "refresh_files")):
        cached_file_list.clear()
        cached_report.clear()
        st.session_state.file_paths = cached_file_list(report_directory)
        st.session_state.files_loaded = True
        config = _persist_report_directory(config, report_directory)

    language = st.sidebar.selectbox(
        tr(translations, config.default_language, "language"),
        options=SUPPORTED_LANGUAGES,
        index=SUPPORTED_LANGUAGES.index(config.default_language) if config.default_language in SUPPORTED_LANGUAGES else 1,
    )
    st.title(tr(translations, language, "app_title"))

    if not st.session_state.files_loaded:
        st.info(tr(translations, language, "refresh_to_load_files"))
        _render_translation_editor(translations, language)
        return

    files = list(st.session_state.file_paths)
    if not files:
        st.warning(f"{tr(translations, language, 'no_files_found')} {report_directory}")
        _render_translation_editor(translations, language)
        return

    file_labels = _build_file_label_map(files)
    selected_labels = st.sidebar.multiselect(
        tr(translations, language, "selected_files"),
        options=list(file_labels.keys()),
        default=list(file_labels.keys())[:2],
    )
    if not selected_labels:
        st.info(tr(translations, language, "select_file_prompt"))
        _render_translation_editor(translations, language)
        return

    reports = {label: cached_report(file_labels[label]) for label in selected_labels}
    translations = _ensure_report_header_translations(translations, reports)

    all_numeric_fields = sorted({field for report in reports.values() for field in numeric_fields(report)})
    grouped_fields = _group_fields(all_numeric_fields)
    field_map = _localized_fields(translations, language, all_numeric_fields)
    selected_group_options = [group for group, items in grouped_fields.items() if items]
    default_groups = sorted({_field_group_for(field) for field in config.default_selected_fields if field in all_numeric_fields})
    selected_groups = st.multiselect(
        tr(translations, language, "field_groups"),
        options=selected_group_options,
        default=default_groups or selected_group_options[:1],
        format_func=lambda group: _group_label(translations, language, group),
    )
    visible_fields = [field for group in selected_groups for field in grouped_fields.get(group, [])]
    label_lookup = {_field_selector_label(field, field_map): field for field in visible_fields}
    default_field_keys = [field for field in config.default_selected_fields if field in visible_fields]
    default_field_labels = [_field_selector_label(field, field_map) for field in default_field_keys]
    selected_field_labels = st.multiselect(
        tr(translations, language, "fields"),
        options=list(label_lookup.keys()),
        default=default_field_labels or list(label_lookup.keys())[: min(3, len(label_lookup))],
    )
    selected_fields = [label_lookup[label] for label in selected_field_labels]

    config = _render_settings(config, selected_fields, translations, language)
    linear_reference_settings = _render_linear_reference_controls(reports, translations, language)

    col1, col2, col3 = st.columns(3)
    with col1:
        interval_m = st.selectbox(
            tr(translations, language, "averaging_interval"),
            options=config.available_intervals_m,
            index=max(0, config.available_intervals_m.index(config.default_interval_m)) if config.default_interval_m in config.available_intervals_m else 0,
        )
    with col2:
        comparison_mode_ui = st.selectbox(
            tr(translations, language, "comparison_mode"),
            options=[
                (tr(translations, language, "overlay"), "overlay"),
                (tr(translations, language, "side_by_side"), "side_by_side"),
                (tr(translations, language, "difference_plot"), "difference"),
            ],
            format_func=lambda item: item[0],
        )
        comparison_mode = comparison_mode_ui[1]
    with col3:
        show_preview = st.checkbox(tr(translations, language, "main_table_preview"), value=False)

    with st.expander(tr(translations, language, "filters"), expanded=False):
        date_range = None
        coordinate_bounds = None
        first_report = next(iter(reports.values()))
        if first_report.datetime_column:
            min_date = pd.to_datetime(first_report.table[first_report.datetime_column].min()).date()
            max_date = pd.to_datetime(first_report.table[first_report.datetime_column].max()).date()
            picked = st.date_input(tr(translations, language, "date_filter"), value=(min_date, max_date))
            if not isinstance(picked, str) and len(picked) == 2:
                date_range = (pd.Timestamp(picked[0]), pd.Timestamp(picked[1]))
        st.caption(tr(translations, language, "coordinate_filter"))
        bounds_text = st.text_input("min_x,min_y,max_x,max_y", value="")
        if bounds_text.strip():
            try:
                bounds = [float(item.strip()) for item in bounds_text.split(",")]
                if len(bounds) == 4:
                    coordinate_bounds = tuple(bounds)
            except ValueError:
                st.warning(tr(translations, language, "invalid_coordinate_bounds"))

    filtered_reports = {label: filter_report(report, date_range=date_range, coordinate_bounds=coordinate_bounds) for label, report in reports.items()}
    analysis_reports = {label: apply_linear_reference_window(report, linear_reference_settings.get(label)) for label, report in filtered_reports.items()}
    aligned = align_reports(analysis_reports, interval_m, selected_fields, linear_reference_settings)
    summary = build_summary_report(analysis_reports, selected_fields)
    correlation = correlation_summary(aligned, selected_fields, list(analysis_reports.keys())) if len(analysis_reports) >= 2 else pd.DataFrame()
    translated_fields = {field: field_map.get(field, field) for field in selected_fields}

    if selected_fields:
        figure = build_comparison_figure(
            analysis_reports,
            aligned,
            selected_fields,
            comparison_mode,
            config.chart_template,
            translated_fields=translated_fields,
            x_axis_title=f"{tr(translations, language, 'road_meter')} (m)",
            y_axis_title=tr(translations, language, "value"),
            legend_title=tr(translations, language, "series"),
        )
        st.plotly_chart(figure, use_container_width=True)
        if comparison_mode == "side_by_side":
            columns = st.columns(len(analysis_reports))
            for column, (label, report) in zip(columns, analysis_reports.items()):
                with column:
                    st.markdown(f"**{label}**")
                    axis = report.table["linear_reference_m"] if "linear_reference_m" in report.table.columns else compute_linear_reference(report, float(linear_reference_settings[label]["start_meter"]), str(linear_reference_settings[label]["direction"]))
                    st.plotly_chart(
                        build_individual_figure(
                            report,
                            selected_fields,
                            config.chart_template,
                            translated_fields=translated_fields,
                            x_values=axis,
                            x_axis_title=f"{tr(translations, language, 'road_meter')} (m)",
                            y_axis_title=tr(translations, language, "value"),
                        ),
                        use_container_width=True,
                    )
    else:
        st.info(tr(translations, language, "select_fields_prompt"))
        figure = build_comparison_figure(analysis_reports, aligned, [], "overlay", config.chart_template)

    st.subheader(tr(translations, language, "summary"))
    st.dataframe(_localize_summary_dataframe(summary, translations, language), use_container_width=True, hide_index=True)

    if len(analysis_reports) >= 2 and not correlation.empty:
        st.subheader(tr(translations, language, "correlation_summary"))
        st.dataframe(_localize_summary_dataframe(correlation, translations, language), use_container_width=True, hide_index=True)

    _render_metadata(analysis_reports, translations, language)

    st.subheader(tr(translations, language, "map"))
    try:
        fmap = build_map(analysis_reports, tiles=config.map_tiles, default_crs=config.default_crs, max_points=config.max_map_points)
        st_folium(fmap, use_container_width=True, height=520)
    except Exception as exc:
        st.warning(f"{tr(translations, language, 'map_render_failed')}: {exc}")

    if show_preview:
        _render_preview(analysis_reports, translations, language)

    _render_exports(analysis_reports, aligned, summary, correlation, figure, config, translations, language)
    updated_translations = _render_translation_editor(translations, language)
    if updated_translations is not translations:
        st.rerun()

