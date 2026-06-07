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
    "col_widths":               "",
    "export_csv":               "false",
    "always_export_csv":        "false",
    "output_dir":               "",
    "auto_resize":              "true",
    "launcher_w":               "720",
    "launcher_h":               "580",
    "table_w":                  "1600",
    "table_h":                  "860",
    "active_markets":           "US,AU,NZ,SG,MY",
    "rank_mode":                "normal",
    "hidden_cols":              "",
    "col_order":                "",
    # Watchlist mode
    "watchlist_tickers":        "",
    "watchlist_rank_mode":      "normal",
    # Minimum average daily dollar turnover per market. 0 = disabled.
    "min_turnover_us":          "10000000",   # $10M
    "min_turnover_au":          "2000000",    # $2M
    "min_turnover_nz":          "100000",     # $100k
    "min_turnover_sg":          "500000",     # SGD 500k
    "min_turnover_my":          "500000",     # MYR 500k
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


def _set(key: str, value):
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
    raw = get("col_widths").strip()
    if raw:
        try:
            widths = [int(x) for x in raw.split(",")]
            if len(widths) > col_index:
                return max(20, widths[col_index])
        except ValueError:
            pass
    return max(30, default_chars * int(font_size() * 1.5))


def save_col_widths(widths: list):
    _set("col_widths", ",".join(str(int(w)) for w in widths))


def clear_col_widths():
    _set("col_widths", "")


def get_min_turnover(market: str) -> float:
    key = f"min_turnover_{market.lower()}"
    try:
        val = float(get(key))
        return max(0.0, val)
    except (ValueError, TypeError):
        return float(DEFAULTS.get(key, 0))


def set_min_turnover(market: str, value: float):
    _set(f"min_turnover_{market.lower()}", value)


def get_all_min_turnovers() -> dict:
    return {m: get_min_turnover(m) for m in ["US", "AU", "NZ", "SG", "MY"]}


def get_active_markets() -> list[str]:
    raw = get("active_markets").strip()
    if not raw:
        return ["US", "AU", "NZ", "SG", "MY"]
    return [m.strip().upper() for m in raw.split(",") if m.strip()]


def set_active_markets(markets: list[str]):
    _set("active_markets", ",".join(markets))


def get_hidden_cols() -> set:
    raw = get("hidden_cols").strip()
    if not raw:
        return set()
    return {f.strip() for f in raw.split(",") if f.strip()}


def set_hidden_cols(fields: set):
    _set("hidden_cols", ",".join(sorted(fields)))


def get_col_order() -> list:
    raw = get("col_order").strip()
    if not raw:
        return []
    return [f.strip() for f in raw.split(",") if f.strip()]


def set_col_order(fields: list):
    _set("col_order", ",".join(fields))