from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


TRANSLATIONS_PATH = Path(__file__).resolve().parent.parent / "translations.json"
SUPPORTED_LANGUAGES = ["no", "en", "et"]


def _default_payload() -> dict:
    return json.loads(TRANSLATIONS_PATH.read_text(encoding="utf-8-sig")) if TRANSLATIONS_PATH.exists() else {"ui": {}, "fields": {}}


def ensure_translation_file(path: Path = TRANSLATIONS_PATH) -> None:
    if not path.exists():
        path.write_text(json.dumps({"ui": {}, "fields": {}}, indent=2, ensure_ascii=False), encoding="utf-8")


def load_translations(path: Path = TRANSLATIONS_PATH) -> dict:
    ensure_translation_file(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_translations(payload: dict, path: Path = TRANSLATIONS_PATH) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_translation_terms(payload: dict, terms: list[str], section: str = "fields") -> tuple[dict, bool]:
    updated = json.loads(json.dumps(payload, ensure_ascii=False))
    updated.setdefault(section, {})
    changed = False
    for term in sorted({str(term).strip() for term in terms if str(term).strip()}):
        if term not in updated[section]:
            updated[section][term] = {lang: term for lang in SUPPORTED_LANGUAGES}
            changed = True
    return updated, changed


def tr(translations: dict, language: str, key: str, section: str = "ui") -> str:
    node = translations.get(section, {}).get(key, {})
    return node.get(language) or node.get("en") or key


def translate_field_name(translations: dict, language: str, field_name: str) -> str:
    node = translations.get("fields", {}).get(field_name, {})
    return node.get(language) or node.get("en") or field_name


def translations_to_dataframe(payload: dict) -> pd.DataFrame:
    rows = []
    for section, entries in payload.items():
        for key, values in entries.items():
            rows.append({"section": section, "key": key, "no": values.get("no", ""), "en": values.get("en", ""), "et": values.get("et", "")})
    return pd.DataFrame(rows).sort_values(["section", "key"]).reset_index(drop=True)


def dataframe_to_translations(df: pd.DataFrame) -> dict:
    payload: dict[str, dict[str, dict[str, str]]] = {}
    for row in df.fillna("").to_dict(orient="records"):
        section = str(row["section"]).strip() or "ui"
        key = str(row["key"]).strip()
        if not key:
            continue
        payload.setdefault(section, {})
        payload[section][key] = {lang: str(row.get(lang, "")).strip() for lang in SUPPORTED_LANGUAGES}
    return payload
