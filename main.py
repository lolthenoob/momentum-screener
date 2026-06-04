"""
Momentum Screener
══════════════════════════════════════════════════════════════════
Screens US (S&P 500), AU (ASX 300), NZ (NZX 50), and SG (SGX)
for the top momentum stocks using batch yfinance price downloads.

Momentum score = composite rank of:
  · 12-1 month return    (classic momentum, skip last month)
  · 3-month return       (short-term confirmation)
  · Price vs 200-day MA  (trend regime)
  · RSI 14               (momentum strength, capped at 75)
  · MA20/MA50 ratio      (short vs medium alignment)
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
import warnings

warnings.filterwarnings("ignore")

from ticker_loader import load_all_tickers, ticker_count
from momentum_calc  import download_prices, run_screener
from screener_table import show_screener_table

# ── Config ────────────────────────────────────────────────────────────────────

TOP_N = 50

# ── Colours (same palette as fundamentals-dashboard) ─────────────────────────

CLR_ACCENT  = "#00A4EF"
CLR_BG      = "#F7F9FC"
CLR_TEXT    = "#1A1A2E"
CLR_SUBTEXT = "#555577"
CLR_BTN_FG  = "#FFFFFF"

MONO_SIZE    = 15
BOLD_SIZE    = 15
HDR_BOLD_SZ  = 18
HDR_SUB_SZ   = 15


# ── Launcher window ───────────────────────────────────────────────────────────

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
    w, h = 700, 560
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    root.minsize(500, 400)

    mono     = tkfont.Font(family="Consolas", size=MONO_SIZE)
    bold     = tkfont.Font(family="Consolas", size=BOLD_SIZE, weight="bold")
    hdr_bold = tkfont.Font(family="Consolas", size=HDR_BOLD_SZ, weight="bold")
    hdr_sub  = tkfont.Font(family="Consolas", size=HDR_SUB_SZ)

    # ── Panels (launcher + status share the same root window) ─────────────
    launcher_panel = tk.Frame(root, bg=CLR_BG)
    status_panel   = tk.Frame(root, bg=CLR_BG)

    # ── Header ────────────────────────────────────────────────────────────
    def _make_header(parent):
        hdr = tk.Frame(parent, bg=CLR_ACCENT, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Momentum Screener",
                 bg=CLR_ACCENT, fg="white", font=hdr_bold).pack()
        tk.Label(hdr, text="US · AU · NZ · SG",
                 bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub).pack()
        return hdr

    # ─── Launcher panel ───────────────────────────────────────────────────
    _make_header(launcher_panel)

    info_frame = tk.Frame(launcher_panel, bg=CLR_BG, padx=24, pady=14)
    info_frame.pack(fill="x")

    info_lines = [
        ("Universe",  "S&P 500 · ASX 300 · NZX 50 · STI + SGX"),
        ("Signals",   "12-1M return, 3M return, vs 200MA, RSI, MA20/50"),
        ("Output",    f"Top {TOP_N} per market + overall leaderboard"),
        ("Cache",     "Price data cached locally — fast re-runs"),
    ]
    for label, val in info_lines:
        row = tk.Frame(info_frame, bg=CLR_BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=f"{label:<12}", font=bold,
                 bg=CLR_BG, fg=CLR_SUBTEXT, anchor="w", width=14).pack(side="left")
        tk.Label(row, text=val, font=mono,
                 bg=CLR_BG, fg=CLR_TEXT, anchor="w").pack(side="left")

    sep = tk.Frame(launcher_panel, bg="#DDDDDD", height=1)
    sep.pack(fill="x", padx=24, pady=(8, 0))

    # Options
    opt_frame = tk.Frame(launcher_panel, bg=CLR_BG, padx=24, pady=14)
    opt_frame.pack(fill="x")

    top_n_var     = tk.StringVar(value=str(TOP_N))
    refresh_var   = tk.BooleanVar(value=False)
    tickers_var   = tk.BooleanVar(value=False)

    def _make_toggle(frame, label, var):
        tick_font = tkfont.Font(family="Segoe UI Symbol", size=18)
        container = tk.Frame(frame, bg=CLR_BG)
        container.pack(fill="x", pady=3)
        btn = tk.Button(container, text="☐", font=tick_font,
                        fg="#AAAAAA", bg=CLR_BG, activebackground=CLR_BG,
                        relief="flat", bd=0, cursor="hand2")
        btn.pack(side="left")
        tk.Label(container, text=label, bg=CLR_BG, fg=CLR_TEXT, font=bold).pack(side="left")
        def _toggle():
            var.set(not var.get())
            btn.config(text="☑" if var.get() else "☐",
                       fg=CLR_ACCENT if var.get() else "#AAAAAA")
        btn.config(command=_toggle)
        return btn

    top_row = tk.Frame(opt_frame, bg=CLR_BG)
    top_row.pack(fill="x", pady=3)
    tk.Label(top_row, text="Top N per market:", bg=CLR_BG,
             fg=CLR_TEXT, font=bold).pack(side="left")
    tk.Entry(top_row, textvariable=top_n_var, font=mono, width=5,
             relief="flat", highlightthickness=1,
             highlightcolor=CLR_ACCENT,
             highlightbackground="#CCCCCC").pack(side="left", padx=8)

    _make_toggle(opt_frame, "Re-download all prices (ignore cache)", refresh_var)
    _make_toggle(opt_frame, "Refresh ticker lists (ignore weekly cache)", tickers_var)

    # ── Buttons ───────────────────────────────────────────────────────────
    btn_frame = tk.Frame(launcher_panel, bg=CLR_BG, padx=24, pady=10)
    btn_frame.pack(fill="x")

    btn_cfg = dict(font=bold, relief="flat", bd=0, padx=16, pady=8, cursor="hand2")

    def _go():
        try:
            top_n = max(1, int(top_n_var.get()))
        except ValueError:
            top_n = TOP_N
        force_prices  = refresh_var.get()
        force_tickers = tickers_var.get()
        _switch_to_status()
        threading.Thread(
            target=_run_screener,
            args=(top_n, force_prices, force_tickers),
            daemon=True,
        ).start()

    tk.Button(btn_frame, text="▶  Run Screener",
              bg=CLR_ACCENT, fg=CLR_BTN_FG,
              activebackground="#0082C8",
              command=_go, **btn_cfg).pack(side="right")

    tk.Button(btn_frame, text="✕  Exit",
              bg="#CC3333", fg=CLR_BTN_FG,
              activebackground="#AA2222",
              command=root.destroy, **btn_cfg).pack(side="right", padx=(0, 8))

    # ─── Status panel ─────────────────────────────────────────────────────
    _make_header(status_panel)

    status_sub_var = tk.StringVar(value="Starting…")
    status_sub_lbl = tk.Label(status_panel, textvariable=status_sub_var,
                               bg=CLR_ACCENT, fg="#D0EEFF", font=hdr_sub)

    log_outer = tk.Frame(status_panel, bg=CLR_BG, padx=20, pady=10)
    log_outer.pack(fill="both", expand=True)

    log_text = tk.Text(
        log_outer,
        font=mono,
        bg="white", fg=CLR_TEXT,
        relief="flat", wrap="word",
        highlightthickness=1,
        highlightbackground="#CCCCCC",
        cursor="arrow",
    )
    log_text.bind("<Key>",
                  lambda e: "break" if e.keysym not in ("c", "C") or not (e.state & 0x4) else None)
    log_scroll = tk.Scrollbar(log_outer, command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_scroll.pack(side="right", fill="y")
    log_text.pack(fill="both", expand=True)

    bottom_bar = tk.Frame(status_panel, bg=CLR_BG, pady=10, padx=20)
    bottom_bar.pack(fill="x")

    run_again_btn = tk.Button(bottom_bar, text="↺  Run Again",
                               bg=CLR_ACCENT, fg="white",
                               font=bold, relief="flat", padx=14, pady=7,
                               cursor="hand2")
    exit_btn = tk.Button(bottom_bar, text="✕  Exit",
                          bg="#CC3333", fg="white",
                          font=bold, relief="flat", padx=14, pady=7,
                          cursor="hand2", command=root.destroy)

    # ── Panel switch helpers ───────────────────────────────────────────────

    def _switch_to_status():
        launcher_panel.pack_forget()
        status_panel.pack(fill="both", expand=True)
        status_sub_lbl.pack()          # show subtitle under the accent header
        run_again_btn.pack_forget()
        exit_btn.pack(side="right")

    def _switch_to_launcher():
        status_panel.pack_forget()
        status_sub_lbl.pack_forget()
        log_text.delete("1.0", "end")
        status_sub_var.set("Starting…")
        refresh_var.set(False)
        tickers_var.set(False)
        launcher_panel.pack(fill="both", expand=True)

    run_again_btn.config(command=_switch_to_launcher)

    # ── Log helper ────────────────────────────────────────────────────────

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

    # ── Worker ────────────────────────────────────────────────────────────

    def _run_screener(top_n: int, force_prices: bool, force_tickers: bool):
        try:
            # 1. Load ticker lists
            _set_subtitle("Loading ticker lists…")
            _log("─" * 55)
            _log("STEP 1 — Ticker lists")
            _log("─" * 55)
            market_tickers = load_all_tickers(
                force_refresh=force_tickers,
                log=_log,
            )
            total = ticker_count(market_tickers)
            _log(f"\n  Total universe: {total} tickers across "
                 f"{len(market_tickers)} markets")

            # 2. Download / cache prices
            _set_subtitle(f"Downloading prices ({total} tickers)…")
            _log("\n" + "─" * 55)
            _log("STEP 2 — Price download / cache check")
            _log("─" * 55)
            prices = download_prices(
                market_tickers,
                force_refresh=force_prices,
                log=_log,
            )
            _log(f"\n  Price matrix: {prices.shape[1]} tickers × "
                 f"{prices.shape[0]} trading days")

            # 3. Score
            _set_subtitle("Computing momentum scores…")
            _log("\n" + "─" * 55)
            _log("STEP 3 — Momentum scoring")
            _log("─" * 55)
            results = run_screener(
                market_tickers,
                prices,
                top_n=top_n,
                log=_log,
            )

            if not results:
                _log("\n  ✗ No results computed — check price data above.")
                _set_subtitle("Failed — no results")
                root.after(0, lambda: run_again_btn.pack(side="left"))
                return

            # 4. Done
            _set_subtitle("Done — opening results…")
            _log("\n" + "─" * 55)
            _log(f"  ✓ Screener complete at {results['scored_at']}")
            _log(f"  Opening results table…")
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
    launcher_panel.pack(fill="both", expand=True)
    root.bind("<Return>", lambda e: _go())
    root.mainloop()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    launch()
