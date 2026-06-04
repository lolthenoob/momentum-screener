"""
screener_table.py
─────────────────
Interactive Tkinter results table for the momentum screener.

Columns:
  Rank, Ticker, Market, Price, Score (composite),
  RAM Score, Exp Slope×R², 12-1M Ret, 3M Ret,
  Stoch %K, Stoch %D, RSI, CCI, Williams %R, ATR,
  MA25, MA50, MA100, MA200

Click any column header to sort; click again to reverse.
Default sort: composite momentum score descending.
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
import pandas as pd
import numpy as np

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
    """Exp slope shown as annualised % e.g. +34.2%"""
    return "—" if _nan(v) else f"{v * 100:+.1f}%"

def _fmt_ma_flag(v, _=None):
    if _nan(v):
        return "—"
    return "✓" if int(v) == 1 else "✗"

def _fmt_wpr(v, _=None):
    return "—" if _nan(v) else f"{v:.1f}"

# ── Cell colour helpers ───────────────────────────────────────────────────────

def _score_clr(v):
    if _nan(v):    return CLR_ROW_A
    if v >= 80:    return CLR_GREEN
    if v >= 60:    return CLR_BLUE
    if v <= 30:    return CLR_RED
    return CLR_ROW_A

def _ret_clr(v):
    if _nan(v):       return CLR_ROW_A
    if v > 0.05:      return CLR_GREEN
    if v < -0.05:     return CLR_RED
    return CLR_YELLOW

def _slope_clr(v):
    if _nan(v):    return CLR_ROW_A
    if v > 0.20:   return CLR_GREEN
    if v > 0:      return CLR_BLUE
    if v < -0.10:  return CLR_RED
    return CLR_YELLOW

def _osc_clr(v, lo, hi, good_high=True):
    """Generic oscillator colouring given neutral band."""
    if _nan(v):      return CLR_ROW_A
    if v > hi:       return CLR_GREEN if good_high else CLR_RED
    if v < lo:       return CLR_RED   if good_high else CLR_GREEN
    return CLR_YELLOW

def _ma_flag_clr(v):
    if _nan(v):         return CLR_ROW_A
    return CLR_GREEN if int(v) == 1 else CLR_RED

def _ram_clr(v):
    if _nan(v):    return CLR_ROW_A
    if v > 1.5:    return CLR_GREEN
    if v > 1.0:    return CLR_BLUE
    if v < 0.6:    return CLR_RED
    return CLR_YELLOW


# ── Column definitions ────────────────────────────────────────────────────────
# (header_label, df_field, char_width, formatter, cell_colour_fn)

def _mk_clr(fn):
    """Wrap a colour function so it receives the value."""
    return lambda v, _row: fn(v)

COLUMNS = [
    # Identity
    ("Rank",        "rank",           4,  lambda v, _: str(v),                   None),
    ("Ticker",      "symbol",        10,  lambda v, _: str(v),                   None),
    ("Market",      "market",         6,  lambda v, _: str(v),                   None),
    ("Price",       "price",          9,  _fmt_price,                             None),

    # Composite
    ("Score",       "momentum_score", 6,  lambda v, _: _fmt_num(v, 1),           _mk_clr(_score_clr)),

    # Core signals
    ("RAM Score",   "ram_score",      8,  lambda v, _: _fmt_num(v, 3),           _mk_clr(_ram_clr)),
    ("Exp Slope",   "exp_slope",      9,  _fmt_slope,                            _mk_clr(_slope_clr)),
    ("12-1M Ret",   "ret_12_1",       9,  _fmt_pct,                              _mk_clr(_ret_clr)),
    ("3M Ret",      "ret_3m",         8,  _fmt_pct,                              _mk_clr(_ret_clr)),

    # Oscillators
    ("Stoch %K",    "stoch_k",        8,  lambda v, _: _fmt_num(v, 1),
        lambda v, _: _osc_clr(v, 20, 80)),
    ("Stoch %D",    "stoch_d",        8,  lambda v, _: _fmt_num(v, 1),
        lambda v, _: _osc_clr(v, 20, 80)),
    ("RSI",         "rsi",            6,  lambda v, _: _fmt_num(v, 1),
        lambda v, _: _osc_clr(v, 30, 70)),
    ("CCI",         "cci",            7,  lambda v, _: _fmt_num(v, 0),
        lambda v, _: _osc_clr(v, -100, 100)),
    ("Williams %R", "wpr",            9,  _fmt_wpr,
        lambda v, _: _osc_clr(v, -80, -20, good_high=False)),  # WPR: less neg = bullish

    # Volatility
    ("ATR(15)",     "atr",            7,  lambda v, _: _fmt_num(v, 2),           None),

    # MA flags
    ("MA25",        "above_ma25",     5,  _fmt_ma_flag,                          _mk_clr(_ma_flag_clr)),
    ("MA50",        "above_ma50",     5,  _fmt_ma_flag,                          _mk_clr(_ma_flag_clr)),
    ("MA100",       "above_ma100",    6,  _fmt_ma_flag,                          _mk_clr(_ma_flag_clr)),
    ("MA200",       "above_ma200",    6,  _fmt_ma_flag,                          _mk_clr(_ma_flag_clr)),
]


# ── Main table window ─────────────────────────────────────────────────────────

def show_screener_table(results: dict, title: str = "Momentum Screener — Results"):
    root = tk.Tk()
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
    w, h = min(1600, sw - 60), min(860, sh - 60)
    root.geometry(f"{w}x{h}+30+30")
    root.minsize(900, 450)

    mono     = tkfont.Font(family="Consolas", size=12)
    bold     = tkfont.Font(family="Consolas", size=12, weight="bold")
    hdr_bold = tkfont.Font(family="Consolas", size=16, weight="bold")
    hdr_sub  = tkfont.Font(family="Consolas", size=12)

    # Header
    hdr = tk.Frame(root, bg=CLR_ACCENT, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Momentum Screener",
             bg=CLR_ACCENT, fg="white", font=hdr_bold).pack()
    scored_at = results.get("scored_at", "")
    tk.Label(hdr, text=f"Scored at {scored_at}  ·  Click any column to sort",
             bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub).pack()

    # Tabs
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=6)

    tabs = {"Overall": results.get("overall", pd.DataFrame())}
    for market in ["US", "AU", "NZ", "SG"]:
        bm = results.get("by_market", {})
        if market in bm and not bm[market].empty:
            tabs[market] = bm[market]

    for tab_name, df in tabs.items():
        frame = tk.Frame(notebook, bg=CLR_BG)
        notebook.add(frame, text=f"  {tab_name}  ")
        _build_table(frame, df, mono, bold)

    # Footer
    footer = tk.Frame(root, bg=CLR_BG, pady=5, padx=12)
    footer.pack(fill="x")
    tk.Label(
        footer,
        text=(
            "Score = 9-signal composite (RAM · Exp Slope · 12-1M · 3M · Stoch · RSI · CCI · W%R · MA count)  "
            "·  ATR & MA flags = raw info only"
        ),
        bg=CLR_BG, fg=CLR_SUBTEXT, font=mono,
    ).pack(side="left")
    tk.Button(
        footer, text="✕  Close", bg="#CC3333", fg="white",
        font=bold, relief="flat", padx=12, pady=4,
        cursor="hand2", command=root.destroy,
    ).pack(side="right")

    root.mainloop()


def _build_table(parent: tk.Frame, df: pd.DataFrame, mono, bold):
    if df.empty:
        tk.Label(parent, text="No data for this market.",
                 bg=CLR_BG, fg=CLR_SUBTEXT, font=mono).pack(pady=40)
        return

    df = df.reset_index()
    df.insert(0, "rank", range(1, len(df) + 1))
    if "symbol" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "symbol"})

    # ── Scrollable canvas ─────────────────────────────────────────────────
    outer = tk.Frame(parent, bg=CLR_BG)
    outer.pack(fill="both", expand=True)

    v_scroll = ttk.Scrollbar(outer, orient="vertical")
    h_scroll = ttk.Scrollbar(outer, orient="horizontal")
    v_scroll.pack(side="right", fill="y")
    h_scroll.pack(side="bottom", fill="x")

    canvas = tk.Canvas(outer, bg=CLR_BG, highlightthickness=0,
                       yscrollcommand=v_scroll.set,
                       xscrollcommand=h_scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    v_scroll.config(command=canvas.yview)
    h_scroll.config(command=canvas.xview)

    inner = tk.Frame(canvas, bg=CLR_BG)
    cw    = canvas.create_window((0, 0), window=inner, anchor="nw")

    canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
    inner.bind("<Configure>",  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _scroll(e):
        if e.num == 4:
            canvas.yview_scroll(-1, "units")
        elif e.num == 5:
            canvas.yview_scroll(1, "units")
        else:
            canvas.yview_scroll(int(-e.delta / 60), "units")

    canvas.bind_all("<MouseWheel>", _scroll)
    canvas.bind_all("<Button-4>",   _scroll)
    canvas.bind_all("<Button-5>",   _scroll)

    # ── Sort state ────────────────────────────────────────────────────────
    sort_state  = {"col": "momentum_score", "asc": False}
    row_widgets = []
    hdr_btns    = {}   # field → button widget, for arrow updates

    def _render(data: pd.DataFrame):
        for w in row_widgets:
            w.destroy()
        row_widgets.clear()

        for i, (_, row) in enumerate(data.iterrows()):
            bg_default = CLR_ROW_A if i % 2 == 0 else CLR_ROW_B
            rf = tk.Frame(inner, bg=bg_default)
            rf.pack(fill="x")
            row_widgets.append(rf)

            for label, field, char_w, fmt, clr_fn in COLUMNS:
                val = row.get(field, None)
                if val is not None and isinstance(val, float) and np.isnan(val):
                    val = None

                text    = fmt(val, row) if val is not None else "—"
                cell_bg = clr_fn(val, row) if (clr_fn and val is not None) else bg_default

                fg = CLR_TEXT
                if field == "market":
                    fg = MARKET_COLOURS.get(str(val), CLR_TEXT)
                elif field == "symbol":
                    fg = CLR_ACCENT
                elif field in ("above_ma25", "above_ma50", "above_ma100", "above_ma200"):
                    fg = "#1A7A3A" if (val == 1) else "#991122"

                use_bold = field in ("symbol", "momentum_score")
                anchor   = "w" if field in ("symbol", "market") else "e"

                tk.Label(
                    rf, text=text,
                    font=bold if use_bold else mono,
                    bg=cell_bg, fg=fg,
                    width=char_w, anchor=anchor,
                    padx=5, pady=3, relief="flat",
                ).pack(side="left")

    # ── Header row ────────────────────────────────────────────────────────
    hdr_row = tk.Frame(inner, bg=CLR_HDR_BG)
    hdr_row.pack(fill="x")

    def _make_sort(field):
        def _sort():
            prev_col = sort_state["col"]
            if prev_col == field:
                sort_state["asc"] = not sort_state["asc"]
            else:
                sort_state["col"] = field
                sort_state["asc"] = field in ("rank", "symbol", "market")
            # Update arrows on all buttons
            for f, btn in hdr_btns.items():
                if f == sort_state["col"]:
                    arrow = " ↑" if sort_state["asc"] else " ↓"
                    btn.config(fg="#FFD700")
                else:
                    btn.config(text=btn.cget("text").rstrip(" ↑↓↕") + " ↕", fg=CLR_HDR_FG)
            btn_active = hdr_btns[field]
            arrow = " ↑" if sort_state["asc"] else " ↓"
            lbl   = field  # find original label
            for l, f, *_ in COLUMNS:
                if f == field:
                    lbl = l
                    break
            btn_active.config(text=lbl + arrow)
            _render(df.sort_values(field, ascending=sort_state["asc"], na_position="last"))
        return _sort

    for label, field, char_w, _, __ in COLUMNS:
        arrow = " ↓" if field == "momentum_score" else " ↕"
        btn = tk.Button(
            hdr_row, text=label + arrow,
            font=bold,
            bg=CLR_HDR_BG,
            fg="#FFD700" if field == "momentum_score" else CLR_HDR_FG,
            activebackground="#333355", activeforeground="white",
            relief="flat", padx=5, pady=5,
            cursor="hand2", width=char_w,
            command=_make_sort(field),
        )
        btn.pack(side="left")
        hdr_btns[field] = btn

    # Initial render
    _render(df.sort_values("momentum_score", ascending=False, na_position="last"))
