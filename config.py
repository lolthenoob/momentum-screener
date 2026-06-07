"""
config.py
─────────
Reads and writes user preferences to screener.ini in the app folder.
"""

import os
import configparser

_BASE    = os.path.dirname(os.path.abspath(__file__))
INI_PATH = os.path.join(_BASE, "screener.ini")

DEFAULTS = {
    "top_n":                    "50",
    "font_size":                "12",
    "col_widths":               "",       # comma-separated pixel widths, rebuilt if empty
    "export_csv":               "false",
    "output_dir":               "",       # defaults to <app>/output at runtime
    "auto_resize":              "false",  # when true, window sizes scale with font; W/H fields ignored
    "launcher_w":               "720",
    "launcher_h":               "580",
    "table_w":                  "1600",
    "table_h":                  "860",
    "active_markets":           "US,AU,NZ,SG",
    "rank_mode":                "normal",
    # Minimum average daily dollar turnover (price × volume) per market.
    # Tickers below this threshold are excluded before scoring.
    # Set to 0 to disable the filter for that market.
    "min_turnover_us":          "10000000",   # $10M  — S&P 500 safety net
    "min_turnover_au":          "500000",     # $500k — filters penny stocks
    "min_turnover_nz":          "100000",     # $100k — small market, lenient
    "min_turnover_sg":          "500000",     # $500k
}


def _parser() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(INI_PATH)
    if "screener" not in cp:
        cp["screener"] = {}
    return cp


def get(key: str) -> str:
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


def font_size() -> int:
    return max(8, min(24, get_int("font_size") or 12))


def col_pixel_width(col_index: int, default_chars: int) -> int:
    """Return saved pixel width for a column, or derive from font + default chars."""
    raw = get("col_widths").strip()
    if raw:
        try:
            widths = [int(x) for x in raw.split(",")]
            if len(widths) > col_index:
                return max(20, widths[col_index])
        except ValueError:
            pass
    # Auto-size: roughly font_size * 1.5 pixels per character (Consolas)
    return max(30, default_chars * int(font_size() * 1.5))


def save_col_widths(widths: list):
    set("col_widths", ",".join(str(int(w)) for w in widths))


def clear_col_widths():
    """Call after font size change so columns auto-resize to new font."""
    set("col_widths", "")


def get_min_turnover(market: str) -> float:
    """Return minimum avg daily dollar turnover for a market. 0 = disabled."""
    key = f"min_turnover_{market.lower()}"
    try:
        val = float(get(key))
        return max(0.0, val)
    except (ValueError, TypeError):
        return float(DEFAULTS.get(key, 0))


def set_min_turnover(market: str, value: float):
    set(f"min_turnover_{market.lower()}", value)


def get_all_min_turnovers() -> dict:
    """Return {market: min_turnover} for all four markets."""
    return {m: get_min_turnover(m) for m in ["US", "AU", "NZ", "SG"]}


def get_active_markets() -> list[str]:
    raw = get("active_markets").strip()
    if not raw:
        return ["US", "AU", "NZ", "SG"]
    return [m.strip().upper() for m in raw.split(",") if m.strip()]


def set_active_markets(markets: list[str]):
    set("active_markets", ",".join(markets))