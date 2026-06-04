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
from momentum_calc  import download_prices, run_screener, cache_data_age_days
from screener_table import show_screener_table

# ── Colours ───────────────────────────────────────────────────────────────────
CLR_ACCENT  = "#00A4EF"
CLR_BG      = "#F7F9FC"
CLR_TEXT    = "#1A1A2E"
CLR_SUBTEXT = "#555577"
CLR_BTN_FG  = "#FFFFFF"
CLR_WARN    = "#CC7700"
HDR_BOLD_SZ = 18
HDR_SUB_SZ  = 13


# ── Preferences dialog ────────────────────────────────────────────────────────

def _show_prefs(root, on_save=None):
    dlg = tk.Toplevel(root)
    dlg.title("Preferences")
    dlg.configure(bg=CLR_BG)
    dlg.resizable(False, False)
    dlg.grab_set()

    # Use the current configured font size (not a hardcoded 12)
    fs = config.font_size()
    f  = tkfont.Font(family="Consolas", size=fs)
    fb = tkfont.Font(family="Consolas", size=fs, weight="bold")

    # ── Simple fields (always editable) ───────────────────────────────────
    simple_fields = [
        ("Font size (8–24):",  "font_size"),
        ("Top N per market:",  "top_n"),
    ]

    # ── Window-size fields (disabled when auto-resize is on) ───────────────
    size_fields = [
        ("Launcher width (px):",        "launcher_w"),
        ("Launcher height (px):",       "launcher_h"),
        ("Results table width (px):",   "table_w"),
        ("Results table height (px):",  "table_h"),
    ]

    vars_   = {}
    entries = {}   # key → Entry widget, for enable/disable
    row_idx = 0

    for label, key in simple_fields:
        tk.Label(dlg, text=label, bg=CLR_BG, fg=CLR_TEXT,
                 font=fb, anchor="w", width=28).grid(
            row=row_idx, column=0, padx=16, pady=6, sticky="w")
        v = tk.StringVar(value=config.get(key))
        tk.Entry(dlg, textvariable=v, font=f, width=8,
                 relief="flat", highlightthickness=1,
                 highlightbackground="#CCCCCC").grid(row=row_idx, column=1, padx=8)
        vars_[key] = v
        row_idx += 1

    # ── Auto-resize toggle ─────────────────────────────────────────────────
    # "Auto-resize" means the windows scale to font size automatically;
    # the stored W/H values are ignored in that mode.
    auto_resize_var = tk.BooleanVar(value=config.get_bool("auto_resize"))

    sep = tk.Frame(dlg, bg="#DDDDDD", height=1)
    sep.grid(row=row_idx, column=0, columnspan=2, sticky="ew", padx=16, pady=(8, 4))
    row_idx += 1

    auto_frame = tk.Frame(dlg, bg=CLR_BG)
    auto_frame.grid(row=row_idx, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 4))
    row_idx += 1

    auto_cb = tk.Checkbutton(
        auto_frame,
        text="Auto-resize windows to font size",
        variable=auto_resize_var,
        bg=CLR_BG, fg=CLR_TEXT,
        font=fb,
        activebackground=CLR_BG,
        selectcolor=CLR_BG,
        relief="flat", bd=0,
        cursor="hand2",
    )
    auto_cb.pack(side="left")

    # ── Window-size fields (conditionally enabled) ─────────────────────────
    for label, key in size_fields:
        tk.Label(dlg, text=label, bg=CLR_BG, fg=CLR_TEXT,
                 font=fb, anchor="w", width=28).grid(
            row=row_idx, column=0, padx=16, pady=4, sticky="w")
        v = tk.StringVar(value=config.get(key))
        e = tk.Entry(dlg, textvariable=v, font=f, width=8,
                     relief="flat", highlightthickness=1,
                     highlightbackground="#CCCCCC")
        e.grid(row=row_idx, column=1, padx=8)
        vars_[key]   = v
        entries[key] = e
        row_idx += 1

    def _update_size_fields(*_):
        state = "disabled" if auto_resize_var.get() else "normal"
        fg    = CLR_SUBTEXT if auto_resize_var.get() else CLR_TEXT
        for key in [k for _, k in size_fields]:
            entries[key].config(state=state, fg=fg)

    auto_resize_var.trace_add("write", _update_size_fields)
    _update_size_fields()   # apply immediately on open

    # ── Note ──────────────────────────────────────────────────────────────
    note = tk.Label(dlg,
        text="Column widths auto-reset when font size changes.",
        bg=CLR_BG, fg=CLR_SUBTEXT, font=f)
    note.grid(row=row_idx, column=0, columnspan=2, pady=(6, 0), padx=16, sticky="w")
    row_idx += 1

    def _save():
        old_fs = config.font_size()
        config.set("auto_resize", auto_resize_var.get())
        for key, v in vars_.items():
            # Skip size fields if auto-resize is on
            if key in [k for _, k in size_fields] and auto_resize_var.get():
                continue
            raw = v.get().strip()
            if raw:
                try:
                    config.set(key, int(raw))
                except ValueError:
                    pass
        if config.font_size() != old_fs:
            config.clear_col_widths()
        dlg.destroy()
        if on_save:
            on_save()

    bf = tk.Frame(dlg, bg=CLR_BG)
    bf.grid(row=row_idx, column=0, columnspan=2, pady=12)
    tk.Button(bf, text="Save", bg=CLR_ACCENT, fg="white",
              font=fb, relief="flat", padx=14, pady=6,
              cursor="hand2", command=_save).pack(side="left", padx=6)
    tk.Button(bf, text="Cancel", bg="#888888", fg="white",
              font=fb, relief="flat", padx=14, pady=6,
              cursor="hand2", command=dlg.destroy).pack(side="left")


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
        if config.get_bool("auto_resize"):
            # Scale window to font size: base 720×580 at fs=12, proportional beyond that
            fs    = config.font_size()
            scale = fs / 12
            w = min(int(720 * scale), sw - 40)
            h = min(int(580 * scale), sh - 40)
        else:
            w = min(config.get_int("launcher_w") or 720, sw - 40)
            h = min(config.get_int("launcher_h") or 580, sh - 40)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        root.minsize(500, 420)

    _apply_launcher_size()

    # ── Font factory ──────────────────────────────────────────────────────
    _fonts = {}

    def _make_fonts():
        fs = config.font_size()
        _fonts["mono"]     = tkfont.Font(family="Consolas", size=fs)
        _fonts["bold"]     = tkfont.Font(family="Consolas", size=fs, weight="bold")
        _fonts["hdr_bold"] = tkfont.Font(family="Consolas", size=HDR_BOLD_SZ, weight="bold")
        _fonts["hdr_sub"]  = tkfont.Font(family="Consolas", size=HDR_SUB_SZ)
        _fonts["tick"]     = tkfont.Font(family="Segoe UI Symbol", size=fs + 4)

    _make_fonts()
    mono     = lambda: _fonts["mono"]
    bold     = lambda: _fonts["bold"]
    hdr_bold = lambda: _fonts["hdr_bold"]
    hdr_sub  = lambda: _fonts["hdr_sub"]
    tick_f   = lambda: _fonts["tick"]

    # ── Panels ────────────────────────────────────────────────────────────
    launcher_panel = tk.Frame(root, bg=CLR_BG)
    status_panel   = tk.Frame(root, bg=CLR_BG)

    # ── Custom menu bar (frame-based so font scales with config) ──────────
    _last_results = {"data": None}

    menubar_frame = tk.Frame(root, bg="#E8EDF4", bd=0, relief="flat")
    menubar_frame.pack(fill="x", side="top")

    _open_popup = {"widget": None, "btn": None}

    def _close_open_popup():
        if _open_popup["widget"] and _open_popup["widget"].winfo_exists():
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

            popup = tk.Toplevel(root)
            popup.overrideredirect(True)
            popup.configure(bg="#E8EDF4",
                            highlightthickness=1,
                            highlightbackground="#BBBBCC")
            bx = btn.winfo_rootx()
            by = btn.winfo_rooty() + btn.winfo_height()
            popup.geometry(f"+{bx}+{by}")

            for item in items:
                if item is None:
                    tk.Frame(popup, bg="#CCCCCC", height=1).pack(fill="x", padx=6, pady=2)
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

            # Register a dismiss handler via after_idle so it fires AFTER
            # the current click event has fully finished propagating.
            # This prevents the same click that opens the menu from
            # immediately closing it, and leaves no lingering binding.
            def _arm_dismiss():
                def _on_click_outside(e):
                    if not _open_popup["widget"]:
                        return
                    try:
                        pw = _open_popup["widget"]
                        if not pw.winfo_exists():
                            _close_open_popup()
                            return
                        wx, wy = pw.winfo_rootx(), pw.winfo_rooty()
                        ww, wh = pw.winfo_width(), pw.winfo_height()
                        if not (wx <= e.x_root <= wx + ww and wy <= e.y_root <= wy + wh):
                            _close_open_popup()
                    except Exception:
                        _close_open_popup()

                # Use FocusOut on the popup instead of a global bind —
                # when the user clicks anywhere else, the popup loses focus.
                if popup.winfo_exists():
                    popup.bind("<FocusOut>", lambda e: _close_open_popup())
                    # Also catch clicks on the root window itself
                    popup.bind_all("<ButtonPress-1>", _on_click_outside)

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

    def _export_now():
        if not _last_results["data"]:
            messagebox.showinfo("Export", "Run the screener first.")
            return
        _do_export(_last_results["data"])

    _make_menu_btn("File", [
        ("Export results to CSV", lambda: _export_now()),
        None,
        ("Exit", root.destroy),
    ])
    _make_menu_btn("Edit", [
        ("Preferences\u2026", lambda: _show_prefs(root, _on_prefs_saved)),
    ])

    # ── Header ────────────────────────────────────────────────────────────
    def _make_header(parent):
        hdr = tk.Frame(parent, bg=CLR_ACCENT, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Momentum Screener",
                 bg=CLR_ACCENT, fg="white", font=hdr_bold()).pack()
        tk.Label(hdr, text="US · AU · NZ · SG",
                 bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub()).pack()

    # ── Toggle helper ─────────────────────────────────────────────────────
    def _make_toggle(frame, label, var):
        container = tk.Frame(frame, bg=CLR_BG)
        container.pack(fill="x", pady=3)
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
    top_n_var    = tk.StringVar(value=str(config.get_int("top_n") or 50))
    force_dl_var = tk.BooleanVar(value=False)
    tickers_var  = tk.BooleanVar(value=False)
    export_var   = tk.BooleanVar(value=config.get_bool("export_csv"))

    # ── Build launcher content ────────────────────────────────────────────
    def _build_launcher():
        for w in launcher_panel.winfo_children():
            w.destroy()

        _make_header(launcher_panel)

        info_frame = tk.Frame(launcher_panel, bg=CLR_BG, padx=24, pady=12)
        info_frame.pack(fill="x")

        for label, val in [
            ("Universe",  "S&P 500 · ASX 300 · NZX 50 · STI + SGX"),
            ("Signals",   "RAM · Exp Slope · 12-1M · 3M · Stoch · RSI · CCI · W%R · MA"),
            ("Output",    f"Top {top_n_var.get()} per market + overall leaderboard"),
            ("Cache",     "Runs from local cache — tick box below to force re-download"),
        ]:
            row = tk.Frame(info_frame, bg=CLR_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{label:<12}", font=bold(),
                     bg=CLR_BG, fg=CLR_SUBTEXT, anchor="w", width=14).pack(side="left")
            tk.Label(row, text=val, font=mono(),
                     bg=CLR_BG, fg=CLR_TEXT, anchor="w").pack(side="left")

        tk.Frame(launcher_panel, bg="#DDDDDD", height=1).pack(fill="x", padx=24, pady=(8, 0))

        opt_frame = tk.Frame(launcher_panel, bg=CLR_BG, padx=24, pady=12)
        opt_frame.pack(fill="x")

        # Top N
        top_row = tk.Frame(opt_frame, bg=CLR_BG)
        top_row.pack(fill="x", pady=3)
        tk.Label(top_row, text="Top N per market:", bg=CLR_BG,
                 fg=CLR_TEXT, font=bold()).pack(side="left")
        tk.Entry(top_row, textvariable=top_n_var, font=mono(), width=6,
                 relief="flat", highlightthickness=1,
                 highlightcolor=CLR_ACCENT,
                 highlightbackground="#CCCCCC").pack(side="left", padx=8)
        tk.Label(top_row, text="(saved to preferences)",
                 bg=CLR_BG, fg=CLR_SUBTEXT, font=mono()).pack(side="left")

        _make_toggle(opt_frame, "⚠  Force re-download prices (ignores cache)", force_dl_var)
        _make_toggle(opt_frame, "Refresh ticker lists (ignore weekly cache)", tickers_var)
        _make_toggle(opt_frame, "Export results to CSV after run", export_var)

        # Data age warning
        age = cache_data_age_days()
        age_frame = tk.Frame(launcher_panel, bg=CLR_BG, padx=24)
        age_frame.pack(fill="x")
        if age is None:
            txt, clr = "⚠  No cached price data — first run will download.", CLR_WARN
        elif age == 0:
            txt, clr = "✓  Price data last updated today.", "#1A7A3A"
        elif age == 1:
            txt, clr = "✓  Price data last updated yesterday.", "#1A7A3A"
        else:
            txt = f"⚠  Price data is {age} days old.  Tick the box above to refresh."
            clr = CLR_WARN if age < 30 else "#CC3333"
        tk.Label(age_frame, text=txt, bg=CLR_BG,
                 fg=clr, font=bold()).pack(anchor="w", pady=(0, 6))

        tk.Frame(launcher_panel, bg="#DDDDDD", height=1).pack(fill="x", padx=24, pady=(0, 4))

        btn_frame = tk.Frame(launcher_panel, bg=CLR_BG, padx=24, pady=10)
        btn_frame.pack(fill="x")
        cfg = dict(font=bold(), relief="flat", bd=0, padx=16, pady=8, cursor="hand2")
        tk.Button(btn_frame, text="▶  Run Screener",
                  bg=CLR_ACCENT, fg=CLR_BTN_FG,
                  activebackground="#0082C8",
                  command=_go, **cfg).pack(side="right")
        tk.Button(btn_frame, text="✕  Exit",
                  bg="#CC3333", fg=CLR_BTN_FG,
                  activebackground="#AA2222",
                  command=root.destroy, **cfg).pack(side="right", padx=(0, 8))

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
        status_panel.pack_forget()
        status_sub_lbl.pack_forget()
        log_text.delete("1.0", "end")
        status_sub_var.set("Starting…")
        force_dl_var.set(False)
        tickers_var.set(False)
        export_var.set(config.get_bool("export_csv"))
        _build_launcher()
        launcher_panel.pack(fill="both", expand=True)

    run_again_btn.config(command=_switch_to_launcher)

    def _on_prefs_saved():
        _make_fonts()
        _apply_launcher_size()
        # Rebuild custom menu bar so button font reflects new size
        for w in menubar_frame.winfo_children():
            w.destroy()
        _make_menu_btn("File", [
            ("Export results to CSV", lambda: _export_now()),
            None,
            ("Exit", root.destroy),
        ])
        _make_menu_btn("Edit", [
            ("Preferences…", lambda: _show_prefs(root, _on_prefs_saved)),
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
        config.set("top_n", top_n)
        config.set("export_csv", export_var.get())
        _switch_to_status()
        threading.Thread(
            target=_run_screener,
            args=(top_n, force_dl_var.get(), tickers_var.get(), export_var.get()),
            daemon=True,
        ).start()

    def _run_screener(top_n, force_prices, force_tickers, do_export):
        try:
            _set_subtitle("Loading ticker lists…")
            _log("─" * 55)
            _log("STEP 1 — Ticker lists")
            _log("─" * 55)
            market_tickers = load_all_tickers(force_refresh=force_tickers, log=_log)
            total = ticker_count(market_tickers)
            _log(f"\n  Total universe: {total} tickers across {len(market_tickers)} markets")

            age = cache_data_age_days()
            age_str = f"{age} days old" if age is not None else "no cache"
            _set_subtitle(
                f"Downloading prices ({total} tickers)…" if force_prices
                else f"Loading from cache ({age_str})…"
            )
            _log("\n" + "─" * 55)
            _log("STEP 2 — Price data")
            _log("─" * 55)
            if age is None:
                _log("  ⚠  No cached data — downloading for first time…")
            elif not force_prices:
                _log(f"  ℹ  Using cached data ({age} days old). Tick 'Force re-download' to refresh.")
            else:
                _log("  ⚠  Force re-download requested.")

            prices = download_prices(market_tickers, force_refresh=force_prices, log=_log)
            _log(f"\n  Price matrix: {prices.shape[1]} tickers × {prices.shape[0]} trading days")

            _set_subtitle("Computing momentum scores…")
            _log("\n" + "─" * 55)
            _log("STEP 3 — Momentum scoring")
            _log("─" * 55)
            results = run_screener(market_tickers, prices, top_n=top_n, log=_log)

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
            root.after(200, lambda: show_screener_table(results))

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