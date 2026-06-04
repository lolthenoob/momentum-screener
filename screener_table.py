"""
screener_table.py
─────────────────
Interactive Tkinter results table for the momentum screener.

Features:
  · Sortable columns (click header)
  · Mouse-wheel scroll (all platforms)
  · Colour-coded cells
  · Double-buffered rendering to reduce tearing
  · Column widths read from / saved to screener.ini
  · Font size from screener.ini

Columns:
  Rank, Ticker, Market, Price, Score,
  RAM Score, Exp Slope×R², 12-1M Ret, 3M Ret,
  Stoch %K, Stoch %D, RSI, CCI, Williams %R, ATR(15),
  MA25, MA50, MA100, MA200
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
    if _nan(v):           return CLR_ROW_A
    return CLR_GREEN if int(v) == 1 else CLR_RED

def _ram_clr(v):
    if _nan(v):   return CLR_ROW_A
    if v > 1.5:   return CLR_GREEN
    if v > 1.0:   return CLR_BLUE
    if v < 0.6:   return CLR_RED
    return CLR_YELLOW

def _mk(fn):
    return lambda v, _r: fn(v)

# ── Column definitions ────────────────────────────────────────────────────────
# (header, field, default_chars, formatter, colour_fn)

COLUMNS = [
    ("Rank",        "rank",           4,  lambda v, _: str(v),                    None),
    ("Ticker",      "symbol",        10,  lambda v, _: str(v),                    None),
    ("Market",      "market",         6,  lambda v, _: str(v),                    None),
    ("Price",       "price",          9,  _fmt_price,                             None),
    ("Score",       "momentum_score", 6,  lambda v, _: _fmt_num(v, 1),           _mk(_score_clr)),
    ("RAM Score",   "ram_score",      8,  lambda v, _: _fmt_num(v, 3),           _mk(_ram_clr)),
    ("Exp Slope",   "exp_slope",      9,  _fmt_slope,                            _mk(_slope_clr)),
    ("12-1M Ret",   "ret_12_1",       9,  _fmt_pct,                              _mk(_ret_clr)),
    ("3M Ret",      "ret_3m",         8,  _fmt_pct,                              _mk(_ret_clr)),
    ("Stoch %K",    "stoch_k",        8,  lambda v, _: _fmt_num(v, 1),           lambda v, _: _osc_clr(v, 20, 80)),
    ("Stoch %D",    "stoch_d",        8,  lambda v, _: _fmt_num(v, 1),           lambda v, _: _osc_clr(v, 20, 80)),
    ("RSI",         "rsi",            6,  lambda v, _: _fmt_num(v, 1),           lambda v, _: _osc_clr(v, 30, 70)),
    ("CCI",         "cci",            7,  lambda v, _: _fmt_num(v, 0),           lambda v, _: _osc_clr(v, -100, 100)),
    ("Williams %R", "wpr",            9,  lambda v, _: _fmt_num(v, 1),           lambda v, _: _osc_clr(v, -80, -20, good_high=False)),
    ("ATR(15)",     "atr",            7,  lambda v, _: _fmt_num(v, 2),           None),
    ("MA25",        "above_ma25",     5,  _fmt_ma_flag,                          _mk(_ma_flag_clr)),
    ("MA50",        "above_ma50",     5,  _fmt_ma_flag,                          _mk(_ma_flag_clr)),
    ("MA100",       "above_ma100",    6,  _fmt_ma_flag,                          _mk(_ma_flag_clr)),
    ("MA200",       "above_ma200",    6,  _fmt_ma_flag,                          _mk(_ma_flag_clr)),
]

_N_COLS = len(COLUMNS)


# ── Column width persistence ──────────────────────────────────────────────────

def _load_col_widths() -> list[int]:
    raw = config.get("col_widths").strip()
    if raw:
        try:
            widths = [int(x) for x in raw.split(",")]
            if len(widths) == _N_COLS:
                return widths
        except ValueError:
            pass
    return [c[2] for c in COLUMNS]   # defaults


def _save_col_widths(widths: list[int]):
    config.set("col_widths", ",".join(str(w) for w in widths))


# ── Main window ───────────────────────────────────────────────────────────────

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
    w, h   = min(1700, sw - 60), min(880, sh - 60)
    root.geometry(f"{w}x{h}+30+30")
    root.minsize(900, 450)

    fs   = config.get_int("font_size") or 12
    mono = tkfont.Font(family="Consolas", size=fs)
    bold = tkfont.Font(family="Consolas", size=fs, weight="bold")
    hdr_bold = tkfont.Font(family="Consolas", size=16, weight="bold")
    hdr_sub  = tkfont.Font(family="Consolas", size=fs)

    # ── Header ────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=CLR_ACCENT, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Momentum Screener",
             bg=CLR_ACCENT, fg="white", font=hdr_bold).pack()
    scored_at = results.get("scored_at", "")
    tk.Label(hdr,
             text=f"Scored at {scored_at}  ·  Click column header to sort  ·  Drag header edges to resize",
             bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub).pack()

    # ── Notebook tabs ─────────────────────────────────────────────────────
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
        _build_table(frame, df, mono, bold, fs)

    # ── Footer ────────────────────────────────────────────────────────────
    footer = tk.Frame(root, bg=CLR_BG, pady=5, padx=12)
    footer.pack(fill="x")
    tk.Label(
        footer,
        text="Score = RAM · Exp Slope · 12-1M · 3M · Stoch · RSI · CCI · W%R · MA count  |  ATR & MA flags = raw info",
        bg=CLR_BG, fg=CLR_SUBTEXT, font=mono,
    ).pack(side="left")
    tk.Button(footer, text="✕  Close", bg="#CC3333", fg="white",
              font=bold, relief="flat", padx=12, pady=4,
              cursor="hand2", command=root.destroy).pack(side="right")

    root.mainloop()


# ── Table builder ─────────────────────────────────────────────────────────────

def _build_table(parent: tk.Frame, df: pd.DataFrame, mono, bold, fs: int):
    if df.empty:
        tk.Label(parent, text="No data for this market.",
                 bg=CLR_BG, fg=CLR_SUBTEXT, font=mono).pack(pady=40)
        return

    df = df.reset_index()
    df.insert(0, "rank", range(1, len(df) + 1))
    if "symbol" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "symbol"})

    col_widths = _load_col_widths()   # in characters

    # ── Outer layout ──────────────────────────────────────────────────────
    outer = tk.Frame(parent, bg=CLR_BG)
    outer.pack(fill="both", expand=True)

    v_scroll = ttk.Scrollbar(outer, orient="vertical")
    h_scroll = ttk.Scrollbar(outer, orient="horizontal")
    v_scroll.pack(side="right",  fill="y")
    h_scroll.pack(side="bottom", fill="x")

    canvas = tk.Canvas(outer, bg=CLR_BG, highlightthickness=0,
                       yscrollcommand=v_scroll.set,
                       xscrollcommand=h_scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    v_scroll.config(command=canvas.yview)
    h_scroll.config(command=canvas.xview)

    inner = tk.Frame(canvas, bg=CLR_BG)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_canvas_resize(e):
        canvas.itemconfig(win_id, width=max(e.width, inner.winfo_reqwidth()))
    canvas.bind("<Configure>", _on_canvas_resize)

    def _on_inner_resize(e):
        canvas.configure(scrollregion=canvas.bbox("all"))
    inner.bind("<Configure>", _on_inner_resize)

    # ── Mouse-wheel scroll (Windows, macOS, Linux) ────────────────────────
    def _on_mousewheel(e):
        if e.num == 4:        # Linux scroll up
            canvas.yview_scroll(-1, "units")
        elif e.num == 5:      # Linux scroll down
            canvas.yview_scroll(1, "units")
        else:                 # Windows / macOS
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    # Bind to canvas AND the inner frame so it always captures
    for widget in (canvas, inner):
        widget.bind("<MouseWheel>", _on_mousewheel)
        widget.bind("<Button-4>",   _on_mousewheel)
        widget.bind("<Button-5>",   _on_mousewheel)

    # ── Sort state ────────────────────────────────────────────────────────
    sort_state = {"col": "momentum_score", "asc": False}
    hdr_btns   = {}

    # ── Header row with resizable columns ─────────────────────────────────
    hdr_row = tk.Frame(inner, bg=CLR_HDR_BG)
    hdr_row.pack(fill="x", side="top")

    # We use a Frame-per-column approach with a resize handle on the right edge
    hdr_col_frames = []

    def _make_sort_cmd(field):
        def _cmd():
            if sort_state["col"] == field:
                sort_state["asc"] = not sort_state["asc"]
            else:
                sort_state["col"]  = field
                sort_state["asc"]  = field in ("rank", "symbol", "market")
            for f, btn in hdr_btns.items():
                lbl = next(c[0] for c in COLUMNS if c[1] == f)
                if f == sort_state["col"]:
                    arrow = " ↑" if sort_state["asc"] else " ↓"
                    btn.config(text=lbl + arrow, fg="#FFD700")
                else:
                    btn.config(text=lbl + " ↕", fg=CLR_HDR_FG)
            _render(df.sort_values(sort_state["col"],
                                   ascending=sort_state["asc"],
                                   na_position="last"))
        return _cmd

    for i, (label, field, _default_w, _fmt, _clr) in enumerate(COLUMNS):
        cw = col_widths[i]
        cf = tk.Frame(hdr_row, bg=CLR_HDR_BG, width=cw * (fs - 2))
        cf.pack_propagate(False)
        cf.pack(side="left")
        hdr_col_frames.append(cf)

        arrow = " ↓" if field == "momentum_score" else " ↕"
        fg    = "#FFD700" if field == "momentum_score" else CLR_HDR_FG
        btn   = tk.Button(cf, text=label + arrow, font=bold,
                          bg=CLR_HDR_BG, fg=fg,
                          activebackground="#333355",
                          activeforeground="white",
                          relief="flat", padx=4, pady=5,
                          cursor="hand2",
                          command=_make_sort_cmd(field))
        btn.pack(fill="both", expand=True)
        hdr_btns[field] = btn

        # Resize handle (3px strip on right edge of each header cell)
        handle = tk.Frame(cf, bg="#444466", width=3, cursor="sb_h_double_arrow")
        handle.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        def _start_resize(e, idx=i, frame=cf):
            frame._drag_start_x = e.x_root
            frame._drag_start_w = frame.winfo_width()

        def _do_resize(e, idx=i, frame=cf):
            delta    = e.x_root - frame._drag_start_x
            new_w    = max(30, frame._drag_start_w + delta)
            frame.config(width=new_w)
            col_widths[idx] = max(1, new_w // (fs - 2))
            _save_col_widths(col_widths)

        handle.bind("<ButtonPress-1>",   _start_resize)
        handle.bind("<B1-Motion>",        _do_resize)

    # ── Data rows (rebuilt on sort) ───────────────────────────────────────
    row_container = tk.Frame(inner, bg=CLR_BG)
    row_container.pack(fill="x", side="top")

    row_frames = []

    def _render(data: pd.DataFrame):
        # Destroy old rows
        for rf in row_frames:
            rf.destroy()
        row_frames.clear()

        for i, (_, row) in enumerate(data.iterrows()):
            bg_def = CLR_ROW_A if i % 2 == 0 else CLR_ROW_B
            rf = tk.Frame(row_container, bg=bg_def)
            rf.pack(fill="x")
            row_frames.append(rf)

            # Bind mouse-wheel to each row frame too
            rf.bind("<MouseWheel>", _on_mousewheel)
            rf.bind("<Button-4>",   _on_mousewheel)
            rf.bind("<Button-5>",   _on_mousewheel)

            for j, (label, field, _dw, fmt, clr_fn) in enumerate(COLUMNS):
                cw  = col_widths[j]
                val = row.get(field, None)
                if val is not None and isinstance(val, float) and np.isnan(val):
                    val = None

                text    = fmt(val, row) if val is not None else "—"
                cell_bg = clr_fn(val, row) if (clr_fn and val is not None) else bg_def

                fg = CLR_TEXT
                if field == "market":
                    fg = MARKET_COLOURS.get(str(val), CLR_TEXT)
                elif field == "symbol":
                    fg = CLR_ACCENT
                elif field in ("above_ma25", "above_ma50", "above_ma100", "above_ma200"):
                    if val is not None:
                        fg = "#1A7A3A" if int(val) == 1 else "#991122"

                use_bold = field in ("symbol", "momentum_score")
                anchor   = "w" if field in ("symbol", "market") else "e"

                cell = tk.Frame(rf, bg=cell_bg,
                                width=cw * (fs - 2), height=fs + 10)
                cell.pack_propagate(False)
                cell.pack(side="left")

                lbl = tk.Label(cell, text=text,
                               font=bold if use_bold else mono,
                               bg=cell_bg, fg=fg,
                               anchor=anchor, padx=4, pady=2)
                lbl.pack(fill="both", expand=True)

                # Forward scroll events from labels too
                lbl.bind("<MouseWheel>", _on_mousewheel)
                lbl.bind("<Button-4>",   _on_mousewheel)
                lbl.bind("<Button-5>",   _on_mousewheel)

        canvas.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

    # Initial render
    _render(df.sort_values("momentum_score", ascending=False, na_position="last"))

