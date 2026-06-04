"""
config.py
─────────
Reads and writes user preferences to screener.ini in the app folder.
All other modules import from here instead of hardcoding values.
"""

import os
import configparser

_BASE    = os.path.dirname(os.path.abspath(__file__))
INI_PATH = os.path.join(_BASE, "screener.ini")

DEFAULTS = {
    "top_n":        "50",
    "font_size":    "12",
    "col_widths":   "",          # comma-separated int list, rebuilt if empty
    "export_csv":   "false",
    "output_dir":   "",          # defaults to <app>/output at runtime
}


def _parser() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(INI_PATH)
    if "screener" not in cp:
        cp["screener"] = {}
    return cp


def get(key: str):
    cp = _parser()
    return cp["screener"].get(key, DEFAULTS.get(key, ""))


def set(key: str, value):
    cp = _parser()
    cp["screener"][key] = str(value)
    with open(INI_PATH, "w") as f:
        cp.write(f)


def get_int(key: str) -> int:
    try:
        return int(get(key))
    except (ValueError, TypeError):
        return int(DEFAULTS.get(key, 0))


def get_bool(key: str) -> bool:
    return get(key).lower() in ("1", "true", "yes")


def output_dir() -> str:
    d = get("output_dir").strip()
    if not d:
        d = os.path.join(_BASE, "output")
    os.makedirs(d, exist_ok=True)
    return d
