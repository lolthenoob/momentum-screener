"""
Momentum Screener — main.py
════════════════════════════════════════════════════════════════════
Launcher + status panel.
"""

import os
import threading
import tkinter as tk
from tkinter import font as tkfont, messagebox
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

import config
from ticker_loader import load_all_tickers, ticker_count
from momentum_calc  import (download_prices, run_screener,
                            cache_data_age_days, cache_signals_age_days,
                            load_signals, save_signals,
                            clear_price_cache, clear_signal_cache)
from screener_table import show_screener_table
from watchlist_picker import build_watchlist_panel

# ── Colours ───────────────────────────────────────────────────────────────────
CLR_ACCENT  = "#00A4EF"
CLR_BG      = "#F7F9FC"
CLR_TEXT    = "#1A1A2E"
CLR_SUBTEXT = "#555577"
CLR_BTN_FG  = "#FFFFFF"
CLR_WARN    = "#CC7700"
HDR_BOLD_SZ = 18
HDR_SUB_SZ  = 13


# ── Preferences overlay (no Toplevel — avoids Win32 crash) ───────────────────

def _show_prefs(root, on_save=None):
    """
    Renders a modal-like preferences panel as a Frame placed over the root
    window. No Toplevel created, so no Win32 system-menu crash.
    Full-size (like About), split into left (settings) and right (columns) panes.
    """
    from screener_table import COLUMNS, FROZEN_COLS, SCROLL_COLS

    fs      = config.font_size()
    f       = tkfont.Font(family="Consolas", size=fs)
    fb      = tkfont.Font(family="Consolas", size=fs, weight="bold")
    small_f = tkfont.Font(family="Consolas", size=max(8, fs - 1))
    title_f = tkfont.Font(family="Consolas", size=fs + 2, weight="bold")

    backdrop = tk.Frame(root, bg="#000000")
    backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)

    MARGIN = 24
    card = tk.Frame(backdrop, bg=CLR_BG,
                    highlightthickness=1, highlightbackground="#AAAACC")
    card.place(x=MARGIN, y=MARGIN, relwidth=1.0, relheight=1.0,
               width=-MARGIN * 2, height=-MARGIN * 2)

    # ── Title ─────────────────────────────────────────────────────────────
    tk.Label(card, text="Preferences", bg=CLR_BG, fg=CLR_TEXT,
             font=title_f).grid(row=0, column=0, columnspan=3,
                                padx=20, pady=(16, 8), sticky="w")
    tk.Frame(card, bg="#DDDDDD", height=1).grid(
        row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 8))

    # ── Two-column layout: left = settings, divider, right = columns ──────
    card.rowconfigure(2, weight=1)
    card.columnconfigure(0, weight=0)   # left settings pane — fixed
    card.columnconfigure(1, weight=0)   # divider
    card.columnconfigure(2, weight=1)   # right columns pane — expands

    left_pane = tk.Frame(card, bg=CLR_BG)
    left_pane.grid(row=2, column=0, sticky="nsew", padx=(16, 0), pady=(0, 0))

    tk.Frame(card, bg="#DDDDDD", width=1).grid(
        row=2, column=1, sticky="ns", padx=12, pady=4)

    right_pane = tk.Frame(card, bg=CLR_BG)
    right_pane.grid(row=2, column=2, sticky="nsew", padx=(0, 16), pady=(0, 0))
    right_pane.rowconfigure(1, weight=1)
    right_pane.columnconfigure(0, weight=1)

    # ── LEFT: General settings ────────────────────────────────────────────
    simple_fields = [
        ("Font size (8–24):",  "font_size"),
        ("Top N per market:",  "top_n"),
    ]
    size_fields = [
        ("Launcher width (px):",        "launcher_w"),
        ("Launcher height (px):",       "launcher_h"),
        ("Results table width (px):",   "table_w"),
        ("Results table height (px):",  "table_h"),
    ]

    vars_   = {}
    entries = {}
    lrow    = 0

    tk.Label(left_pane, text="General", bg=CLR_BG, fg=CLR_SUBTEXT,
             font=small_f).grid(row=lrow, column=0, columnspan=2,
                                sticky="w", pady=(0, 4))
    lrow += 1

    for label, key in simple_fields:
        tk.Label(left_pane, text=label, bg=CLR_BG, fg=CLR_TEXT,
                 font=fb, anchor="w", width=26).grid(
            row=lrow, column=0, pady=5, sticky="w")
        v = tk.StringVar(value=config.get(key))
        tk.Entry(left_pane, textvariable=v, font=f, width=8,
                 relief="flat", highlightthickness=1,
                 highlightbackground="#CCCCCC").grid(row=lrow, column=1, padx=(8, 0))
        vars_[key] = v
        lrow += 1

    tk.Frame(left_pane, bg="#DDDDDD", height=1).grid(
        row=lrow, column=0, columnspan=2, sticky="ew", pady=(8, 4))
    lrow += 1

    auto_resize_var = tk.BooleanVar(value=config.get_bool("auto_resize"))
    tk.Checkbutton(
        left_pane, text="Auto-resize windows to font size",
        variable=auto_resize_var, bg=CLR_BG, fg=CLR_TEXT, font=fb,
        activebackground=CLR_BG, selectcolor=CLR_BG,
        relief="flat", bd=0, cursor="hand2",
    ).grid(row=lrow, column=0, columnspan=2, sticky="w", pady=(0, 4))
    lrow += 1

    for label, key in size_fields:
        tk.Label(left_pane, text=label, bg=CLR_BG, fg=CLR_TEXT,
                 font=fb, anchor="w", width=26).grid(
            row=lrow, column=0, pady=4, sticky="w")
        v = tk.StringVar(value=config.get(key))
        e = tk.Entry(left_pane, textvariable=v, font=f, width=8,
                     relief="flat", highlightthickness=1,
                     highlightbackground="#CCCCCC")
        e.grid(row=lrow, column=1, padx=(8, 0))
        vars_[key]   = v
        entries[key] = e
        lrow += 1

    def _update_size_fields(*_):
        state = "disabled" if auto_resize_var.get() else "normal"
        fg    = CLR_SUBTEXT if auto_resize_var.get() else CLR_TEXT
        for key in [k for _, k in size_fields]:
            entries[key].config(state=state, fg=fg)

    auto_resize_var.trace_add("write", _update_size_fields)
    _update_size_fields()

    tk.Label(left_pane, text="Column widths reset when font size changes.",
             bg=CLR_BG, fg=CLR_SUBTEXT, font=small_f).grid(
        row=lrow, column=0, columnspan=2, pady=(6, 0), sticky="w")

    # ── RIGHT: Column visibility + ordering ───────────────────────────────
    tk.Label(right_pane, text="Result table columns  (scroll columns only — Rank and Ticker always shown)",
             bg=CLR_BG, fg=CLR_SUBTEXT, font=small_f).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

    # list_frame holds the scrollable column list
    list_frame = tk.Frame(right_pane, bg=CLR_BG,
                          highlightthickness=1, highlightbackground="#CCCCCC")
    list_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
    list_frame.rowconfigure(0, weight=1)
    list_frame.columnconfigure(0, weight=1)

    list_canvas = tk.Canvas(list_frame, bg=CLR_BG, highlightthickness=0)
    list_sb     = tk.Scrollbar(list_frame, orient="vertical",
                               command=list_canvas.yview)
    list_canvas.configure(yscrollcommand=list_sb.set)
    list_canvas.grid(row=0, column=0, sticky="nsew")
    list_sb.grid(row=0, column=1, sticky="ns")

    inner = tk.Frame(list_canvas, bg=CLR_BG)
    list_canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))

    # Build working list: order from config, hidden from config
    _hidden  = config.get_hidden_cols()
    _order   = config.get_col_order()
    # All scroll column tuples
    _all_scroll = list(SCROLL_COLS)
    # Apply saved order
    if _order:
        _field_map  = {c[1]: c for c in _all_scroll}
        _ordered    = [_field_map[f] for f in _order if f in _field_map]
        _remaining  = [c for c in _all_scroll if c[1] not in set(_order)]
        _working    = _ordered + _remaining
    else:
        _working = list(_all_scroll)

    # State: list of [col_tuple, visible_BooleanVar] in current order
    col_states = [[c, tk.BooleanVar(value=c[1] not in _hidden)] for c in _working]

    row_frames = []

    def _rebuild_list():
        for rf in row_frames:
            rf.destroy()
        row_frames.clear()

        for i, (col, vis_var) in enumerate(col_states):
            rf = tk.Frame(inner, bg=CLR_BG)
            rf.pack(fill="x", pady=1)
            row_frames.append(rf)

            # Up/down buttons
            btn_up = tk.Button(rf, text="▲", font=small_f,
                               bg=CLR_BG, fg=CLR_TEXT, relief="flat",
                               cursor="hand2", padx=2, pady=0,
                               command=lambda idx=i: _move(idx, -1))
            btn_up.pack(side="left")
            btn_dn = tk.Button(rf, text="▼", font=small_f,
                               bg=CLR_BG, fg=CLR_TEXT, relief="flat",
                               cursor="hand2", padx=2, pady=0,
                               command=lambda idx=i: _move(idx, +1))
            btn_dn.pack(side="left")

            # Visibility checkbox
            cb = tk.Checkbutton(rf, variable=vis_var,
                                bg=CLR_BG, activebackground=CLR_BG,
                                selectcolor=CLR_BG, relief="flat", bd=0,
                                cursor="hand2")
            cb.pack(side="left", padx=(4, 0))

            # Column name label
            tk.Label(rf, text=col[0], font=small_f if vis_var.get() else f,
                     bg=CLR_BG,
                     fg=CLR_TEXT if vis_var.get() else CLR_SUBTEXT,
                     anchor="w").pack(side="left", padx=4)

            # Field name in grey
            tk.Label(rf, text=f"({col[1]})", font=small_f,
                     bg=CLR_BG, fg="#AAAAAA", anchor="w").pack(side="left")

    def _move(idx: int, direction: int):
        new_idx = idx + direction
        if 0 <= new_idx < len(col_states):
            col_states[idx], col_states[new_idx] = col_states[new_idx], col_states[idx]
            _rebuild_list()

    _rebuild_list()

    # Mousewheel on the inner canvas
    def _mw(e):
        delta = -1 if e.num == 4 else (1 if e.num == 5 else int(-e.delta / 120))
        list_canvas.yview_scroll(delta, "units")
    list_canvas.bind("<MouseWheel>", _mw)
    list_canvas.bind("<Button-4>",   _mw)
    list_canvas.bind("<Button-5>",   _mw)
    inner.bind("<MouseWheel>", _mw)
    inner.bind("<Button-4>",   _mw)
    inner.bind("<Button-5>",   _mw)

    # Up/down buttons column on the right
    btn_col = tk.Frame(right_pane, bg=CLR_BG)
    btn_col.grid(row=1, column=1, sticky="n", padx=(6, 0))

    # ── Dismiss / Save ────────────────────────────────────────────────────
    tk.Frame(card, bg="#DDDDDD", height=1).grid(
        row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 0))

    def _dismiss():
        backdrop.destroy()

    def _save():
        old_fs = config.font_size()
        config._set("auto_resize", auto_resize_var.get())
        for key, v in vars_.items():
            if key in [k for _, k in size_fields] and auto_resize_var.get():
                continue
            raw = v.get().strip()
            if raw:
                try:
                    config._set(key, int(raw))
                except ValueError:
                    pass
        if config.font_size() != old_fs:
            config.clear_col_widths()

        # Save column visibility and order
        new_hidden = {c[1] for c, vis in col_states if not vis.get()}
        new_order  = [c[1] for c, _ in col_states]
        config.set_hidden_cols(new_hidden)
        config.set_col_order(new_order)

        _dismiss()
        if on_save:
            on_save()

    bf = tk.Frame(card, bg=CLR_BG)
    bf.grid(row=4, column=0, columnspan=3, pady=12)
    tk.Button(bf, text="Save", bg=CLR_ACCENT, fg="white",
              font=fb, relief="flat", padx=14, pady=6,
              cursor="hand2", command=_save).pack(side="left", padx=6)
    tk.Button(bf, text="Cancel", bg="#888888", fg="white",
              font=fb, relief="flat", padx=14, pady=6,
              cursor="hand2", command=_dismiss).pack(side="left")

    # Click outside card to dismiss
    backdrop.bind("<Button-1>", lambda e: _dismiss() if e.widget is backdrop else None)


# ── About overlay ─────────────────────────────────────────────────────────────

def _show_about(root):
    """
    Modal-like About / methodology panel rendered as a Frame over the root
    window — same pattern as _show_prefs, no Toplevel created.
    """
    fs      = config.font_size()
    f       = tkfont.Font(family="Consolas", size=fs)
    fb      = tkfont.Font(family="Consolas", size=fs, weight="bold")
    title_f = tkfont.Font(family="Consolas", size=fs + 2, weight="bold")
    small_f = tkfont.Font(family="Consolas", size=max(8, fs - 1))

    backdrop = tk.Frame(root, bg="#000000")
    backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)

    MARGIN = 24
    card = tk.Frame(backdrop, bg=CLR_BG,
                    highlightthickness=1, highlightbackground="#AAAACC")
    card.place(x=MARGIN, y=MARGIN, relwidth=1.0, relheight=1.0,
               width=-MARGIN * 2, height=-MARGIN * 2)

    # ── Title row ─────────────────────────────────────────────────────────
    tk.Label(card, text="About — How It Works", bg=CLR_BG, fg=CLR_TEXT,
             font=title_f).grid(row=0, column=0, padx=20, pady=(16, 6), sticky="w")
    tk.Frame(card, bg="#DDDDDD", height=1).grid(
        row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

    # ── Scrollable text area ───────────────────────────────────────────────
    text_frame = tk.Frame(card, bg=CLR_BG)
    text_frame.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="nsew")
    card.rowconfigure(2, weight=1)
    card.columnconfigure(0, weight=1)

    txt = tk.Text(
        text_frame,
        font=small_f, bg=CLR_BG, fg=CLR_TEXT,
        relief="flat", wrap="word",
        highlightthickness=0,
        cursor="arrow", padx=4,
    )
    sb = tk.Scrollbar(text_frame, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)

    # Block editing but allow keyboard scroll and copy
    txt.bind("<Key>", lambda e: "break"
             if e.keysym not in ("c", "C", "Up", "Down", "Prior", "Next")
             or (e.keysym in ("c", "C") and not (e.state & 0x4))
             else None)

    # ── Tag styles ────────────────────────────────────────────────────────
    txt.tag_configure("h1",    font=fb,      foreground=CLR_ACCENT)
    txt.tag_configure("h2",    font=fb,      foreground=CLR_TEXT)
    txt.tag_configure("body",  font=small_f, foreground=CLR_TEXT)
    txt.tag_configure("sub",   font=small_f, foreground=CLR_SUBTEXT)
    txt.tag_configure("warn",  font=small_f, foreground="#CC7700")
    txt.tag_configure("rule",  font=small_f, foreground="#CCCCCC")

    def ins(text, tag="body"):
        txt.insert("end", text, tag)

    # ── Content ───────────────────────────────────────────────────────────
    ins("Momentum Screener\n", "h1")
    ins("Ranks stocks across US, AU, NZ, SG, and MY markets by a composite\n"
        "momentum score built from 9 technical signals.\n\n", "sub")

    ins("─" * 60 + "\n", "rule")
    ins("DATA SOURCES\n", "h2")
    ins("─" * 60 + "\n", "rule")
    ins(
        "  US   NYSE + NASDAQ full list — NASDAQ screener CSV (local)\n"
        "       + NYSE list from GitHub (datasets/nyse-other-listings).\n"
        "  AU   ASX listed companies — CSV downloaded from asx.com.au,\n"
        "       or ASX 200 from Wikipedia if no CSV is present.\n"
        "  NZ   NZSX equity list — scraped live from nzx.com.\n"
        "  SG   Full SGX list — scraped from stockanalysis.com.\n"
        "       Cross-listed HK/China codes are excluded.\n"
        "  MY   Bursa Malaysia (KLSE) — parsed from official Bursa PDF\n"
        "       in the data/ folder, or scraped from stockanalysis.com.\n\n"
        "  Ticker lists are cached locally for 7 days.\n"
        "  Price history (2 years) is fetched from Yahoo Finance\n"
        "  and stored in a local SQLite database (data/momentum.db).\n\n",
        "body",
    )

    ins("─" * 60 + "\n", "rule")
    ins("THE 9 SIGNALS\n", "h2")
    ins("─" * 60 + "\n", "rule")
    ins(
        "Each signal is rank-normalised across the full universe\n"
        "to a 0–100 percentile before being averaged. A score of 85\n"
        "means the stock ranked in the 85th percentile on average\n"
        "across all signals — not that any raw value equalled 85.\n\n",
        "sub",
    )

    signals = [
        ("1. Risk-Adj Momentum (RAM)",
         "12-1 month return divided by annualised volatility,\n"
         "   then z-scored and mapped to 0–100. Rewards stocks\n"
         "   with strong returns relative to how much they swing."),
        ("2. Exp Regression Slope",
         "Annualised slope of a log-price regression over the last\n"
         "   90 days, scaled by R². Captures steady, consistent\n"
         "   uptrends — a high R² matters as much as the slope."),
        ("3. 12-1 Month Return",
         "Price return from 12 months ago to 1 month ago (skipping\n"
         "   the most recent month to avoid short-term reversal).\n"
         "   The classic academic momentum factor."),
        ("4. 3-Month Return",
         "Price return over the last 63 trading days. Confirms\n"
         "   that recent shorter-term trend agrees with the 12-1M."),
        ("5. Stochastic %K (14)",
         "Where the current price sits within the 14-day high/low\n"
         "   range, expressed as a percentage (0 = at the low,\n"
         "   100 = at the high)."),
        ("6. RSI (14)",
         "Relative Strength Index over 14 days. Measures the\n"
         "   speed and size of recent up-moves vs down-moves.\n"
         "   Higher = stronger recent buying pressure."),
        ("7. CCI (14)",
         "Commodity Channel Index over 14 days. Measures how\n"
         "   far price has deviated from its recent average,\n"
         "   scaled by typical daily variation."),
        ("8. Williams %R (14)",
         "Inverted stochastic — distance from current price to\n"
         "   the 14-day high, as a negative percentage. Ranked\n"
         "   inversely so that less negative = higher score."),
        ("9. MA Score (0–4)",
         "Count of moving averages (25, 50, 100, 200-day) that\n"
         "   the current price is trading above. 4 = above all\n"
         "   four; 0 = below all four."),
    ]

    for name, desc in signals:
        ins(f"\n  {name}\n", "h2")
        ins(f"   {desc}\n", "body")

    ins("\n", "body")
    ins("─" * 60 + "\n", "rule")
    ins("COMPOSITE SCORE\n", "h2")
    ins("─" * 60 + "\n", "rule")
    ins(
        "  momentum_score = mean of the 9 rank-normalised signals\n\n"
        "  All signals are weighted equally. Williams %R is the only\n"
        "  signal ranked inversely (lower raw value = stronger signal).\n"
        "  Tickers with fewer than 30 days of price history are excluded.\n"
        "  The 12-1M signal requires at least 252 days of history.\n\n",
        "body",
    )

    ins("─" * 60 + "\n", "rule")
    ins("DISPLAY COLUMNS (not in composite score)\n", "h2")
    ins("─" * 60 + "\n", "rule")
    ins(
        "  ATR (15)     Average True Range over 15 days — volatility context.\n"
        "  MA25/50/     Tick or cross flags showing which moving averages\n"
        "  100/200      the stock is currently trading above or below.\n\n",
        "body",
    )

    ins("─" * 60 + "\n", "rule")
    ins("WHAT THIS SCREENER DOES NOT DO\n", "h2")
    ins("─" * 60 + "\n", "rule")
    ins(
        "  · No fundamental screening (P/E, earnings, revenue).\n"
        "  · No volume filter — low-liquidity stocks can appear.\n"
        "  · No earnings calendar — scores can reflect pre/post-\n"
        "    earnings gaps rather than sustained momentum.\n"
        "  · Scores are relative within each run's universe.\n"
        "    Re-running on a different market selection will\n"
        "    produce different scores for the same stock.\n\n",
        "warn",
    )

    ins("─" * 60 + "\n", "rule")
    ins("CACHING\n", "h2")
    ins("─" * 60 + "\n", "rule")
    ins(
        "  Ticker lists    JSON files in data/, refreshed every 7 days.\n"
        "  Price history   SQLite rows in data/momentum.db, fetched on\n"
        "                  demand when 'Download latest prices' is ticked.\n"
        "  Signal cache    Scored results persisted to momentum.db after\n"
        "                  every compute run. Subsequent runs load instantly\n"
        "                  unless 'Force recompute' is ticked.\n",
        "body",
    )

    txt.config(state="disabled")

    # ── Close button ──────────────────────────────────────────────────────
    tk.Frame(card, bg="#DDDDDD", height=1).grid(
        row=3, column=0, sticky="ew", padx=16, pady=(0, 4))

    def _dismiss():
        backdrop.destroy()

    tk.Button(card, text="Close", bg=CLR_ACCENT, fg="white",
              font=fb, relief="flat", padx=14, pady=6,
              cursor="hand2", command=_dismiss).grid(
        row=4, column=0, pady=(0, 12))

    backdrop.bind("<Button-1>", lambda e: _dismiss() if e.widget is backdrop else None)
    root.bind("<Escape>", lambda e: _dismiss())


# ── Launcher ──────────────────────────────────────────────────────────────────

def launch():
    root = tk.Tk()
    root.title("📈 Momentum Screener")
    root.configure(bg=CLR_BG)
    root.resizable(True, True)

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()

    def _apply_launcher_size():
        base_w = 900
        base_h = 850

        if config.get_bool("auto_resize"):
            fs    = config.font_size()
            scale = fs / 12
            w = min(int(base_w * scale), sw - 40)
            h = min(int(base_h * scale), sh - 40)
        else:
            w = min(config.get_int("launcher_w") or base_w, sw - 40)
            h = min(config.get_int("launcher_h") or base_h, sh - 40)
        sh_usable = sh - 48  # 48px = standard Windows taskbar height
        h = min(h, sh_usable)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh_usable - h) // 2}")
        fs_now = config.font_size()
        root.minsize(max(600, int(base_w * fs_now / 12)),
                     max(400, int(base_h * fs_now / 12)))

    _apply_launcher_size()

    # ── Font factory ──────────────────────────────────────────────────────
    _fonts = {}

    def _make_fonts():
        fs = config.font_size()
        _fonts["mono"]     = tkfont.Font(family="Consolas", size=fs)
        _fonts["bold"]     = tkfont.Font(family="Consolas", size=fs, weight="bold")
        _fonts["hdr_bold"] = tkfont.Font(family="Consolas", size=HDR_BOLD_SZ, weight="bold")
        _fonts["hdr_sub"]  = tkfont.Font(family="Consolas", size=HDR_SUB_SZ)
        _fonts["tick"]     = tkfont.Font(family="Segoe UI Symbol", size=fs + 0)

    _make_fonts()
    mono     = lambda: _fonts["mono"]
    bold     = lambda: _fonts["bold"]
    hdr_bold = lambda: _fonts["hdr_bold"]
    hdr_sub  = lambda: _fonts["hdr_sub"]
    tick_f   = lambda: _fonts["tick"]

    # ── Panels ────────────────────────────────────────────────────────────
    launcher_panel = tk.Frame(root, bg=CLR_BG)
    status_panel   = tk.Frame(root, bg=CLR_BG)
    results_panel  = tk.Frame(root, bg=CLR_BG)

    # ── Custom menu bar (frame-based so font scales with config) ──────────
    _last_results = {"data": None}

    menubar_frame = tk.Frame(root, bg="#E8EDF4", bd=0, relief="flat")
    menubar_frame.pack(fill="x", side="top")

    _open_popup = {"widget": None, "btn": None}

    def _close_open_popup():
        if _open_popup["widget"] and _open_popup["widget"].winfo_exists():
            _open_popup["widget"].place_forget()
            _open_popup["widget"].destroy()
        if _open_popup["btn"] and _open_popup["btn"].winfo_exists():
            _open_popup["btn"].config(bg="#E8EDF4", fg=CLR_TEXT)
        _open_popup["widget"] = None
        _open_popup["btn"]    = None

    def _make_menu_btn(label, items):
        btn = tk.Label(
            menubar_frame, text=label,
            font=bold(), bg="#E8EDF4", fg=CLR_TEXT,
            padx=12, pady=4, cursor="hand2",
        )
        btn.pack(side="left")

        def _show_dropdown(e=None):
            if _open_popup["btn"] is btn:
                _close_open_popup()
                return
            _close_open_popup()

            # Build dropdown as a plain Frame placed on root — no Toplevel
            popup = tk.Frame(root, bg="#E8EDF4",
                             highlightthickness=1,
                             highlightbackground="#BBBBCC")

            for item in items:
                if item is None:
                    tk.Frame(popup, bg="#CCCCCC", height=1).pack(
                        fill="x", padx=6, pady=2)
                else:
                    item_label, item_cmd = item
                    def _make_cmd(cmd):
                        def _run(e=None):
                            _close_open_popup()
                            cmd()
                        return _run
                    row = tk.Label(
                        popup, text=item_label,
                        font=bold(), bg="#E8EDF4", fg=CLR_TEXT,
                        anchor="w", padx=16, pady=5, cursor="hand2",
                    )
                    row.pack(fill="x")
                    _cmd = _make_cmd(item_cmd)
                    row.bind("<Button-1>", _cmd)
                    row.bind("<Enter>", lambda e, r=row: r.config(bg=CLR_ACCENT, fg="white"))
                    row.bind("<Leave>", lambda e, r=row: r.config(bg="#E8EDF4", fg=CLR_TEXT))

            # Position below the menu button, relative to root
            root.update_idletasks()
            bx = btn.winfo_rootx() - root.winfo_rootx()
            by = btn.winfo_rooty() - root.winfo_rooty() + btn.winfo_height()
            popup.place(x=bx, y=by)
            popup.lift()

            def _arm_dismiss():
                def _on_click_outside(e):
                    if not _open_popup["widget"]:
                        return
                    try:
                        pw = _open_popup["widget"]
                        if not pw.winfo_exists():
                            _close_open_popup()
                            return
                        pw.update_idletasks()
                        wx = pw.winfo_rootx() - root.winfo_rootx()
                        wy = pw.winfo_rooty() - root.winfo_rooty()
                        ww, wh = pw.winfo_width(), pw.winfo_height()
                        ex = e.x_root - root.winfo_rootx()
                        ey = e.y_root - root.winfo_rooty()
                        if not (wx <= ex <= wx + ww and wy <= ey <= wy + wh):
                            _close_open_popup()
                    except Exception:
                        _close_open_popup()

                if _open_popup["widget"] and _open_popup["widget"].winfo_exists():
                    _dismiss_id = root.bind("<ButtonPress-1>", _on_click_outside, "+")

                    def _cleanup_dismiss(e=None, _id=_dismiss_id):
                        try:
                            root.unbind("<ButtonPress-1>", _id)
                        except Exception:
                            pass

                    _open_popup["widget"].bind("<Destroy>", _cleanup_dismiss)

            root.after_idle(_arm_dismiss)

            btn.config(bg=CLR_ACCENT, fg="white")
            _open_popup["widget"] = popup
            _open_popup["btn"]    = btn

        btn.bind("<Button-1>", _show_dropdown)
        btn.bind("<Enter>", lambda e: btn.config(bg=CLR_ACCENT, fg="white")
                 if _open_popup["btn"] is not btn else None)
        btn.bind("<Leave>", lambda e: btn.config(bg="#E8EDF4", fg=CLR_TEXT)
                 if _open_popup["btn"] is not btn else None)
        return btn

    def _clear_price_cache_cmd():
        if not messagebox.askyesno(
            "Clear price cache",
            "Delete all cached price data?\n\n"
            "The next run will need 'Download latest prices' ticked to rebuild it.",
        ):
            return
        n, err = clear_price_cache()
        if err:
            messagebox.showerror("Error", f"Failed to clear price cache:\n{err}")
        else:
            messagebox.showinfo("Done", f"Price cache cleared ({n:,} rows deleted).\n\n"
                                        "Tick 'Download latest prices' on the next run.")
        _build_launcher()

    def _clear_signal_cache_cmd():
        if not messagebox.askyesno(
            "Clear signal cache",
            "Delete all cached momentum signals?\n\n"
            "The next run will recompute signals from existing price data.",
        ):
            return
        n, err = clear_signal_cache()
        if err:
            messagebox.showerror("Error", f"Failed to clear signal cache:\n{err}")
        else:
            messagebox.showinfo("Done", f"Signal cache cleared ({n:,} rows deleted).\n\n"
                                        "The next run will recompute from scratch.")
        _build_launcher()

    def _open_output_folder():
        import subprocess, sys
        out_dir = config.output_dir()
        try:
            if sys.platform == "win32":
                os.startfile(out_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", out_dir])
            else:
                subprocess.Popen(["xdg-open", out_dir])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}")

    _make_menu_btn("File", [
        ("Clear price cache",   _clear_price_cache_cmd),
        ("Clear signal cache",  _clear_signal_cache_cmd),
        None,
        ("Open output folder",  _open_output_folder),
        None,
        ("Exit", root.destroy),
    ])
    _make_menu_btn("Edit", [
        ("Preferences\u2026", lambda: _show_prefs(root, _on_prefs_saved)),
    ])
    _make_menu_btn("Help", [
        ("About / How it works", lambda: _show_about(root)),
    ])

    # ── Header ────────────────────────────────────────────────────────────
    def _make_header(parent):
        hdr = tk.Frame(parent, bg=CLR_ACCENT, pady=max(4, config.font_size() // 2))
        hdr.pack(fill="x")
        tk.Label(hdr, text="Momentum Screener",
                 bg=CLR_ACCENT, fg="white", font=hdr_bold()).pack()
        tk.Label(hdr, text="US · AU · NZ · SG · MY",
                 bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub()).pack()

    # ── Toggle helper ─────────────────────────────────────────────────────
    def _make_toggle(frame, label, var):
        container = tk.Frame(frame, bg=CLR_BG)
        container.pack(fill="x", pady=max(1, config.font_size() // 6))
        btn = tk.Button(container, text="☐", font=tick_f(),
                        fg="#AAAAAA", bg=CLR_BG, activebackground=CLR_BG,
                        relief="flat", bd=0, cursor="hand2")
        btn.pack(side="left")
        tk.Label(container, text=label, bg=CLR_BG,
                 fg=CLR_TEXT, font=bold()).pack(side="left")
        def _toggle():
            var.set(not var.get())
            btn.config(text="☑" if var.get() else "☐",
                       fg=CLR_ACCENT if var.get() else "#AAAAAA")
        btn.config(command=_toggle)
        return btn

    # ── Option vars ───────────────────────────────────────────────────────
    top_n_var          = tk.StringVar(value=str(config.get_int("top_n") or 50))
    download_var       = tk.BooleanVar(value=False)
    force_signals_var  = tk.BooleanVar(value=False)
    tickers_var        = tk.BooleanVar(value=False)
    export_var         = tk.BooleanVar(value=config.get_bool("export_csv"))
    rank_mode_var      = tk.StringVar(value=config.get("rank_mode") or "normal")

    # ── Watchlist vars (persistence only — picker owns download/export/rank) ──
    watchlist_tickers_var   = tk.StringVar(value=config.get("watchlist_tickers") or "")
    watchlist_rank_mode_var = tk.StringVar(value=config.get("watchlist_rank_mode") or "normal")
    active_tab_var          = tk.StringVar(value="screener")

    _active = config.get_active_markets()
    market_vars = {
        "US": tk.BooleanVar(value="US" in _active),
        "AU": tk.BooleanVar(value="AU" in _active),
        "NZ": tk.BooleanVar(value="NZ" in _active),
        "SG": tk.BooleanVar(value="SG" in _active),
        "MY": tk.BooleanVar(value="MY" in _active),
    }
    MARKET_LABELS     = {"US": "US  (NYSE + NASDAQ)", "AU": "AU  (ASX)", "NZ": "NZ  (NZX)", "SG": "SG  (SGX)", "MY": "MY  (Bursa / KLSE)"}
    MARKET_COLOURS_UI = {"US": "#00A4EF", "AU": "#10B981", "NZ": "#8B5CF6", "SG": "#F59E0B", "MY": "#EF4444"}

    # ── Build launcher content ────────────────────────────────────────────
    def _build_screener_pane(parent):
        fs = config.font_size()
        pad_x = max(12, fs * 2)
        pad_y = max(6,  fs // 2)

        info_frame = tk.Frame(parent, bg=CLR_BG, padx=pad_x, pady=pad_y)
        info_frame.pack(fill="x")

        for label, val in [
            ("Universe",  "NYSE + NASDAQ · ASX · NZX · SGX · Bursa Malaysia"),
            ("Signals",   "RAM · Exp Slope · 12-1M · 3M · Stoch · RSI · CCI · W%R · MA"),
            ("Output",    f"Top {top_n_var.get()} per market + overall leaderboard"),
            ("Cache",     "Results loaded from local cache unless boxes ticked below"),
        ]:
            row = tk.Frame(info_frame, bg=CLR_BG)
            row.pack(fill="x", pady=max(0, fs // 8))
            tk.Label(row, text=f"{label:<12}", font=bold(),
                     bg=CLR_BG, fg=CLR_SUBTEXT, anchor="w", width=14).pack(side="left")
            tk.Label(row, text=val, font=mono(),
                     bg=CLR_BG, fg=CLR_TEXT, anchor="w").pack(side="left")

        tk.Frame(parent, bg="#DDDDDD", height=1).pack(fill="x", padx=pad_x, pady=(max(4, fs // 3), 0))

        # ── Market selector ───────────────────────────────────────────────
        mkt_frame = tk.Frame(parent, bg=CLR_BG, padx=pad_x, pady=pad_y)
        mkt_frame.pack(fill="x")

        mkt_hdr_row = tk.Frame(mkt_frame, bg=CLR_BG)
        mkt_hdr_row.pack(fill="x")
        tk.Label(mkt_hdr_row, text="Markets (Togglable):", bg=CLR_BG, fg=CLR_SUBTEXT,
                 font=bold(), anchor="w").pack(side="left")

        mkt_btns = {}

        def _update_run_btn(*_):
            any_on = any(v.get() for v in market_vars.values())
            run_btn.config(state="normal" if any_on else "disabled",
                           bg=CLR_ACCENT if any_on else "#AAAAAA")

        def _toggle_all_markets():
            all_on = all(v.get() for v in market_vars.values())
            new_state = not all_on
            for mkt, v in market_vars.items():
                v.set(new_state)
                clr = MARKET_COLOURS_UI[mkt]
                mkt_btns[mkt].config(
                    text="☑" if new_state else "☐",
                    fg=clr if new_state else "#AAAAAA",
                )
            _update_run_btn()

        toggle_all_btn = tk.Button(
            mkt_hdr_row, text="Select All / None",
            font=bold(), bg="#E8EDF4", fg=CLR_TEXT,
            activebackground=CLR_ACCENT, activeforeground="white",
            relief="flat", bd=0, padx=8, pady=2, cursor="hand2",
            command=_toggle_all_markets,
        )
        toggle_all_btn.pack(side="right")

        for mkt, var in market_vars.items():
            clr  = MARKET_COLOURS_UI[mkt]
            lbl  = MARKET_LABELS[mkt]

            row = tk.Frame(mkt_frame, bg=CLR_BG)
            row.pack(fill="x", pady=max(1, fs // 6))

            def _make_mkt_toggle(v=var, m=mkt, c=clr):
                def _toggle():
                    v.set(not v.get())
                    on = v.get()
                    mkt_btns[m].config(
                        text="☑" if on else "☐",
                        fg=c      if on else "#AAAAAA",
                    )
                    _update_run_btn()
                return _toggle

            on  = var.get()
            chk = tk.Button(row, text="☑" if on else "☐",
                            font=tick_f(),
                            fg=clr if on else "#AAAAAA",
                            bg=CLR_BG, activebackground=CLR_BG,
                            relief="flat", bd=0, cursor="hand2",
                            command=_make_mkt_toggle())
            chk.pack(side="left")
            mkt_btns[mkt] = chk
            tk.Label(row, text=lbl, bg=CLR_BG, fg=CLR_TEXT,
                     font=bold()).pack(side="left")

        tk.Frame(parent, bg="#DDDDDD", height=1).pack(fill="x", padx=pad_x, pady=(max(4, fs // 3), 0))

        opt_frame = tk.Frame(parent, bg=CLR_BG, padx=pad_x, pady=pad_y)
        opt_frame.pack(fill="x")

        # Top N
        top_row = tk.Frame(opt_frame, bg=CLR_BG)
        top_row.pack(fill="x", pady=max(1, fs // 6))
        tk.Label(top_row, text="Top N per market:", bg=CLR_BG,
                 fg=CLR_TEXT, font=bold()).pack(side="left")
        tk.Entry(top_row, textvariable=top_n_var, font=mono(), width=6,
                 relief="flat", highlightthickness=1,
                 highlightcolor=CLR_ACCENT,
                 highlightbackground="#CCCCCC").pack(side="left", padx=8)
        tk.Label(top_row, text="(saved to preferences)",
                 bg=CLR_BG, fg=CLR_SUBTEXT, font=mono()).pack(side="left")

        _make_toggle(opt_frame, "Download latest prices",                     download_var)
        _make_toggle(opt_frame, "Force recompute momentum signals",           force_signals_var)
        _make_toggle(opt_frame, "Refresh ticker lists (ignore weekly cache)", tickers_var)
        _make_toggle(opt_frame, "Export results to CSV after run",            export_var)

        # Ranking mode
        rank_row = tk.Frame(opt_frame, bg=CLR_BG)
        rank_row.pack(fill="x", pady=max(1, fs // 6))
        tk.Label(rank_row, text="Rank by:", bg=CLR_BG,
                 fg=CLR_TEXT, font=bold()).pack(side="left")

        _rank_btns = {}
        _rank_modes = [("normal", "Normal momentum"),
                       ("weekly", "Weekly momentum"),
                       ("both",   "Both")]

        def _select_rank_mode(chosen):
            rank_mode_var.set(chosen)
            for val, btn in _rank_btns.items():
                btn.config(text="☑" if val == chosen else "☐",
                           fg=CLR_ACCENT if val == chosen else "#AAAAAA")

        for mode_val, mode_lbl in _rank_modes:
            cell = tk.Frame(rank_row, bg=CLR_BG)
            cell.pack(side="left", padx=(10, 0))
            is_on = rank_mode_var.get() == mode_val
            btn = tk.Button(cell, text="☑" if is_on else "☐",
                            font=tick_f(),
                            fg=CLR_ACCENT if is_on else "#AAAAAA",
                            bg=CLR_BG, activebackground=CLR_BG,
                            relief="flat", bd=0, cursor="hand2",
                            command=lambda v=mode_val: _select_rank_mode(v))
            btn.pack(side="left")
            tk.Label(cell, text=mode_lbl, bg=CLR_BG, fg=CLR_TEXT,
                     font=bold(), cursor="hand2").pack(side="left")
            cell.bind("<Button-1>", lambda e, v=mode_val: _select_rank_mode(v))
            _rank_btns[mode_val] = btn

        # Cache age info
        age_frame = tk.Frame(parent, bg=CLR_BG, padx=pad_x)
        age_frame.pack(fill="x")

        price_age   = cache_data_age_days()
        signals_age = cache_signals_age_days()

        if price_age is None:
            p_txt, p_clr = "⚠  No cached price data — tick 'Download latest prices' before first run.", CLR_WARN
        elif price_age == 0:
            p_txt, p_clr = "✓  Price data last downloaded today.", "#1A7A3A"
        elif price_age == 1:
            p_txt, p_clr = "✓  Price data last downloaded yesterday.", "#1A7A3A"
        else:
            p_txt = f"ℹ  Price data last downloaded {price_age} days ago."
            p_clr = CLR_SUBTEXT

        if signals_age is None:
            s_txt, s_clr = "⚠  No cached signals — tick 'Download latest prices' to run for the first time.", CLR_WARN
        elif signals_age == 0:
            s_txt, s_clr = "✓  Signals last computed today — Run will load instantly.", "#1A7A3A"
        elif signals_age == 1:
            s_txt, s_clr = "ℹ  Signals last computed yesterday.", CLR_SUBTEXT
        else:
            s_txt = f"ℹ  Signals last computed {signals_age} days ago."
            s_clr = CLR_SUBTEXT if signals_age < 14 else CLR_WARN

        tk.Label(age_frame, text=p_txt, bg=CLR_BG, fg=p_clr, font=bold()).pack(anchor="w", pady=(0, max(1, fs // 6)))
        tk.Label(age_frame, text=s_txt, bg=CLR_BG, fg=s_clr, font=bold()).pack(anchor="w", pady=(0, max(2, fs // 4)))

        tk.Frame(parent, bg="#DDDDDD", height=1).pack(fill="x", padx=pad_x, pady=(0, max(2, fs // 6)))

        btn_frame = tk.Frame(parent, bg=CLR_BG, padx=pad_x, pady=max(4, fs // 3))
        btn_frame.pack(fill="x")
        cfg = dict(font=bold(), relief="flat", bd=0, padx=max(8, fs), pady=max(4, fs // 2), cursor="hand2")
        run_btn = tk.Button(btn_frame, text="▶  Run Screener",
                            bg=CLR_ACCENT, fg=CLR_BTN_FG,
                            activebackground="#0082C8",
                            command=_go, **cfg)
        run_btn.pack(side="right")
        tk.Button(btn_frame, text="✕  Exit",
                  bg="#CC3333", fg=CLR_BTN_FG,
                  activebackground="#AA2222",
                  command=root.destroy, **cfg).pack(side="right", padx=(0, 8))
        _update_run_btn()

    def _build_watchlist_pane(parent):
        # Delegate entirely to watchlist_picker — the panel builds itself
        # inside *parent* and calls back here when the user hits Run.
        def _on_run(tickers, do_download, do_export, rank_mode):
            if not tickers:
                return
            # Persist for next launch
            watchlist_tickers_var.set(", ".join(tickers))
            config._set("watchlist_tickers",   ", ".join(tickers))
            config._set("watchlist_rank_mode", rank_mode)
            watchlist_rank_mode_var.set(rank_mode)
            _switch_to_status()
            threading.Thread(
                target=_run_watchlist,
                args=(tickers, do_download, do_export, rank_mode),
                daemon=True,
            ).start()

        build_watchlist_panel(
            parent       = parent,
            root         = root,
            fonts        = {
                "mono":     mono(),
                "bold":     bold(),
                "tick":     tick_f(),
                "hdr_bold": hdr_bold(),
                "hdr_sub":  hdr_sub(),
            },
            colors       = {
                "bg":      CLR_BG,
                "accent":  CLR_ACCENT,
                "text":    CLR_TEXT,
                "subtext": CLR_SUBTEXT,
                "btn_fg":  CLR_BTN_FG,
                "row_a":   "#FFFFFF",
                "row_b":   "#EFF4FA",
                "warn":    CLR_WARN,
            },
            on_run_cb        = _on_run,
            saved_tickers    = watchlist_tickers_var.get(),
            saved_rank_mode  = watchlist_rank_mode_var.get(),
        )

    def _build_launcher():
        for w in launcher_panel.winfo_children():
            w.destroy()

        _make_header(launcher_panel)

        fs = config.font_size()

        # ── Tab strip ─────────────────────────────────────────────────────
        tab_strip = tk.Frame(launcher_panel, bg="#D8E4F0", bd=0)
        tab_strip.pack(fill="x")

        _tab_btns = {}
        tab_content = tk.Frame(launcher_panel, bg=CLR_BG)
        tab_content.pack(fill="both", expand=True)
        tab_content.pack_propagate(False)  # prevent children from shrinking the window

        screener_pane  = tk.Frame(tab_content, bg=CLR_BG)
        watchlist_pane = tk.Frame(tab_content, bg=CLR_BG)

        _watchlist_built = [False]

        def _show_tab(name):
            active_tab_var.set(name)
            for n, btn in _tab_btns.items():
                if n == name:
                    btn.config(bg=CLR_BG, fg=CLR_ACCENT)
                else:
                    btn.config(bg="#D8E4F0", fg=CLR_SUBTEXT)
            if name == "screener":
                watchlist_pane.pack_forget()
                screener_pane.pack(fill="both", expand=True)
            else:
                screener_pane.pack_forget()
                watchlist_pane.pack(fill="both", expand=True)
                if not _watchlist_built[0]:
                    _watchlist_built[0] = True
                    _build_watchlist_pane(watchlist_pane)

        for tab_id, tab_label in [("screener", "  Screener  "), ("watchlist", "  Watchlist  ")]:
            btn = tk.Button(tab_strip, text=tab_label,
                            font=bold(), relief="flat", bd=0,
                            padx=6, pady=max(4, fs // 3),
                            cursor="hand2",
                            command=lambda n=tab_id: _show_tab(n))
            btn.pack(side="left")
            _tab_btns[tab_id] = btn

        tk.Frame(tab_strip, bg="#D8E4F0").pack(side="left", fill="x", expand=True)

        _build_screener_pane(screener_pane)
        _show_tab(active_tab_var.get())



    # ── Status panel (built once) ─────────────────────────────────────────
    _make_header(status_panel)

    status_sub_var = tk.StringVar(value="Starting…")
    status_sub_lbl = tk.Label(status_panel, textvariable=status_sub_var,
                               bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub())

    log_outer = tk.Frame(status_panel, bg=CLR_BG, padx=20, pady=10)
    log_outer.pack(fill="both", expand=True)

    log_text = tk.Text(log_outer, font=mono(),
                       bg="white", fg=CLR_TEXT,
                       relief="flat", wrap="word",
                       highlightthickness=1,
                       highlightbackground="#CCCCCC",
                       cursor="arrow")
    log_text.bind("<Key>",
                  lambda e: "break" if e.keysym not in ("c","C")
                  or not (e.state & 0x4) else None)
    log_scroll = tk.Scrollbar(log_outer, command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_scroll.pack(side="right", fill="y")
    log_text.pack(fill="both", expand=True)

    bottom_bar = tk.Frame(status_panel, bg=CLR_BG, pady=10, padx=20)
    bottom_bar.pack(fill="x")

    run_again_btn = tk.Button(bottom_bar, text="↺  Run Again",
                               bg=CLR_ACCENT, fg="white",
                               font=bold(), relief="flat",
                               padx=14, pady=7, cursor="hand2")
    exit_btn = tk.Button(bottom_bar, text="✕  Exit",
                          bg="#CC3333", fg="white",
                          font=bold(), relief="flat",
                          padx=14, pady=7, cursor="hand2",
                          command=root.destroy)

    # ── Panel switchers ───────────────────────────────────────────────────
    def _switch_to_status():
        launcher_panel.pack_forget()
        status_panel.pack(fill="both", expand=True)
        status_sub_lbl.pack()
        run_again_btn.pack_forget()
        exit_btn.pack(side="right")

    def _switch_to_launcher():
        results_panel.pack_forget()
        status_panel.pack_forget()
        status_sub_lbl.pack_forget()
        log_text.delete("1.0", "end")
        status_sub_var.set("Starting…")
        download_var.set(False)
        force_signals_var.set(False)
        tickers_var.set(False)
        export_var.set(config.get_bool("export_csv"))
        try:
            root.state("normal")
        except tk.TclError:
            try:
                root.attributes("-zoomed", False)
            except tk.TclError:
                pass
        _apply_launcher_size()
        menubar_frame.pack_forget()
        menubar_frame.pack(fill="x", side="top")
        _build_launcher()
        launcher_panel.pack(fill="both", expand=True)

    run_again_btn.config(command=_switch_to_launcher)

    def _show_results_inline(res, rank_mode="normal"):
        status_panel.pack_forget()
        menubar_frame.pack_forget()
        for w in results_panel.winfo_children():
            w.destroy()
        try:
            root.state("zoomed")
        except tk.TclError:
            try:
                root.attributes("-zoomed", True)
            except tk.TclError:
                pass
        show_screener_table(res, parent_frame=results_panel, on_close=_switch_to_launcher,
                            rank_mode=rank_mode)
        results_panel.pack(fill="both", expand=True)

    def _on_prefs_saved():
        _make_fonts()
        _apply_launcher_size()
        # Rebuild custom menu bar so button font reflects new size
        for w in menubar_frame.winfo_children():
            w.destroy()
        _make_menu_btn("File", [
            ("Clear price cache",   _clear_price_cache_cmd),
            ("Clear signal cache",  _clear_signal_cache_cmd),
            None,
            ("Open output folder",  _open_output_folder),
            None,
            ("Exit", root.destroy),
        ])
        _make_menu_btn("Edit", [
            ("Preferences…", lambda: _show_prefs(root, _on_prefs_saved)),
        ])
        _make_menu_btn("Help", [
            ("About / How it works", lambda: _show_about(root)),
        ])
        _build_launcher()

    # ── Logging ───────────────────────────────────────────────────────────
    def _log(msg: str):
        try:
            if not log_text.winfo_exists():
                return
            log_text.insert("end", msg + "\n")
            log_text.see("end")
            log_text.update_idletasks()
        except Exception:
            pass

    def _set_subtitle(text: str):
        try:
            status_sub_var.set(text)
            root.update_idletasks()
        except Exception:
            pass

    # ── CSV export ────────────────────────────────────────────────────────
    def _do_export(results: dict):
        try:
            out_dir = config.output_dir()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            overall = results.get("overall")
            if overall is not None and not overall.empty:
                p = os.path.join(out_dir, f"momentum_overall_{ts}.csv")
                overall.to_csv(p)
                _log(f"  ✓ Exported overall → {p}")
            for market, df in results.get("by_market", {}).items():
                if df is not None and not df.empty:
                    p = os.path.join(out_dir, f"momentum_{market}_{ts}.csv")
                    df.to_csv(p)
                    _log(f"  ✓ Exported {market} → {p}")
            _log(f"  CSV files saved to: {out_dir}")
        except Exception as e:
            _log(f"  ✗ Export failed: {e}")

    # ── Runner ────────────────────────────────────────────────────────────
    def _go():
        try:
            top_n = max(1, int(top_n_var.get()))
        except ValueError:
            top_n = config.get_int("top_n") or 50
        config._set("top_n", top_n)
        config._set("export_csv", export_var.get())
        config._set("rank_mode", rank_mode_var.get())
        selected_markets = [m for m, v in market_vars.items() if v.get()]
        config.set_active_markets(selected_markets)
        _switch_to_status()
        threading.Thread(
            target=_run_screener,
            args=(top_n, download_var.get(), force_signals_var.get(),
                  tickers_var.get(), export_var.get(), selected_markets,
                  rank_mode_var.get()),
            daemon=True,
        ).start()

    def _run_screener(top_n, do_download, force_signals, force_tickers, do_export, selected_markets, rank_mode="normal"):
        try:
            _set_subtitle("Loading ticker lists…")
            _log("─" * 55)
            _log("STEP 1 — Ticker lists")
            _log("─" * 55)
            market_tickers = load_all_tickers(force_refresh=force_tickers, log=_log)
            market_tickers = {m: t for m, t in market_tickers.items() if m in selected_markets}
            total = ticker_count(market_tickers)
            _log(f"\n  Active markets: {', '.join(market_tickers.keys())}")
            _log(f"  Total universe: {total} tickers across {len(market_tickers)} markets")

            # ── Fast path: load cached signals, skip download + recompute ──
            if not do_download and not force_signals:
                _log("\n" + "─" * 55)
                _log("STEP 2 — Loading cached signals")
                _log("─" * 55)
                _set_subtitle("Loading cached signals…")
                results = load_signals(market_tickers, top_n=top_n, rank_mode=rank_mode, log=_log)

                if results:
                    _last_results["data"] = results
                    if do_export:
                        _log("\n" + "─" * 55)
                        _log("STEP 3 — Exporting CSV")
                        _log("─" * 55)
                        _do_export(results)
                    _set_subtitle("Done — loading results…")
                    _log("\n" + "─" * 55)
                    _log(f"  ✓ Loaded cached signals (scored at {results['scored_at']})")
                    _log("  Opening results table…")
                    _log("─" * 55)
                    root.after(0, lambda: run_again_btn.pack(side="left"))
                    root.after(200, lambda: _show_results_inline(results, rank_mode))
                    return
                else:
                    _log("  ⚠  No cached signals found — will download and compute.")
                    do_download   = True
                    force_signals = True

            # ── Full path: download and/or recompute ───────────────────────
            _log("\n" + "─" * 55)
            _log("STEP 2 — Price data")
            _log("─" * 55)

            if do_download:
                _set_subtitle(f"Downloading prices ({total} tickers)…")
                _log("  Downloading latest prices…")
            else:
                _set_subtitle("Loading prices from DB…")
                _log("  Loading prices from local DB (no download requested)…")

            prices = download_prices(market_tickers, force_refresh=do_download, log=_log)
            _log(f"\n  Price matrix: {prices.shape[1]} tickers × {prices.shape[0]} trading days")

            _set_subtitle("Computing momentum scores…")
            _log("\n" + "─" * 55)
            _log("STEP 3 — Momentum scoring")
            _log("─" * 55)
            results = run_screener(market_tickers, prices, top_n=top_n,
                                   min_turnovers=config.get_all_min_turnovers(),
                                   rank_mode=rank_mode, log=_log)

            if not results:
                _log("\n  ✗ No results — check price data above.")
                _set_subtitle("Failed — no results")
                root.after(0, lambda: run_again_btn.pack(side="left"))
                return

            _last_results["data"] = results

            if do_export:
                _log("\n" + "─" * 55)
                _log("STEP 4 — Exporting CSV")
                _log("─" * 55)
                _do_export(results)

            _set_subtitle("Done — opening results…")
            _log("\n" + "─" * 55)
            _log(f"  ✓ Screener complete at {results['scored_at']}")
            _log("  Opening results table…")
            _log("─" * 55)

            root.after(0, lambda: run_again_btn.pack(side="left"))
            root.after(200, lambda: _show_results_inline(results, rank_mode))

        except Exception as e:
            import traceback
            _log(f"\n  ✗ ERROR: {e}")
            _log(traceback.format_exc())
            _set_subtitle("Error — see log")
            root.after(0, lambda: run_again_btn.pack(side="left"))

    def _run_watchlist(tickers: list, do_download: bool, do_export: bool, rank_mode: str = "normal"):
        try:
            _log("─" * 55)
            _log("WATCHLIST RUN")
            _log("─" * 55)
            _log(f"  Tickers ({len(tickers)}): {', '.join(tickers)}")

            # Build a pseudo market_tickers dict — assign each ticker to its
            # market based on suffix, defaulting to US for bare symbols.
            market_tickers: dict[str, list[str]] = {}
            for sym in tickers:
                if sym.endswith(".AX"):
                    mkt = "AU"
                elif sym.endswith(".NZ"):
                    mkt = "NZ"
                elif sym.endswith(".SI"):
                    mkt = "SG"
                elif sym.endswith(".KL"):
                    mkt = "MY"
                else:
                    mkt = "US"
                market_tickers.setdefault(mkt, []).append(sym)

            _log(f"  Markets detected: { {m: len(t) for m, t in market_tickers.items()} }")

            # ── Prices ────────────────────────────────────────────────────
            _log("\n" + "─" * 55)
            _log("STEP 1 — Prices")
            _log("─" * 55)
            _set_subtitle(f"{'Downloading' if do_download else 'Loading'} prices…")
            prices = download_prices(market_tickers, force_refresh=do_download, log=_log)

            if prices.empty:
                _log("\n  ✗ No price data found. Tick 'Re-download prices' and try again.")
                _set_subtitle("Failed — no price data")
                root.after(0, lambda: run_again_btn.pack(side="left"))
                return

            _log(f"\n  Price matrix: {prices.shape[1]} tickers × {prices.shape[0]} trading days")

            # ── Score ─────────────────────────────────────────────────────
            _log("\n" + "─" * 55)
            _log("STEP 2 — Momentum scoring")
            _log("─" * 55)
            _set_subtitle("Computing momentum scores…")

            results = run_screener(
                market_tickers, prices,
                top_n=len(tickers),       # show all — no cutoff for watchlist
                min_turnovers=None,       # no liquidity filter for hand-picked tickers
                rank_mode=rank_mode,
                log=_log,
                save_cache=False,         # don't overwrite screener signal cache
            )

            if not results:
                _log("\n  ✗ No results computed.")
                _set_subtitle("Failed — no results")
                root.after(0, lambda: run_again_btn.pack(side="left"))
                return

            _last_results["data"] = results

            if do_export:
                _log("\n" + "─" * 55)
                _log("STEP 3 — Exporting CSV")
                _log("─" * 55)
                _do_export(results)

            _set_subtitle("Done — opening results…")
            _log("\n" + "─" * 55)
            _log(f"  ✓ Watchlist complete at {results['scored_at']}")
            _log("  Opening results table…")
            _log("─" * 55)

            root.after(0, lambda: run_again_btn.pack(side="left"))
            root.after(200, lambda: _show_results_inline(results, rank_mode))

        except Exception as e:
            import traceback
            _log(f"\n  ✗ ERROR: {e}")
            _log(traceback.format_exc())
            _set_subtitle("Error — see log")
            root.after(0, lambda: run_again_btn.pack(side="left"))

    # ── Boot ──────────────────────────────────────────────────────────────
    _build_launcher()
    launcher_panel.pack(fill="both", expand=True)
    root.bind("<Return>", lambda e: _go())
    root.mainloop()


if __name__ == "__main__":
    launch()