# ViaPPS Analyzer

ViaPPS Analyzer is a Streamlit application for loading, comparing, summarizing, and mapping ViaPPS Desktop report files stored as tab-separated text files. It supports two complementary workflows:

- `Comparison`: inspect one or more ViaPPS reports directly in the Streamlit UI
- `Overview`: generate a lightweight dataset bundle from many reports and review it later in the Streamlit UI

## Features

- Multi-file TSV/TXT selection from `D:\ViaPPS_RBS\REPORT_DATA` by default
- Automatic detection of the main tabular block and surrounding metadata
- Translation-aware UI, metadata, summary tables, and chart labels in Norwegian, English, and Estonian
- Numeric field selection for cross-file comparison, with selected fields saved in settings
- Distance-based averaging and resampling at `1m`, `5m`, `20m`, or `100m`
- User-defined start meter and measurement direction per selected file for road linear reference alignment
- Pairwise correlation summary per selected field after averaging and alignment
- Overlay, side-by-side, and difference plotting with Plotly
- Statistical summaries for selected fields
- Date and coordinate filtering
- Interactive Folium map rendering for detected tracks
- Export of comparison data to CSV and Excel
- Export of charts to HTML and, when supported by the environment, PNG/PDF
- Export of tracks to GeoJSON, GeoPackage, or zipped Shapefile
- Overview workflow for loading exported parquet/CSV datasets plus optional GeoJSON track lines
- Built-in ViaPPS Exporter bundle download for bulk dataset generation outside the Streamlit app
- Parquet and GeoJSON overview track outputs use the same 160-point downsampling logic
- Built-in translation management through the UI

## Project Structure

```text
app.py
exporter_app.py
config.json
translations.json
requirements.txt
viapps_analyzer/
  analyzer.py
  config.py
  data_loader.py
  exporter_app.py
  exporter_core.py
  map_utils.py
  plotting.py
  translations.py
  ui.py
```

## Installation

1. Create and activate a Python virtual environment.
2. Install the dependencies:

```bash
pip install -r requirements.txt
```

3. Start the Streamlit application:

```bash
streamlit run app.py
```

## Usage

### Comparison workflow

1. Open the app in your browser.
2. Confirm or update the report directory in the sidebar settings.
3. Select one or more ViaPPS report files.
4. Choose numeric fields to compare.
5. Set start meter and direction for each selected file when needed.
6. Select the averaging interval and comparison mode.
7. Optionally apply date or coordinate filters.
8. Review the chart, summary table, correlation table, metadata, and map.
9. Use the export section for CSV, Excel, chart, or geospatial output.

### Overview workflow

1. Open the app and switch the sidebar workflow to `Overview`.
2. Set the exporter input/output folders and choose the field groups or individual fields to summarize.
3. Download the exporter config JSON and the ViaPPS Exporter bundle ZIP.
4. Run the exporter bundle on a machine that has access to the source report folder.
5. Load the generated `viapps_overview_dataset.parquet` or `.csv` back into the overview mode.
6. Optionally load `viapps_overview_dataset.geojson` to display track lines on the map.

The overview dataset includes:

- Per-file identifiers such as display name, source file, and source path
- Table size and detected table line range
- Optional metadata fields copied from the original report
- Start/end and min/max latitude/longitude bounds
- `track_coordinates_json` with a compact 160-point track preview for map rendering without GeoJSON
- Per-selected-field summary columns using the `field__count`, `field__mean`, `field__min`, and `field__max` naming pattern

## ViaPPS Exporter

The exporter is a small desktop launcher (`exporter_app.py`) bundled directly from the Streamlit app. Its purpose is to scan a folder of ViaPPS TXT/TSV reports and write overview outputs without opening the full Analyzer UI on that machine.

Typical exporter flow:

1. Download the config JSON and bundle ZIP from the `Overview` workflow.
2. Extract the ZIP on the target machine.
3. Install dependencies with `pip install -r requirements.txt`.
4. Start the exporter with `python exporter_app.py`.
5. Load the config, confirm folders and output formats, then run the export.

The exporter looks for the most recent `viapps_export_*.json` config in the launcher folder first and then in the user's `Downloads` folder.

## Data Parsing Notes

- The parser scans the file for the most likely main table by looking for a strong header row followed by a consistent tabular block.
- Lines before and after that table are treated as metadata.
- Numeric and date-like columns are converted automatically where possible.
- Coordinate detection supports common latitude/longitude names and generic `x/y` or easting/northing naming patterns.
- If the source distance column contains relative row meters like `1, 2, 3`, use the linear reference controls to map them to the true road meter chainage.

## Updating Translations

The app stores translations in `translations.json`. You can update them directly in the built-in translation editor and save the changes without restarting the app.

Translation file layout:

```json
{
  "ui": {
    "app_title": {
      "no": "ViaPPS Analyzer",
      "en": "ViaPPS Analyzer",
      "et": "ViaPPS Analyzer"
    }
  },
  "fields": {
    "Avstand": {
      "no": "Avstand",
      "en": "Distance",
      "et": "Vahemaa"
    }
  }
}
```

Sample ViaPPS-related field entries included by default:

- `Avstand` -> `Distance` / `Vahemaa`
- `Breddegrad` -> `Latitude` / `Laiuskraad`
- `Lengdegrad` -> `Longitude` / `Pikkuskraad`
- `Hastighet` -> `Speed` / `Kiirus`
- `Måling` -> `Measurement` / `Mõõtmine`

## Export Notes

- Chart PNG/PDF export depends on `kaleido`.
- GeoPackage and Shapefile export depend on a working GeoPandas driver stack.
- Shapefile export is delivered as a zip archive because it consists of multiple files.
- Overview parquet export depends on `pyarrow`.
- Overview GeoJSON is optional; the overview table can still render a simplified map from `track_coordinates_json`.

## Assumptions and Extension Points

- The application assumes the main measurement table is the largest coherent tabular block in each file.
- Pairwise correlation is calculated after averaging and aligning selected files by the configured road meter bins.
- If your ViaPPS export uses custom field names, add them to `translations.json` for better display labels.
- If projected coordinates are used, update `config.json` or the in-app settings with the correct CRS string.
- The parser is intentionally modular so format-specific tweaks can be added in `viapps_analyzer/data_loader.py`.
