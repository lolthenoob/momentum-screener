"""
screener_table.py
─────────────────
Interactive Tkinter results table for the momentum screener.

Frozen left columns: Rank + Ticker only (never scroll horizontally).
All other columns including Name scroll right with the data.
Scrollable header row stays pinned above data, synced to xscroll.
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

def _mk(fn):
    return lambda v, _r: fn(v)

# ── Column definitions ────────────────────────────────────────────────────────
# (header, field, default_chars, formatter, colour_fn, frozen)
# frozen=True → Rank + Ticker pane, never scrolls horizontally

COLUMNS = [
    ("Rank",        "rank",           4,  lambda v, _: str(v),               None,             True),
    ("Ticker",      "symbol",        10,  lambda v, _: str(v),               None,             True),
    ("Name",        "name",          20,  lambda v, _: str(v) if v else "—", None,             False),
    ("Market",      "market",         6,  lambda v, _: str(v),               None,             False),
    ("Price",       "price",          9,  _fmt_price,                        None,             False),
    ("Score",       "momentum_score", 6,  lambda v, _: _fmt_num(v, 1),      _mk(_score_clr),  False),
    ("RAM Score",   "ram_score",      8,  lambda v, _: _fmt_num(v, 3),      _mk(_ram_clr),    False),
    ("Exp Slope",   "exp_slope",      9,  _fmt_slope,                        _mk(_slope_clr),  False),
    ("12-1M Ret",   "ret_12_1",       9,  _fmt_pct,                          _mk(_ret_clr),    False),
    ("3M Ret",      "ret_3m",         8,  _fmt_pct,                          _mk(_ret_clr),    False),
    ("Stoch %K",    "stoch_k",        8,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, 20, 80),   False),
    ("Stoch %D",    "stoch_d",        8,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, 20, 80),   False),
    ("RSI",         "rsi",            6,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, 30, 70),   False),
    ("CCI",         "cci",            7,  lambda v, _: _fmt_num(v, 0),      lambda v, _: _osc_clr(v, -100, 100),False),
    ("Williams %R", "wpr",            9,  lambda v, _: _fmt_num(v, 1),      lambda v, _: _osc_clr(v, -80, -20, good_high=False), False),
    ("ATR(15)",     "atr",            7,  lambda v, _: _fmt_num(v, 2),      None,             False),
    ("MA25",        "above_ma25",     5,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
    ("MA50",        "above_ma50",     5,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
    ("MA100",       "above_ma100",    6,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
    ("MA200",       "above_ma200",    6,  _fmt_ma_flag,                      _mk(_ma_flag_clr),False),
]

FROZEN_COLS = [c for c in COLUMNS if     c[5]]
SCROLL_COLS = [c for c in COLUMNS if not c[5]]
_N_COLS     = len(COLUMNS)

# ── Column width helpers ──────────────────────────────────────────────────────

def _load_col_widths() -> list:
    raw = config.get("col_widths").strip()
    if raw:
        try:
            w = [int(x) for x in raw.split(",")]
            if len(w) == _N_COLS:
                return w
        except ValueError:
            pass
    return [c[2] for c in COLUMNS]

def _save_col_widths(widths: list):
    config.set("col_widths", ",".join(str(w) for w in widths))

def _col_px(char_w: int, fs: int) -> int:
    return max(30, char_w * (fs - 2))


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
    if config.get_bool("auto_resize"):
        scale = config.font_size() / 12
        w = min(int(1700 * scale), sw - 60)
        h = min(int(880  * scale), sh - 60)
    else:
        w = min(config.get_int("table_w") or 1600, sw - 60)
        h = min(config.get_int("table_h") or 860,  sh - 60)
    root.geometry(f"{w}x{h}+30+30")
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
    tk.Label(footer,
             text="Score = RAM · Exp Slope · 12-1M · 3M · Stoch · RSI · CCI · W%R · MA count  |  ATR & MA flags = raw info",
             bg=CLR_BG, fg=CLR_SUBTEXT, font=mono).pack(side="left")
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
    if "name" not in df.columns:
        df["name"] = ""

    col_widths = _load_col_widths()

    def px(col_idx):
        return _col_px(col_widths[col_idx], fs)

    row_h = fs + max(6, fs // 2)
    hdr_h = fs + max(8, fs // 2) + max(4, fs // 3) * 2   # approximate header button height

    # ─────────────────────────────────────────────────────────────────────
    # Layout (all packed into `outer`):
    #
    #   [v_scroll on right]
    #   [h_scroll on bottom]
    #   [frozen_pane | divider | scroll_pane]
    #
    # frozen_pane (side="left", fill="y"):
    #   frozen_hdr   ← plain Frame, always visible, no scroll
    #   frozen_canvas← vertical scroll only
    #
    # scroll_pane (side="left", fill="both", expand=True):
    #   scroll_hdr   ← plain Frame, clips to viewport width, shifted via place
    #   scroll_canvas← vertical + horizontal scroll
    # ─────────────────────────────────────────────────────────────────────

    outer = tk.Frame(parent, bg=CLR_BG)
    outer.pack(fill="both", expand=True)

    v_scroll = ttk.Scrollbar(outer, orient="vertical")
    v_scroll.pack(side="right", fill="y")

    h_scroll = ttk.Scrollbar(outer, orient="horizontal")
    h_scroll.pack(side="bottom", fill="x")

    # ── Frozen pane ───────────────────────────────────────────────────────
    frozen_pane = tk.Frame(outer, bg=CLR_HDR_BG)
    frozen_pane.pack(side="left", fill="y")

    # Fixed-height frozen header (exact height set after fonts known)
    frozen_hdr = tk.Frame(frozen_pane, bg=CLR_HDR_BG, height=hdr_h)
    frozen_hdr.pack(side="top", fill="x")
    frozen_hdr.pack_propagate(False)

    frozen_canvas = tk.Canvas(frozen_pane, bg=CLR_BG, highlightthickness=0,
                              yscrollcommand=v_scroll.set)
    frozen_canvas.pack(side="top", fill="both", expand=True)

    frozen_inner = tk.Frame(frozen_canvas, bg=CLR_BG)
    frozen_win   = frozen_canvas.create_window((0, 0), window=frozen_inner, anchor="nw")

    def _frozen_inner_resize(e):
        frozen_canvas.configure(scrollregion=frozen_canvas.bbox("all"))
    frozen_inner.bind("<Configure>", _frozen_inner_resize)

    # Thin divider between panes
    tk.Frame(outer, bg="#444466", width=2).pack(side="left", fill="y")

    # ── Scroll pane ───────────────────────────────────────────────────────
    scroll_pane = tk.Frame(outer, bg=CLR_BG)
    scroll_pane.pack(side="left", fill="both", expand=True)

    # Scroll header: a viewport Frame that clips its child.
    # Child (scroll_hdr_inner) is wider than the viewport and shifted via place().
    scroll_hdr_vp = tk.Frame(scroll_pane, bg=CLR_HDR_BG, height=hdr_h)
    scroll_hdr_vp.pack(side="top", fill="x")
    scroll_hdr_vp.pack_propagate(False)   # must not grow to child width

    scroll_hdr_inner = tk.Frame(scroll_hdr_vp, bg=CLR_HDR_BG)
    scroll_hdr_inner.place(x=0, y=0, height=hdr_h)

    scroll_canvas = tk.Canvas(scroll_pane, bg=CLR_BG, highlightthickness=0,
                              yscrollcommand=v_scroll.set,
                              xscrollcommand=h_scroll.set)
    scroll_canvas.pack(side="top", fill="both", expand=True)

    scroll_inner = tk.Frame(scroll_canvas, bg=CLR_BG)
    scroll_win   = scroll_canvas.create_window((0, 0), window=scroll_inner, anchor="nw")

    def _scroll_inner_resize(e):
        scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
    scroll_inner.bind("<Configure>", _scroll_inner_resize)

    def _scroll_canvas_resize(e):
        scroll_canvas.itemconfig(scroll_win,
                                 width=max(e.width, scroll_inner.winfo_reqwidth()))
    scroll_canvas.bind("<Configure>", _scroll_canvas_resize)

    # ── Shared scroll wiring ──────────────────────────────────────────────

    def _yview(*args):
        frozen_canvas.yview(*args)
        scroll_canvas.yview(*args)

    def _xview(*args):
        scroll_canvas.xview(*args)
        # Shift the header inner frame to match data canvas x position
        try:
            frac   = scroll_canvas.xview()[0]
            total  = scroll_inner.winfo_reqwidth()
            scroll_hdr_inner.place_configure(x=-int(frac * total))
        except Exception:
            pass

    v_scroll.config(command=_yview)
    h_scroll.config(command=_xview)

    # ── Mouse-wheel ───────────────────────────────────────────────────────
    def _on_mw(e):
        delta = -1 if e.num == 4 else (1 if e.num == 5 else int(-e.delta / 120))
        frozen_canvas.yview_scroll(delta, "units")
        scroll_canvas.yview_scroll(delta, "units")

    for w in (frozen_canvas, frozen_inner, scroll_canvas, scroll_inner,
              frozen_hdr, scroll_hdr_vp, scroll_hdr_inner):
        w.bind("<MouseWheel>", _on_mw)
        w.bind("<Button-4>",   _on_mw)
        w.bind("<Button-5>",   _on_mw)

    # ── Sort state ────────────────────────────────────────────────────────
    sort_state   = {"col": "momentum_score", "asc": False}
    all_hdr_btns = {}

    def _refresh_arrows():
        for f, btn in all_hdr_btns.items():
            lbl = next(c[0] for c in COLUMNS if c[1] == f)
            if f == sort_state["col"]:
                btn.config(text=lbl + (" ↑" if sort_state["asc"] else " ↓"), fg="#FFD700")
            else:
                btn.config(text=lbl + " ↕", fg=CLR_HDR_FG)

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

        arrow = " ↓" if field == "momentum_score" else " ↕"
        fg    = "#FFD700" if field == "momentum_score" else CLR_HDR_FG
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
            f._dx = e.x_root;  f._dw = f.winfo_width()

        def _drag(e, idx=col_idx, f=cf):
            new_w = max(30, f._dw + (e.x_root - f._dx))
            f.config(width=new_w)
            col_widths[idx] = max(1, new_w // (fs - 2))
            _save_col_widths(col_widths)

        handle.bind("<ButtonPress-1>", _start)
        handle.bind("<B1-Motion>",     _drag)

    # Build frozen header cells
    for col in FROZEN_COLS:
        _make_hdr_cell(frozen_hdr, col, COLUMNS.index(col))

    # Build scroll header cells
    for col in SCROLL_COLS:
        _make_hdr_cell(scroll_hdr_inner, col, COLUMNS.index(col))

    # After header cells are packed, fix the actual rendered height
    frozen_hdr.update_idletasks()
    real_hdr_h = frozen_hdr.winfo_reqheight()
    if real_hdr_h > 0:
        frozen_hdr.configure(height=real_hdr_h)
        scroll_hdr_vp.configure(height=real_hdr_h)
        scroll_hdr_inner.place_configure(height=real_hdr_h)

    # ── Data cell factory ─────────────────────────────────────────────────
    def _make_cell(parent, field, val, col_idx, bg_def, row):
        _, _, _dw, fmt, clr_fn, _frozen = COLUMNS[col_idx]
        w = px(col_idx)

        if isinstance(val, float) and np.isnan(val):
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
        anchor   = "w" if field in ("symbol", "name", "market") else "e"

        cell = tk.Frame(parent, bg=cell_bg, width=w, height=row_h)
        cell.pack_propagate(False)
        cell.pack(side="left")

        lbl = tk.Label(cell, text=text,
                       font=bold if use_bold else mono,
                       bg=cell_bg, fg=fg,
                       anchor=anchor, padx=4, pady=max(2, fs // 6))
        lbl.pack(fill="both", expand=True)
        lbl.bind("<MouseWheel>", _on_mw)
        lbl.bind("<Button-4>",   _on_mw)
        lbl.bind("<Button-5>",   _on_mw)

    # ── Data render ───────────────────────────────────────────────────────
    frozen_rows = []
    scroll_rows = []

    def _render(data: pd.DataFrame):
        for rf in frozen_rows:
            rf.destroy()
        for rf in scroll_rows:
            rf.destroy()
        frozen_rows.clear()
        scroll_rows.clear()

        for i, (_, row) in enumerate(data.iterrows()):
            bg = CLR_ROW_A if i % 2 == 0 else CLR_ROW_B

            frf = tk.Frame(frozen_inner, bg=bg)
            frf.pack(fill="x")
            frozen_rows.append(frf)
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                frf.bind(ev, _on_mw)

            for col in FROZEN_COLS:
                _make_cell(frf, col[1], row.get(col[1]), COLUMNS.index(col), bg, row)

            srf = tk.Frame(scroll_inner, bg=bg)
            srf.pack(fill="x")
            scroll_rows.append(srf)
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                srf.bind(ev, _on_mw)

            for col in SCROLL_COLS:
                _make_cell(srf, col[1], row.get(col[1]), COLUMNS.index(col), bg, row)

        frozen_canvas.update_idletasks()
        frozen_canvas.configure(scrollregion=frozen_canvas.bbox("all"))
        scroll_canvas.update_idletasks()
        scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

    _render(df.sort_values("momentum_score", ascending=False, na_position="last"))