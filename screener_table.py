"""
screener_table.py
─────────────────
Interactive Tkinter results table for the momentum screener.

Frozen left columns: Rank + Ticker only (never scroll horizontally).
All other columns including Name scroll right with the data.
Scrollable header row stays pinned above data, synced to xscroll.

show_screener_table() can be called two ways:
  1. parent_frame=<Frame>   — embeds the table directly into that frame
                              (no Toplevel, no Win32 menu crash).
                              on_close= callback is called when Close is pressed.
  2. master=<Tk>            — legacy fallback: opens a plain Toplevel window
                              (no -toolwindow, no special attributes).

Rendering: canvas-based (create_rectangle + create_text per cell).
  500 rows render in < 1 second. No per-cell Frame/Label widgets.
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
import pandas as pd
import numpy as np

import config

# ── Palette ───────────────────────────────────────────────────────────────────

CLR_ACCENT  = "#00A4EF"
CLR_BG      = "#F7F9FC"
CLR_ROW_A   = "#FFFFFF"
CLR_ROW_B   = "#EFF4FA"
CLR_TEXT    = "#1A1A2E"
CLR_SUBTEXT = "#555577"
CLR_HDR_BG  = "#1A1A2E"
CLR_HDR_FG  = "#FFFFFF"
CLR_GREEN   = "#D4EDDA"
CLR_RED     = "#F8D7DA"
CLR_YELLOW  = "#FFF3CD"
CLR_BLUE    = "#EAF4FB"

MARKET_COLOURS = {
    "US": "#00A4EF",
    "AU": "#10B981",
    "NZ": "#8B5CF6",
    "SG": "#F59E0B",
    "?":  "#999999",
}

# ── Formatting helpers ────────────────────────────────────────────────────────

def _nan(v):
    return v is None or (isinstance(v, float) and np.isnan(v))

def _fmt_pct(v, _=None):
    return "—" if _nan(v) else f"{v * 100:+.1f}%"

def _fmt_num(v, dp=1):
    return "—" if _nan(v) else f"{v:.{dp}f}"

def _fmt_price(v, _=None):
    return "—" if _nan(v) else f"${v:,.2f}"

def _fmt_slope(v, _=None):
    return "—" if _nan(v) else f"{v * 100:+.1f}%"

def _fmt_ma_flag(v, _=None):
    if _nan(v):
        return "—"
    return "✓" if int(v) == 1 else "✗"

# ── Cell colour helpers ───────────────────────────────────────────────────────

def _score_clr(v):
    if _nan(v):  return CLR_ROW_A
    if v >= 80:  return CLR_GREEN
    if v >= 60:  return CLR_BLUE
    if v <= 30:  return CLR_RED
    return CLR_ROW_A

def _ret_clr(v):
    if _nan(v):      return CLR_ROW_A
    if v > 0.05:     return CLR_GREEN
    if v < -0.05:    return CLR_RED
    return CLR_YELLOW

def _slope_clr(v):
    if _nan(v):   return CLR_ROW_A
    if v > 0.20:  return CLR_GREEN
    if v > 0:     return CLR_BLUE
    if v < -0.10: return CLR_RED
    return CLR_YELLOW

def _osc_clr(v, lo, hi, good_high=True):
    if _nan(v):   return CLR_ROW_A
    if v > hi:    return CLR_GREEN if good_high else CLR_RED
    if v < lo:    return CLR_RED   if good_high else CLR_GREEN
    return CLR_YELLOW

def _ma_flag_clr(v):
    if _nan(v):       return CLR_ROW_A
    return CLR_GREEN if int(v) == 1 else CLR_RED

def _ram_clr(v):
    if _nan(v):   return CLR_ROW_A
    if v > 1.5:   return CLR_GREEN
    if v > 1.0:   return CLR_BLUE
    if v < 0.6:   return CLR_RED
    return CLR_YELLOW

def _vol_ratio_clr(v):
    if _nan(v):   return CLR_ROW_A
    if v > 1.5:   return CLR_GREEN
    if v > 1.1:   return CLR_BLUE
    if v < 0.7:   return CLR_RED
    return CLR_ROW_A

def _high_52w_clr(v):
    if _nan(v):    return CLR_ROW_A
    if v >= -0.05: return CLR_GREEN
    if v >= -0.15: return CLR_BLUE
    if v <= -0.30: return CLR_RED
    return CLR_YELLOW

def _vol_surge_clr(v):
    if _nan(v):   return CLR_ROW_A
    if v > 2.0:   return CLR_GREEN
    if v > 1.3:   return CLR_BLUE
    if v < 0.5:   return CLR_RED
    return CLR_ROW_A

def _ema_clr(v):
    if _nan(v):     return CLR_ROW_A
    if v > 0.03:    return CLR_GREEN
    if v > 0:       return CLR_BLUE
    if v < -0.03:   return CLR_RED
    return CLR_YELLOW

def _mk(fn):
    return lambda v, _r: fn(v)

# ── Column definitions ────────────────────────────────────────────────────────

COLUMNS = [
    ("Rank",        "rank",           6,  lambda v, _: str(v),               None,             True),
    ("Ticker",      "symbol",        10,  lambda v, _: str(v),               None,             True),
    ("Name",        "name",          25,  lambda v, _: str(v) if v else "—", None,             False),
    ("Sector",      "sector",        18,  lambda v, _: str(v) if v else "—", None,             False),
    ("Market",      "market",         8,  lambda v, _: str(v),               None,             False),
    ("Price",       "price",          9,  _fmt_price,                        None,             False),
    ("Score",       "momentum_score", 8,  lambda v, _: _fmt_num(v, 1),      _mk(_score_clr),  False),
    ("Chg",         "rank_change",    6,  lambda v, _: (
        "NEW" if _nan(v) else (f"▲{int(abs(v))}" if v > 0 else (f"▼{int(abs(v))}" if v < 0 else "–"))
    ),  lambda v, _: (
        CLR_ROW_A if _nan(v) else (CLR_GREEN if v > 0 else (CLR_RED if v < 0 else CLR_ROW_A))
    ),  False),
    ("RAM Score",   "ram_score",      12,  lambda v, _: _fmt_num(v, 3),      _mk(_ram_clr),    False),
    ("Exp Slope",   "exp_slope",      12,  _fmt_slope,                        _mk(_slope_clr),  False),
    ("Vol Ratio",   "vol_ratio",     10,  lambda v, _: _fmt_num(v, 2),      _mk(_vol_ratio_clr), False),
    ("52w High%",   "high_52w_pct",  11,  _fmt_pct,                          _mk(_high_52w_clr),  False),
    ("12-1M Ret",   "ret_12_1",       12,  _fmt_pct,                          _mk(_ret_clr),    False),
    ("3M Ret",      "ret_3m",         12,  _fmt_pct,                          _mk(_ret_clr),    False),
    ("Stoch %K",    "stoch_k",        12,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, 20, 80),   False),
    ("Stoch %D",    "stoch_d",        12,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, 20, 80),   False),
    ("RSI",         "rsi",            8,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, 30, 70),   False),
    ("CCI",         "cci",            8,  lambda v, _: _fmt_num(v, 0),      lambda v, _: _osc_clr(v, -100, 100),False),
    ("Williams %R", "wpr",            12,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, -80, -20, good_high=False), False),
    ("ATR(15)",     "atr",            12,  lambda v, _: _fmt_num(v, 2),      None,             False),
    ("MA25",        "above_ma25",     8,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
    ("MA50",        "above_ma50",     8,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
    ("MA100",       "above_ma100",    8,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
    ("MA200",       "above_ma200",    8,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
    ("Wk Score",    "weekly_score",   10, lambda v, _: _fmt_num(v, 1),      _mk(_score_clr),     False),
    ("1W Ret",      "ret_1w",         10, _fmt_pct,                          _mk(_ret_clr),       False),
    ("Wk Slope",    "weekly_exp_slope",11,_fmt_slope,                        _mk(_slope_clr),     False),
    ("Wk RSI(5)",   "weekly_rsi",      10,lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, 30, 70), False),
    ("Vol Surge",   "vol_surge",       10,lambda v, _: _fmt_num(v, 2),      _mk(_vol_surge_clr), False),
    ("vs EMA20",    "price_vs_ema20",  10,_fmt_pct,                          _mk(_ema_clr),       False),
]

FROZEN_COLS = [c for c in COLUMNS if     c[5]]
SCROLL_COLS = [c for c in COLUMNS if not c[5]]
_N_COLS     = len(COLUMNS)

# ── Column width helpers ──────────────────────────────────────────────────────

def _load_col_widths(fs: int | None = None) -> list:
    raw = config.get("col_widths").strip()
    if raw:
        try:
            w = [int(x) for x in raw.split(",")]
            if len(w) == _N_COLS:
                return w
        except ValueError:
            pass
    _fs = fs or config.font_size()
    return [max(30, c[2] * (_fs - 2)) for c in COLUMNS]

def _save_col_widths(widths: list):
    config.set("col_widths", ",".join(str(int(w)) for w in widths))

def _col_px(char_w: int, fs: int) -> int:
    return max(30, char_w * (fs - 2))


# ── Main entry point ──────────────────────────────────────────────────────────

def show_screener_table(
    results: dict,
    title: str = "Momentum Screener — Results",
    master=None,
    parent_frame=None,
    on_close=None,
    rank_mode: str = "normal",
):
    is_embedded = parent_frame is not None

    if is_embedded:
        root = parent_frame
    else:
        if master is None:
            master = tk._get_default_root()
        root = tk.Toplevel(master)
        root.title(title)
        root.configure(bg=CLR_BG)
        root.resizable(True, True)
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        if config.get_bool("auto_resize"):
            scale = config.font_size() / 12
            w = min(int(1700 * scale), sw - 60)
            h = min(int(880  * scale), sh - 60)
        else:
            w = min(config.get_int("table_w") or 1600, sw - 60)
            h = min(config.get_int("table_h") or 860,  sh - 60)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        root.minsize(900, 450)

    fs       = config.get_int("font_size") or 12
    mono     = tkfont.Font(family="Consolas", size=fs)
    bold     = tkfont.Font(family="Consolas", size=fs, weight="bold")
    hdr_bold = tkfont.Font(family="Consolas", size=16, weight="bold")
    hdr_sub  = tkfont.Font(family="Consolas", size=fs)

    # ── App header ────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=CLR_ACCENT, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Momentum Screener",
             bg=CLR_ACCENT, fg="white", font=hdr_bold).pack()
    scored_at = results.get("scored_at", "")
    tk.Label(hdr,
             text=f"Scored at {scored_at}  ·  Click column header to sort  ·  Drag header edges to resize",
             bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub).pack()

    # ── Tab bar ───────────────────────────────────────────────────────────
    tabs_data = {"Overall": results.get("overall", pd.DataFrame())}
    for market in ["US", "AU", "NZ", "SG"]:
        bm = results.get("by_market", {})
        if market in bm and not bm[market].empty:
            tabs_data[market] = bm[market]
    sector_df = _build_sector_df(results.get("overall", pd.DataFrame()), rank_mode)
    if not sector_df.empty:
        tabs_data["Sectors"] = sector_df

    tab_bar = tk.Frame(root, bg="#E8EDF4")
    tab_bar.pack(fill="x", padx=8, pady=(6, 0))

    content_area = tk.Frame(root, bg=CLR_BG)
    content_area.pack(fill="both", expand=True, padx=8)

    tab_frames  = {}
    tab_buttons = {}
    tab_built   = {}
    _active_tab = {"name": None}

    for tab_name in tabs_data:
        f = tk.Frame(content_area, bg=CLR_BG)
        tab_frames[tab_name] = f
        tab_built[tab_name]  = False

    _mw_unbind_callbacks = {}

    def _switch_tab(name):
        if _active_tab["name"] == name:
            return
        prev = _active_tab["name"]
        if prev and prev in _mw_unbind_callbacks:
            try:
                _mw_unbind_callbacks[prev]()
            except Exception:
                pass
        if _active_tab["name"] and _active_tab["name"] in tab_frames:
            tab_frames[_active_tab["name"]].pack_forget()

        if not tab_built[name]:
            unbind_ref = []
            _build_table(tab_frames[name], tabs_data[name], mono, bold, fs,
                         rank_mode=rank_mode, _mw_unbind_ref=unbind_ref)
            if unbind_ref:
                _mw_unbind_callbacks[name] = unbind_ref[0]
            tab_built[name] = True

        tab_frames[name].pack(fill="both", expand=True)
        _active_tab["name"] = name
        for n, btn in tab_buttons.items():
            btn.config(bg=CLR_ACCENT if n == name else "#E8EDF4",
                       fg="white"   if n == name else CLR_TEXT)

    for tab_name in tabs_data:
        btn = tk.Button(
            tab_bar, text=f"  {tab_name}  ",
            font=bold, relief="flat", bd=0,
            bg="#E8EDF4", fg=CLR_TEXT,
            activebackground=CLR_ACCENT, activeforeground="white",
            padx=6, pady=6, cursor="hand2",
            command=lambda n=tab_name: _switch_tab(n),
        )
        btn.pack(side="left")
        tab_buttons[tab_name] = btn

    _switch_tab(next(iter(tabs_data)))

    # ── Footer ────────────────────────────────────────────────────────────
    footer = tk.Frame(root, bg=CLR_BG, pady=5, padx=12)
    footer.pack(fill="x")
    if rank_mode == "weekly":
        footer_txt = "Ranked by Weekly Score  |  Wk Score = 1W Ret · Wk Slope · Wk RSI · Vol Surge · vs EMA20"
    elif rank_mode == "both":
        footer_txt = "Both momentum modes shown  |  Ranked by Normal Score"
    else:
        footer_txt = "Score = RAM · Exp Slope · 12-1M · 3M · Stoch · RSI · CCI · W%R · MA count  |  ATR & MA flags = raw info"
    tk.Label(footer, text=footer_txt,
             bg=CLR_BG, fg=CLR_SUBTEXT, font=mono).pack(side="left")

    def _new_scan():
        if is_embedded:
            for w in root.winfo_children():
                w.destroy()
            if on_close:
                on_close()
        else:
            root.destroy()

    def _exit_app():
        w = root
        while w.master:
            w = w.master
        w.destroy()

    btn_cfg = dict(font=bold, relief="flat", padx=12, pady=4, cursor="hand2")
    tk.Button(footer, text="✕  Exit",     bg="#CC3333", fg="white",
              command=_exit_app, **btn_cfg).pack(side="right")
    tk.Button(footer, text="↺  New Scan", bg="#00A4EF", fg="white",
              command=_new_scan, **btn_cfg).pack(side="right", padx=(0, 6))


# ── Sector helpers ────────────────────────────────────────────────────────────

def _build_sector_df(overall: pd.DataFrame, rank_mode: str) -> pd.DataFrame:
    df = overall.copy()
    if "sector" not in df.columns or df.empty:
        return pd.DataFrame()
    df = df[df["sector"].notna() & (df["sector"] != "")]
    score_col = "weekly_score" if rank_mode == "weekly" else "momentum_score"
    agg = df.groupby("sector").agg(
        tickers   =("sector",    "count"),
        avg_score =(score_col,   "mean"),
        avg_1w    =("ret_1w",    "mean"),
        avg_3m    =("ret_3m",    "mean"),
        avg_12_1  =("ret_12_1",  "mean"),
        avg_vol   =("vol_surge", "mean"),
        markets   =("market",    lambda x: "/".join(sorted(set(x)))),
    ).reset_index()
    agg = agg.sort_values("avg_score", ascending=False).reset_index(drop=True)
    agg.insert(0, "rank", range(1, len(agg) + 1))
    return agg


def _build_sector_table(parent: tk.Frame, df: pd.DataFrame, mono, bold, fs: int,
                        _mw_unbind_ref: list):
    SCOLS = [
        ("Rank",      "rank",      4,  lambda v, _: str(int(v)),    None),
        ("Sector",    "sector",    24, lambda v, _: str(v),          None),
        ("# Stocks",  "tickers",   8,  lambda v, _: str(int(v)),    None),
        ("Avg Score", "avg_score", 10, lambda v, _: _fmt_num(v, 1), _score_clr),
        ("Avg 1W",    "avg_1w",    10, lambda v, _: _fmt_pct(v),    _ret_clr),
        ("Avg 3M",    "avg_3m",    10, lambda v, _: _fmt_pct(v),    _ret_clr),
        ("Avg 12-1M", "avg_12_1",  12, lambda v, _: _fmt_pct(v),    _ret_clr),
        ("Vol Surge", "avg_vol",   12, lambda v, _: _fmt_num(v, 2), None),
        ("Markets",   "markets",   10, lambda v, _: str(v),          None),
    ]

    char_w = int(fs * 1.1)
    row_h  = fs + max(6, fs // 2)
    hdr_h  = fs + max(8, fs // 2) + max(4, fs // 3) * 2

    sort_state  = {"col": "avg_score", "asc": False}
    hdr_btns    = {}
    _current_df = [df.copy()]

    outer = tk.Frame(parent, bg=CLR_BG)
    outer.pack(fill="both", expand=True)

    vsb = ttk.Scrollbar(outer, orient="vertical")
    vsb.pack(side="right", fill="y")

    canvas = tk.Canvas(outer, bg=CLR_BG, highlightthickness=0,
                       yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.config(command=canvas.yview)

    hdr_frame = tk.Frame(canvas, bg=CLR_HDR_BG)
    hdr_win   = canvas.create_window((0, 0), window=hdr_frame, anchor="nw")

    inner     = tk.Frame(canvas, bg=CLR_BG)
    inner_win = canvas.create_window((0, hdr_h), window=inner, anchor="nw")

    def _on_configure(e):
        canvas.configure(scrollregion=(
            0, 0,
            max(canvas.winfo_width(), inner.winfo_reqwidth()),
            hdr_h + inner.winfo_reqheight()
        ))
        canvas.itemconfig(hdr_win,   width=max(canvas.winfo_width(), inner.winfo_reqwidth()))
        canvas.itemconfig(inner_win, width=max(canvas.winfo_width(), inner.winfo_reqwidth()))

    inner.bind("<Configure>",  _on_configure)
    canvas.bind("<Configure>", _on_configure)

    def _on_yscroll(*args):
        canvas.yview(*args)
        y_frac  = canvas.yview()[0]
        total_h = hdr_h + inner.winfo_reqheight()
        canvas.coords(hdr_win, 0, int(y_frac * total_h))

    vsb.config(command=_on_yscroll)

    def _on_mw(e):
        delta = -1 if e.num == 4 else (1 if e.num == 5 else int(-e.delta / 120))
        canvas.yview_scroll(delta, "units")

    def _bind_mw(w):
        w.bind("<MouseWheel>", _on_mw)
        w.bind("<Button-4>",   _on_mw)
        w.bind("<Button-5>",   _on_mw)

    _bind_mw(canvas)
    _bind_mw(inner)

    def _unbind():
        try:
            canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
    _mw_unbind_ref.append(_unbind)

    def _refresh_arrows():
        for field, btn in hdr_btns.items():
            label = next(c[0] for c in SCOLS if c[1] == field)
            if field == sort_state["col"]:
                btn.config(text=label + (" ↑" if sort_state["asc"] else " ↓"), fg="#FFD700")
            else:
                btn.config(text=label + " ↕", fg=CLR_HDR_FG)

    _data_rows = []

    def _render(data: pd.DataFrame):
        _current_df[0] = data
        for rf in _data_rows:
            rf.destroy()
        _data_rows.clear()

        for row_i, row in data.iterrows():
            bg = CLR_ROW_A if row_i % 2 == 0 else CLR_ROW_B
            rf = tk.Frame(inner, bg=bg)
            rf.pack(fill="x")
            _bind_mw(rf)
            _data_rows.append(rf)

            for col_i, (label, field, chars, fmt, clr_fn) in enumerate(SCOLS):
                val = row.get(field)
                if isinstance(val, float) and np.isnan(val):
                    val = None
                text    = fmt(val, None) if val is not None else "—"
                cell_bg = clr_fn(val) if (clr_fn and val is not None) else bg
                anchor  = "w" if col_i <= 1 else "e"
                lbl = tk.Label(rf, text=text, font=mono,
                               bg=cell_bg, fg=CLR_TEXT,
                               width=chars, anchor=anchor,
                               relief="flat", pady=max(2, fs // 6), padx=4)
                lbl.pack(side="left")
                _bind_mw(lbl)

    def _sort_cmd(field):
        def _cmd():
            if sort_state["col"] == field:
                sort_state["asc"] = not sort_state["asc"]
            else:
                sort_state["col"] = field
                sort_state["asc"] = field in ("sector", "markets")
            _refresh_arrows()
            sorted_df = _current_df[0].sort_values(
                field, ascending=sort_state["asc"], na_position="last"
            ).reset_index(drop=True)
            sorted_df["rank"] = range(1, len(sorted_df) + 1)
            _render(sorted_df)
        return _cmd

    for col_i, (label, field, chars, fmt, clr_fn) in enumerate(SCOLS):
        arrow = " ↓" if field == "avg_score" else " ↕"
        fg    = "#FFD700" if field == "avg_score" else CLR_HDR_FG
        btn = tk.Button(
            hdr_frame, text=label + arrow, font=bold,
            bg=CLR_HDR_BG, fg=fg,
            activebackground="#333355", activeforeground="white",
            relief="flat", padx=4, pady=max(4, fs // 3),
            width=chars, anchor="w" if col_i <= 1 else "e",
            cursor="hand2", command=_sort_cmd(field),
        )
        btn.pack(side="left")
        hdr_btns[field] = btn
        _bind_mw(btn)

    initial = df.sort_values("avg_score", ascending=False).reset_index(drop=True)
    initial["rank"] = range(1, len(initial) + 1)
    _render(initial)


# ── Table builder ─────────────────────────────────────────────────────────────

def _build_table(parent: tk.Frame, df: pd.DataFrame, mono, bold, fs: int,
                 rank_mode: str = "normal", _mw_unbind_ref: list = None):
    if _mw_unbind_ref is None:
        _mw_unbind_ref = []
    if df.empty:
        tk.Label(parent, text="No data for this market.",
                 bg=CLR_BG, fg=CLR_SUBTEXT, font=mono).pack(pady=40)
        return

    if "avg_score" in df.columns:
        _build_sector_table(parent, df, mono, bold, fs, _mw_unbind_ref=_mw_unbind_ref)
        return

    # ── Column set for this rank mode ─────────────────────────────────────
    _WEEKLY_FIELDS = {"weekly_score", "ret_1w", "weekly_exp_slope",
                      "weekly_rsi", "vol_surge", "price_vs_ema20"}
    _NORMAL_FIELDS = {"ram_score", "exp_slope", "ret_12_1", "ret_3m",
                      "stoch_k", "stoch_d", "rsi", "cci", "wpr",
                      "atr", "above_ma25", "above_ma50", "above_ma100",
                      "above_ma200", "vol_ratio", "high_52w_pct"}

    if rank_mode == "weekly":
        _keep = lambda c: c[1] not in _NORMAL_FIELDS
        _default_sort = "weekly_score"
    elif rank_mode == "normal":
        _keep = lambda c: c[1] not in _WEEKLY_FIELDS
        _default_sort = "momentum_score"
    else:
        _keep = lambda c: True
        _default_sort = "momentum_score"

    _active_frozen = [c for c in FROZEN_COLS if _keep(c)]

    _hidden  = config.get_hidden_cols()
    _order   = config.get_col_order()
    _mode_scroll = [c for c in SCROLL_COLS if _keep(c) and c[1] not in _hidden]

    if _order:
        _field_map     = {c[1]: c for c in _mode_scroll}
        _ordered       = [_field_map[f] for f in _order if f in _field_map]
        _remaining     = [c for c in _mode_scroll if c[1] not in set(_order)]
        _active_scroll = _ordered + _remaining
    else:
        _active_scroll = _mode_scroll

    _active_cols = _active_frozen + _active_scroll

    df = df.reset_index()
    if "symbol" not in df.columns:
        candidate = next(
            (c for c in df.columns if c not in ("index",) or c == df.columns[0]),
            df.columns[0],
        )
        df = df.rename(columns={candidate: "symbol"})
    df.insert(0, "rank", range(1, len(df) + 1))
    if "name" not in df.columns:
        df["name"] = ""

    col_widths = _load_col_widths(fs)

    def px(col_idx):
        return max(30, int(col_widths[col_idx]))

    row_h = fs + max(6, fs // 2)
    hdr_h = fs + max(8, fs // 2) + max(4, fs // 3) * 2

    # ── Layout ────────────────────────────────────────────────────────────
    outer = tk.Frame(parent, bg=CLR_BG)
    outer.pack(fill="both", expand=True)

    v_scroll = ttk.Scrollbar(outer, orient="vertical")
    v_scroll.pack(side="right", fill="y")

    h_scroll = ttk.Scrollbar(outer, orient="horizontal")
    h_scroll.pack(side="bottom", fill="x")

    frozen_pane_w = sum(px(COLUMNS.index(c)) for c in _active_frozen)
    frozen_pane = tk.Frame(outer, bg=CLR_HDR_BG, width=frozen_pane_w)
    frozen_pane.pack(side="left", fill="y")
    frozen_pane.pack_propagate(False)

    frozen_hdr = tk.Frame(frozen_pane, bg=CLR_HDR_BG, height=hdr_h)
    frozen_hdr.pack(side="top", fill="x")
    frozen_hdr.pack_propagate(False)

    frozen_canvas = tk.Canvas(frozen_pane, bg=CLR_BG, highlightthickness=0,
                              yscrollcommand=v_scroll.set)
    frozen_canvas.pack(side="top", fill="both", expand=True)

    tk.Frame(outer, bg="#444466", width=2).pack(side="left", fill="y")

    scroll_pane = tk.Frame(outer, bg=CLR_BG)
    scroll_pane.pack(side="left", fill="both", expand=True)

    scroll_hdr_vp = tk.Frame(scroll_pane, bg=CLR_HDR_BG, height=hdr_h)
    scroll_hdr_vp.pack(side="top", fill="x")
    scroll_hdr_vp.pack_propagate(False)

    scroll_hdr_inner = tk.Frame(scroll_hdr_vp, bg=CLR_HDR_BG)
    scroll_hdr_inner.place(x=0, y=0, height=hdr_h)

    scroll_canvas = tk.Canvas(scroll_pane, bg=CLR_BG, highlightthickness=0,
                              yscrollcommand=v_scroll.set,
                              xscrollcommand=h_scroll.set)
    scroll_canvas.pack(side="top", fill="both", expand=True)

    # ── Canvas drawing surfaces ───────────────────────────────────────────
    # One canvas per pane — all rows drawn as canvas items, no Frame/Label per cell
    frozen_draw = tk.Canvas(frozen_canvas, bg=CLR_BG, highlightthickness=0)
    frozen_canvas.create_window((0, 0), window=frozen_draw, anchor="nw")

    scroll_draw = tk.Canvas(scroll_canvas, bg=CLR_BG, highlightthickness=0)
    scroll_canvas.create_window((0, 0), window=scroll_draw, anchor="nw")

    # ── Shared scroll wiring ──────────────────────────────────────────────
    def _yview(*args):
        frozen_canvas.yview(*args)
        scroll_canvas.yview(*args)

    def _xview(*args):
        scroll_canvas.xview(*args)
        try:
            frac  = scroll_canvas.xview()[0]
            total = scroll_draw.winfo_reqwidth()
            scroll_hdr_inner.place_configure(x=-int(frac * total))
        except Exception:
            pass

    v_scroll.config(command=_yview)
    h_scroll.config(command=_xview)

    def _on_mw(e):
        delta = -1 if e.num == 4 else (1 if e.num == 5 else int(-e.delta / 120))
        frozen_canvas.yview_scroll(delta, "units")
        scroll_canvas.yview_scroll(delta, "units")

    for w in (frozen_canvas, frozen_draw, scroll_canvas, scroll_draw,
              frozen_hdr, scroll_hdr_vp, scroll_hdr_inner):
        w.bind("<MouseWheel>", _on_mw)
        w.bind("<Button-4>",   _on_mw)
        w.bind("<Button-5>",   _on_mw)

    # ── Sort state ────────────────────────────────────────────────────────
    sort_state   = {"col": _default_sort, "asc": False}
    all_hdr_btns = {}

    def _refresh_arrows():
        for f, btn in all_hdr_btns.items():
            lbl = next(c[0] for c in _active_cols if c[1] == f)
            if f == sort_state["col"]:
                btn.config(text=lbl + (" ↑" if sort_state["asc"] else " ↓"), fg="#FFD700")
            else:
                btn.config(text=lbl + " ↕", fg=CLR_HDR_FG)

    _current_df = [None]

    def _sort_cmd(field):
        def _cmd():
            if sort_state["col"] == field:
                sort_state["asc"] = not sort_state["asc"]
            else:
                sort_state["col"] = field
                sort_state["asc"] = field in ("rank", "symbol", "name", "market")
            _refresh_arrows()
            _render(df.sort_values(sort_state["col"],
                                   ascending=sort_state["asc"],
                                   na_position="last"))
        return _cmd

    # ── Header cell factory ───────────────────────────────────────────────
    def _make_hdr_cell(parent_frame, col_tuple, col_idx):
        label, field, _dw, _fmt, _clr, _frozen = col_tuple
        w = px(col_idx)

        cf = tk.Frame(parent_frame, bg=CLR_HDR_BG, width=w, height=hdr_h)
        cf.pack_propagate(False)
        cf.pack(side="left")

        arrow = " ↓" if field == _default_sort else " ↕"
        fg    = "#FFD700" if field == _default_sort else CLR_HDR_FG
        btn   = tk.Button(cf, text=label + arrow, font=bold,
                          bg=CLR_HDR_BG, fg=fg,
                          activebackground="#333355", activeforeground="white",
                          relief="flat", padx=4, pady=max(4, fs // 3),
                          cursor="hand2", command=_sort_cmd(field))
        btn.pack(fill="both", expand=True)
        all_hdr_btns[field] = btn
        btn.bind("<MouseWheel>", _on_mw)
        btn.bind("<Button-4>",   _on_mw)
        btn.bind("<Button-5>",   _on_mw)

        handle = tk.Frame(cf, bg="#444466", width=3, cursor="sb_h_double_arrow")
        handle.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        def _start(e, f=cf):
            f._dx = e.x_root
            f._dw = f.winfo_width()

        def _drag(e, idx=col_idx, f=cf):
            new_w = max(30, f._dw + (e.x_root - f._dx))
            f.config(width=new_w)
            col_widths[idx] = new_w

        def _release(e, idx=col_idx, f=cf):
            new_w = max(30, f.winfo_width())
            col_widths[idx] = new_w
            _save_col_widths(col_widths)
            _render(_current_df[0])

        handle.bind("<ButtonPress-1>",   _start)
        handle.bind("<B1-Motion>",       _drag)
        handle.bind("<ButtonRelease-1>", _release)

    for col in _active_frozen:
        _make_hdr_cell(frozen_hdr, col, COLUMNS.index(col))

    for col in _active_scroll:
        _make_hdr_cell(scroll_hdr_inner, col, COLUMNS.index(col))

    def _place_scroll_hdr(*_):
        frozen_hdr.update_idletasks()
        real_hdr_h = frozen_hdr.winfo_reqheight()
        if real_hdr_h > 0:
            frozen_hdr.configure(height=real_hdr_h)
            scroll_hdr_vp.configure(height=real_hdr_h)
            scroll_hdr_inner.place_configure(height=real_hdr_h)

    frozen_hdr.bind("<Configure>", _place_scroll_hdr)
    frozen_hdr.after(100, _place_scroll_hdr)
    frozen_hdr.after(300, _place_scroll_hdr)

    # ── Canvas renderer ───────────────────────────────────────────────────
    # Draws all rows as canvas rectangles + text items.
    # Vastly faster than Frame/Label per cell — 500 rows in < 1 second.

    def _render(data: pd.DataFrame):
        _current_df[0] = data

        frozen_draw.delete("all")
        scroll_draw.delete("all")

        rows_list = list(data.iterrows())
        total     = len(rows_list)
        if total == 0:
            return

        f_widths = [px(COLUMNS.index(c)) for c in _active_frozen]
        s_widths = [px(COLUMNS.index(c)) for c in _active_scroll]

        frozen_total_w = sum(f_widths)
        scroll_total_w = sum(s_widths)
        total_h        = total * row_h

        frozen_draw.config(width=frozen_total_w, height=total_h)
        scroll_draw.config(width=scroll_total_w, height=total_h)

        for i, (_, row) in enumerate(rows_list):
            y_top  = i * row_h
            y_bot  = y_top + row_h
            y_mid  = y_top + row_h // 2
            bg_def = CLR_ROW_A if i % 2 == 0 else CLR_ROW_B

            # Frozen columns
            x = 0
            for ci, col in enumerate(_active_frozen):
                w       = f_widths[ci]
                _, field, _dw, fmt, clr_fn, _ = col

                val = row.get(field)
                if isinstance(val, float) and np.isnan(val):
                    val = None

                text    = fmt(val, row) if val is not None else "—"
                cell_bg = clr_fn(val, row) if (clr_fn and val is not None) else bg_def
                fg      = CLR_ACCENT if field == "symbol" else CLR_TEXT
                use_bold   = field in ("symbol", "momentum_score")
                anchor_tk  = "w" if field in ("symbol", "name", "market") else "e"
                tx = (x + 4) if anchor_tk == "w" else (x + w - 4)

                frozen_draw.create_rectangle(x, y_top, x + w, y_bot,
                                             fill=cell_bg, outline="", width=0)
                frozen_draw.create_text(tx, y_mid, text=text,
                                        font=bold if use_bold else mono,
                                        fill=fg, anchor=anchor_tk)
                x += w

            # Scroll columns
            x = 0
            for ci, col in enumerate(_active_scroll):
                w       = s_widths[ci]
                _, field, _dw, fmt, clr_fn, _ = col

                val = row.get(field)
                if isinstance(val, float) and np.isnan(val):
                    val = None

                text    = fmt(val, row) if val is not None else "—"
                cell_bg = clr_fn(val, row) if (clr_fn and val is not None) else bg_def

                fg = CLR_TEXT
                if field == "market":
                    fg = MARKET_COLOURS.get(str(val) if val is not None else "?", CLR_TEXT)
                elif field in ("above_ma25", "above_ma50", "above_ma100", "above_ma200"):
                    if val is not None:
                        fg = "#1A7A3A" if int(val) == 1 else "#991122"
                elif field == "momentum_score":
                    fg = CLR_TEXT

                use_bold  = field == "momentum_score"
                anchor_tk = "w" if field in ("name", "market") else "e"
                tx = (x + 4) if anchor_tk == "w" else (x + w - 4)

                scroll_draw.create_rectangle(x, y_top, x + w, y_bot,
                                             fill=cell_bg, outline="", width=0)
                scroll_draw.create_text(tx, y_mid, text=text,
                                        font=bold if use_bold else mono,
                                        fill=fg, anchor=anchor_tk)
                x += w

        # Update scroll regions
        frozen_canvas.configure(scrollregion=(0, 0, frozen_total_w, total_h))
        scroll_canvas.configure(
            scrollregion=(0, 0,
                          max(scroll_total_w, scroll_canvas.winfo_width()),
                          total_h)
        )
        # Keep frozen canvas width locked
        frozen_pane.config(width=frozen_total_w)

    _render(df.sort_values(_default_sort, ascending=False, na_position="last"))