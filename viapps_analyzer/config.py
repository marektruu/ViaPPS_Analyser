from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_DIR = Path(r"D:\ViaPPS_RBS\REPORT_DATA")
CONFIG_PATH = BASE_DIR / "config.json"


@dataclass
class AppConfig:
    report_directory: str
    default_language: str
    default_interval_m: int
    available_intervals_m: list[int]
    map_tiles: str
    chart_template: str
    default_crs: str
    max_map_points: int
    default_selected_fields: list[str] = field(default_factory=list)


DEFAULT_CONFIG = AppConfig(
    report_directory=str(DEFAULT_REPORT_DIR),
    default_language="en",
    default_interval_m=20,
    available_intervals_m=[1, 5, 20, 100],
    map_tiles="CartoDB positron",
    chart_template="plotly_white",
    default_crs="EPSG:4326",
    max_map_points=12000,
    default_selected_fields=[],
)


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        save_config(DEFAULT_CONFIG, path)
        return DEFAULT_CONFIG

    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    data: dict[str, Any] = {**DEFAULT_CONFIG.__dict__, **raw}
    data["default_selected_fields"] = list(data.get("default_selected_fields", []))
    return AppConfig(**data)


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    path.write_text(
        json.dumps(config.__dict__, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
