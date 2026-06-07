"""
watchlist_picker.py
───────────────────
Builds a fully-featured watchlist ticker-selection panel *inside* an existing
Tkinter parent frame.  No Tk() root, no Toplevel — the widget tree stays inside
the caller's window so there is always exactly one window on screen.

Public API
──────────
    build_watchlist_panel(
        parent,          # tk.Frame  — the frame to pack content into
        root,            # tk.Tk     — root window (for after() / mousewheel binds)
        fonts,           # dict with keys: mono, bold, tick, hdr_bold, hdr_sub
        colors,          # dict with keys: bg, accent, text, subtext, btn_fg,
                         #                 row_a, row_b, warn
        on_run_cb,       # callable(tickers, do_download, do_export, rank_mode)
        saved_tickers,   # str  — comma-separated, pre-fills the selection on load
        saved_rank_mode, # str  — "normal" | "weekly" | "both"
    ) -> dict
        Returns a controller dict with:
            "get_selected"  → callable() → list[str]
            "clear"         → callable() — resets the picker to empty

Features (ported from ticker_picker.py)
────────────────────────────────────────
  · Scrollable tick-list  (All / Selected / Unselected filter)
  · Live search bar — filters the local list and queries Yahoo Finance for
    suggestions after 350 ms of inactivity (single-ticker mode)
  · Bulk comma-mode — typing a comma switches into bulk mode: all symbols are
    resolved in parallel via Yahoo and shown as a toggleable preview list.
    "Add all N" or tick individually, then commit.
  · "Add as new ticker" button for symbols not yet in the list
  · Selected-ticker summary bar at the top
  · Run options: Re-download toggle, Export toggle, Rank-by radio
  · ▶ Run Watchlist button fires on_run_cb with the final selection
"""

import re
import json
import threading
import tkinter as tk
from tkinter import ttk
import urllib.request
import urllib.parse

# ── Symbol validation ─────────────────────────────────────────────────────────

_SYM_RE = re.compile(r'^[A-Z0-9.\-]{1,7}$')


def _parse_bulk(raw: str) -> list[str]:
    """Split comma-separated string into clean, deduplicated, valid tickers."""
    tokens = [t.strip().upper() for t in raw.split(",")]
    seen, result = set(), []
    for t in tokens:
        if not t:
            continue
        if not _SYM_RE.match(t):
            continue
        if t in seen:
            continue
        seen.add(t)
        result.append(t)
    return result


# ── Yahoo search helpers ──────────────────────────────────────────────────────

def _yahoo_search(q: str, callback):
    """Fetch Yahoo Finance suggestions for q, then call callback(results) on
    the main thread.  Designed to run in a daemon thread."""
    try:
        url = (
            "https://query1.finance.yahoo.com/v1/finance/search"
            f"?q={urllib.parse.quote(q)}&quotesCount=20&newsCount=0"
            "&enableFuzzyQuery=false&enableCccBoost=false"
            "&enableEnhancedTrivialQuery=true"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read())
        quotes = data.get("quotes", [])
        results = [
            (r.get("symbol", ""), r.get("longname") or r.get("shortname") or "")
            for r in quotes if r.get("symbol")
        ]
    except Exception:
        results = []
    callback(results)


def _yahoo_resolve_one(sym: str, db_syms: set, db_name: dict,
                       on_done, resolved_list, resolved_lock, pending, order):
    """Resolve a single symbol's name (used for parallel bulk resolution)."""
    in_db = sym in db_syms
    if in_db:
        name = db_name.get(sym, "")
    else:
        name = ""
        try:
            url = (
                "https://query1.finance.yahoo.com/v1/finance/search"
                f"?q={urllib.parse.quote(sym)}&quotesCount=5&newsCount=0"
                "&enableFuzzyQuery=false&enableEnhancedTrivialQuery=true"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read())
            for quote in data.get("quotes", []):
                if quote.get("symbol", "").upper() == sym:
                    name = quote.get("longname") or quote.get("shortname") or ""
                    break
        except Exception:
            pass

    with resolved_lock:
        resolved_list.append((sym, name, in_db))
        pending[0] -= 1
        if pending[0] == 0:
            resolved_list.sort(key=lambda t: order.get(t[0], 999))
            on_done(list(resolved_list))


# ── Main builder ──────────────────────────────────────────────────────────────

def build_watchlist_panel(
    parent,
    root,
    fonts: dict,
    colors: dict,
    on_run_cb,
    saved_tickers: str = "",
    saved_rank_mode: str = "normal",
) -> dict:
    """
    Build the watchlist picker UI into *parent*.
    Returns a controller dict.
    """

    # ── Unpack theme shortcuts ────────────────────────────────────────────
    CLR_BG      = colors["bg"]
    CLR_ACCENT  = colors["accent"]
    CLR_TEXT    = colors["text"]
    CLR_SUBTEXT = colors["subtext"]
    CLR_BTN_FG  = colors["btn_fg"]
    CLR_ROW_A   = colors.get("row_a", "#FFFFFF")
    CLR_ROW_B   = colors.get("row_b", "#EFF4FA")
    CLR_WARN    = colors.get("warn", "#CC7700")

    mono      = fonts["mono"]
    bold      = fonts["bold"]
    tick_font = fonts["tick"]

    # ── State ─────────────────────────────────────────────────────────────
    check_vars:   dict[str, tk.BooleanVar] = {}   # sym → checked
    row_frames:   dict[str, tk.Frame]      = {}   # sym → row widget
    tick_buttons: dict[str, tk.Button]     = {}   # sym → tick btn
    _session_added: set[str]               = set()
    _name_cache:  dict[str, str]           = {}   # sym → display name

    # Pre-populate from saved tickers
    _initial_tickers: list[str] = []
    if saved_tickers:
        for tok in re.split(r"[,\s]+", saved_tickers.upper()):
            tok = tok.strip()
            if tok and _SYM_RE.match(tok):
                _initial_tickers.append(tok)

    # ── Grid layout: rows 0-3 fixed height, row 4 (list) expands, row 5 footer ─
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(4, weight=1)   # list row expands

    # ── Summary bar — row 0 ───────────────────────────────────────────────
    summary_frame = tk.Frame(parent, bg="#E8F4FD", pady=6, padx=14)
    summary_frame.grid(row=0, column=0, sticky="ew")
    tk.Label(summary_frame, text="Selected: ", bg="#E8F4FD",
             fg=CLR_SUBTEXT, font=bold).pack(side="left")
    summary_var = tk.StringVar(value="—")
    tk.Label(summary_frame, textvariable=summary_var, bg="#E8F4FD",
             fg=CLR_ACCENT, font=bold, anchor="w",
             wraplength=600, justify="left").pack(side="left", fill="x", expand=True)

    # Filter toggle
    toggle_frame = tk.Frame(parent, bg=CLR_BG, pady=4, padx=14)
    toggle_frame.grid(row=1, column=0, sticky="ew")
    filter_var = tk.StringVar(value="all")
    _filter_btns: dict[str, tuple] = {}

    def _set_filter(val):
        filter_var.set(val)
        for v, (btn, lbl) in _filter_btns.items():
            active = (v == val)
            btn.config(text="☑" if active else "☐",
                       fg=CLR_ACCENT if active else "#AAAAAA")
        _apply_filter()

    for f_label, f_val in [("All", "all"), ("Selected", "selected"), ("Unselected", "unselected")]:
        c = tk.Frame(toggle_frame, bg=CLR_BG)
        c.pack(side="left", padx=(0, 16))
        fb = tk.Button(c, text="☑" if f_val == "all" else "☐",
                       font=tick_font,
                       fg=CLR_ACCENT if f_val == "all" else "#AAAAAA",
                       bg=CLR_BG, activebackground=CLR_BG,
                       relief="flat", bd=0, cursor="hand2",
                       command=lambda v=f_val: _set_filter(v))
        fb.pack(side="left")
        fl = tk.Label(c, text=f_label, bg=CLR_BG, fg=CLR_TEXT, font=bold)
        fl.pack(side="left")
        fl.bind("<Button-1>", lambda e, v=f_val: _set_filter(v))
        _filter_btns[f_val] = (fb, fl)

    # Search bar
    search_frame = tk.Frame(parent, bg=CLR_BG, pady=6, padx=14)
    search_frame.grid(row=2, column=0, sticky="ew")
    tk.Label(search_frame, text="🔍  Search / Add:", bg=CLR_BG,
             fg=CLR_TEXT, font=bold).pack(side="left")
    search_var = tk.StringVar()
    search_entry = tk.Entry(
        search_frame, textvariable=search_var,
        font=mono, relief="flat", bg="white", fg=CLR_TEXT,
        insertbackground=CLR_ACCENT,
        highlightthickness=1,
        highlightcolor=CLR_ACCENT,
        highlightbackground="#CCCCCC",
    )
    search_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

    add_new_btn = tk.Button(
        search_frame, text="", bg="#E06C00", fg="white",
        font=bold, relief="flat", padx=12, pady=4,
        cursor="hand2",
    )

    select_results_btn = tk.Button(
        search_frame, text="✔  Select All Results",
        bg="#10B981", fg="white",
        font=bold, relief="flat", padx=12, pady=4,
        cursor="hand2",
        command=lambda: _select_visible(),
    )

    # ── Scrollable list — row 4 (expands) ───────────────────────────────────
    list_outer = tk.Frame(parent, bg=CLR_BG, padx=14)
    list_outer.grid(row=4, column=0, sticky="nsew")

    # ── Footer — row 5 (fixed) ────────────────────────────────────────────
    tk.Frame(parent, bg="#DDDDDD", height=1).grid(row=5, column=0, sticky="ew")
    ctrl = tk.Frame(parent, bg=CLR_BG, pady=6, padx=14)
    ctrl.grid(row=6, column=0, sticky="ew")

    canvas = tk.Canvas(list_outer, bg=CLR_BG, highlightthickness=0)
    scrollbar = ttk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas, bg=CLR_BG)
    canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

    canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _scroll(event):
        if event.num == 4:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            canvas.yview_scroll(1, "units")
        else:
            canvas.yview_scroll(int(-event.delta / 60), "units")

    canvas.bind_all("<MouseWheel>", _scroll)
    canvas.bind_all("<Button-4>",   _scroll)
    canvas.bind_all("<Button-5>",   _scroll)

    # ── Summary / count helpers ───────────────────────────────────────────
    def _update_summary(*_):
        selected = [s for s, v in check_vars.items() if v.get()]
        summary_var.set(", ".join(selected) if selected else "—")

    def _update_count(*_):
        n = sum(v.get() for v in check_vars.values())
        count_var.set(f"{n} selected")

    def _apply_filter(*_):
        q    = search_var.get().strip().upper()
        filt = filter_var.get()
        for sym in list(row_frames):
            if sym not in row_frames:
                continue
            text_match = (
                not q or "," in q
                or sym.upper().startswith(q)
                or q in sym.upper()
                or q in _name_cache.get(sym, "").upper()
            )
            if filt == "selected":
                sel_match = check_vars.get(sym, tk.BooleanVar()).get()
            elif filt == "unselected":
                sel_match = not check_vars.get(sym, tk.BooleanVar()).get()
            else:
                sel_match = True
            try:
                if text_match and sel_match:
                    row_frames[sym].pack(fill="x")
                else:
                    row_frames[sym].pack_forget()
            except Exception:
                pass
        canvas.yview_moveto(0)

    def _select_visible():
        for sym in list(row_frames):
            try:
                if row_frames[sym].winfo_ismapped():
                    check_vars[sym].set(True)
            except Exception:
                pass
        _sync_all_buttons()

    def _sync_all_buttons():
        for sym, v in check_vars.items():
            if sym in tick_buttons:
                try:
                    tick_buttons[sym].config(
                        text="☑" if v.get() else "☐",
                        fg=CLR_ACCENT if v.get() else "#AAAAAA",
                    )
                except Exception:
                    pass

    # ── Toggle factory for persistent list rows ───────────────────────────
    def _make_toggle(v, b):
        def _toggle():
            v.set(not v.get())
            b.config(text="☑" if v.get() else "☐",
                     fg=CLR_ACCENT if v.get() else "#AAAAAA")
        return _toggle

    # ── Session-ticker toggle (unticking removes the row) ─────────────────
    def _make_session_toggle(sym, v, b):
        def _toggle():
            if v.get():
                # Was ticked — remove the row
                v.set(False)
                for d in (row_frames, tick_buttons, check_vars):
                    d.pop(sym, None)
                _session_added.discard(sym)
                _name_cache.pop(sym, None)
                _update_summary()
                _update_count()
                q = search_var.get().strip()
                if q and "," not in q:
                    threading.Thread(
                        target=_yahoo_search,
                        args=(q, lambda r: root.after(0, lambda: _show_suggestions(r))),
                        daemon=True,
                    ).start()
            else:
                v.set(True)
                b.config(text="☑", fg=CLR_ACCENT)
        return _toggle

    # ── Add / tick a symbol ───────────────────────────────────────────────
    def _add_ticker_sym(sym: str, name: str = ""):
        sym = sym.upper().strip()
        if sym in check_vars:
            check_vars[sym].set(True)
            if sym in tick_buttons:
                tick_buttons[sym].config(text="☑", fg=CLR_ACCENT)
            # Retire any stale suggestion row
            if sym in _ac_row_frames:
                try:
                    _ac_row_frames[sym].destroy()
                    _ac_row_frames.pop(sym, None)
                    _ac_buttons.pop(sym, None)
                except Exception:
                    pass
            return

        if not name:
            name = _name_cache.get(sym, "(new — will download)")
        _name_cache[sym] = name

        var = tk.BooleanVar(value=True)
        check_vars[sym] = var
        _session_added.add(sym)

        bg  = CLR_ROW_A if len(check_vars) % 2 == 0 else CLR_ROW_B
        row = tk.Frame(inner, bg=bg, pady=0, padx=8)
        row.pack(fill="x")
        row_frames[sym] = row

        btn = tk.Button(row, text="☑", font=tick_font,
                        fg=CLR_ACCENT, bg=bg, activebackground=bg,
                        relief="flat", bd=0, cursor="hand2")
        btn.pack(side="left")
        tick_buttons[sym] = btn
        btn.config(command=_make_session_toggle(sym, var, btn))

        tk.Label(row, text=f"{sym:<8}", font=bold,
                 bg=bg, fg="#E06C00", anchor="w").pack(side="left")
        tk.Label(row, text=name, font=mono,
                 bg=bg, fg=CLR_SUBTEXT, anchor="w").pack(side="left")

        var.trace_add("write", _update_summary)
        var.trace_add("write", _update_count)
        var.trace_add("write", _apply_filter)
        _update_summary()
        _update_count()

        # Retire suggestion row for this symbol
        if sym in _ac_buttons:
            try:
                _ac_buttons[sym].config(text="☑", fg=CLR_ACCENT,
                                        command=lambda: None)
            except Exception:
                pass
        if sym in _ac_row_frames:
            try:
                _ac_row_frames[sym].destroy()
                _ac_row_frames.pop(sym, None)
                _ac_buttons.pop(sym, None)
            except Exception:
                pass

    # ── Yahoo autocomplete (single-ticker mode) ───────────────────────────
    _ac_after        = None
    _ac_rows:        list        = []
    _ac_buttons:     dict        = {}
    _ac_row_frames:  dict        = {}

    def _clear_suggestions():
        for sym in list(_ac_row_frames):
            if sym in _session_added:
                var = check_vars.get(sym)
                if var is None or not var.get():
                    for d in (check_vars, row_frames, tick_buttons):
                        d.pop(sym, None)
                    _session_added.discard(sym)
                    _name_cache.pop(sym, None)
        for w in _ac_rows:
            try:
                w.destroy()
            except Exception:
                pass
        _ac_rows.clear()
        _ac_buttons.clear()
        _ac_row_frames.clear()
        _update_summary()
        _update_count()

    def _show_suggestions(results):
        _clear_suggestions()
        existing_syms = set(check_vars)
        yahoo_only = [
            (sym, name) for sym, name in results
            if sym not in existing_syms
        ]
        if not yahoo_only:
            return

        div = tk.Frame(inner, bg="#CCCCCC", height=1)
        div.pack(fill="x")
        _ac_rows.append(div)
        lbl = tk.Label(inner, text="  Yahoo suggestions",
                       bg=CLR_BG, fg=CLR_SUBTEXT, font=bold, anchor="w")
        lbl.pack(fill="x")
        _ac_rows.append(lbl)

        for i, (sym, name) in enumerate(yahoo_only[:7]):
            bg  = CLR_ROW_A if i % 2 == 0 else CLR_ROW_B
            row = tk.Frame(inner, bg=bg, pady=0, padx=8)
            row.pack(fill="x")
            _ac_rows.append(row)

            var = tk.BooleanVar(value=False)
            check_vars[sym]   = var
            row_frames[sym]   = row
            _session_added.add(sym)
            _name_cache[sym]  = name

            var.trace_add("write", _update_summary)
            var.trace_add("write", _update_count)
            var.trace_add("write", _apply_filter)

            def _make_sug_toggle(s, v, b):
                def _toggle():
                    new_val = not v.get()
                    v.set(new_val)
                    b.config(text="☑" if new_val else "☐",
                             fg=CLR_ACCENT if new_val else "#AAAAAA")
                return _toggle

            btn = tk.Button(row, text="☐", font=tick_font,
                            fg="#AAAAAA", bg=bg, activebackground=bg,
                            relief="flat", bd=0, cursor="hand2")
            btn.pack(side="left")
            tick_buttons[sym]   = btn
            _ac_buttons[sym]    = btn
            _ac_row_frames[sym] = row
            btn.config(command=_make_sug_toggle(sym, var, btn))

            tk.Label(row, text=f"{sym:<8}", font=bold,
                     bg=bg, fg="#E06C00", anchor="w").pack(side="left")
            tk.Label(row, text=name, font=mono,
                     bg=bg, fg=CLR_SUBTEXT, anchor="w").pack(side="left", fill="x")

    # ── Bulk mode ─────────────────────────────────────────────────────────
    _bulk_frame      = tk.Frame(inner, bg=CLR_BG)
    _bulk_rows:      list = []
    _bulk_vars:      dict = {}
    _bulk_btns:      dict = {}
    _bulk_active     = [False]
    _bulk_resolve_id = [None]

    def _clear_bulk_ui():
        for w in _bulk_rows:
            try:
                w.destroy()
            except Exception:
                pass
        _bulk_rows.clear()
        _bulk_vars.clear()
        _bulk_btns.clear()

    def _hide_bulk():
        _bulk_active[0] = False
        _clear_bulk_ui()
        _bulk_frame.pack_forget()

    def _show_bulk_loading(symbols):
        _clear_bulk_ui()
        _bulk_frame.pack(fill="x")
        lbl = tk.Label(
            _bulk_frame,
            text=f"  Resolving {len(symbols)} ticker{'s' if len(symbols) != 1 else ''}…",
            bg="#FFF9E6", fg="#8B6914", font=bold,
            anchor="w", pady=6, padx=14,
        )
        lbl.pack(fill="x")
        _bulk_rows.append(lbl)

    def _commit_bulk():
        for sym, var in _bulk_vars.items():
            if var.get():
                _add_ticker_sym(sym, _name_cache.get(sym, ""))
        _hide_bulk()
        search_var.set("")
        _update_summary()
        _update_count()

    def _make_bulk_toggle(v, b):
        def _toggle():
            v.set(not v.get())
            b.config(text="☑" if v.get() else "☐",
                     fg=CLR_ACCENT if v.get() else "#AAAAAA")
        return _toggle

    def _render_bulk_preview(resolved):
        _clear_bulk_ui()
        if not resolved:
            lbl = tk.Label(
                _bulk_frame,
                text="  No valid tickers found.",
                bg="#FFF0F0", fg="#8B1414", font=bold,
                anchor="w", pady=6, padx=14,
            )
            lbl.pack(fill="x")
            _bulk_rows.append(lbl)
            return

        hdr_row = tk.Frame(_bulk_frame, bg="#E8F4FD", pady=5, padx=14)
        hdr_row.pack(fill="x")
        _bulk_rows.append(hdr_row)
        tk.Label(hdr_row,
                 text=f"  {len(resolved)} ticker{'s' if len(resolved) != 1 else ''} ready — tick individually or:",
                 bg="#E8F4FD", fg=CLR_SUBTEXT, font=bold).pack(side="left")
        tk.Button(hdr_row,
                  text=f"＋  Add all {len(resolved)}",
                  bg=CLR_ACCENT, fg="white", font=bold,
                  relief="flat", padx=10, pady=4, cursor="hand2",
                  command=_commit_bulk).pack(side="right", padx=(0, 4))

        div = tk.Frame(_bulk_frame, bg="#CCCCCC", height=1)
        div.pack(fill="x")
        _bulk_rows.append(div)

        for i, (sym, name, in_db) in enumerate(resolved):
            bg  = CLR_ROW_A if i % 2 == 0 else CLR_ROW_B
            row = tk.Frame(_bulk_frame, bg=bg, pady=0, padx=8)
            row.pack(fill="x")
            _bulk_rows.append(row)

            var = tk.BooleanVar(value=True)
            _bulk_vars[sym] = var
            _name_cache[sym] = name

            sym_clr = CLR_ACCENT if in_db else "#E06C00"
            btn = tk.Button(row, text="☑", font=tick_font,
                            fg=CLR_ACCENT, bg=bg, activebackground=bg,
                            relief="flat", bd=0, cursor="hand2")
            btn.pack(side="left")
            _bulk_btns[sym] = btn
            btn.config(command=_make_bulk_toggle(var, btn))

            tk.Label(row, text=f"{sym:<8}", font=bold,
                     bg=bg, fg=sym_clr, anchor="w").pack(side="left")
            name_display = name if name else "(unknown)"
            name_suffix  = "  ✦ already selected" if in_db else "  ↓ will download"
            tk.Label(row, text=name_display, font=mono,
                     bg=bg, fg=CLR_SUBTEXT, anchor="w").pack(side="left")
            tk.Label(row, text=name_suffix, font=mono,
                     bg=bg, fg="#AAAAAA" if in_db else "#E06C00",
                     anchor="w").pack(side="left")

    def _resolve_bulk(symbols):
        db_syms  = set(check_vars)
        db_name  = dict(_name_cache)
        resolved: list    = []
        lock              = threading.Lock()
        pending           = [len(symbols)]
        order             = {s: i for i, s in enumerate(symbols)}

        def _on_done(results):
            root.after(0, lambda: _render_bulk_preview(results))

        for sym in symbols:
            threading.Thread(
                target=_yahoo_resolve_one,
                args=(sym, db_syms, db_name, _on_done,
                      resolved, lock, pending, order),
                daemon=True,
            ).start()

    def _trigger_bulk_mode(symbols):
        _bulk_active[0] = True
        add_new_btn.pack_forget()
        _clear_suggestions()
        _show_bulk_loading(symbols)
        _resolve_bulk(symbols)

    # ── Search-change handler ─────────────────────────────────────────────
    _ac_after_id = [None]

    def _on_search_change(*_):
        if _ac_after_id[0]:
            root.after_cancel(_ac_after_id[0])
        q = search_var.get().strip()

        if "," in q:
            # Bulk mode
            _clear_suggestions()
            add_new_btn.pack_forget()
            select_results_btn.pack_forget()
            symbols = _parse_bulk(q)
            if symbols:
                if _bulk_resolve_id[0]:
                    root.after_cancel(_bulk_resolve_id[0])
                _bulk_resolve_id[0] = root.after(
                    400, lambda s=symbols: _trigger_bulk_mode(s)
                )
            else:
                _hide_bulk()
            return

        # Single mode
        if _bulk_active[0]:
            _hide_bulk()
        _clear_suggestions()

        if len(q) < 1:
            add_new_btn.pack_forget()
            select_results_btn.pack_forget()
            return

        _ac_after_id[0] = root.after(350, lambda: threading.Thread(
            target=_yahoo_search,
            args=(q, lambda r: root.after(0, lambda: _show_suggestions(r))),
            daemon=True,
        ).start())

        exact = q.upper() in {s.upper() for s in check_vars}
        if not exact:
            add_new_btn.config(text=f"＋  Add \"{q.upper()}\" as new ticker")
            add_new_btn.pack(side="left", padx=(8, 0))
        else:
            add_new_btn.pack_forget()

        select_results_btn.pack(side="left", padx=(8, 0))

    search_var.trace_add("write", _on_search_change)
    search_var.trace_add("write", _apply_filter)

    def _add_new_from_btn():
        sym = search_var.get().strip().upper()
        if sym and "," not in sym:
            _add_ticker_sym(sym)

    add_new_btn.config(command=_add_new_from_btn)

    btn_cfg = dict(font=bold, relief="flat", bd=0, padx=12, pady=6, cursor="hand2")

    def _select_all():
        for sym in list(row_frames):
            try:
                if row_frames[sym].winfo_ismapped():
                    check_vars[sym].set(True)
            except Exception:
                pass
        _sync_all_buttons()

    def _clear_all():
        for v in check_vars.values():
            v.set(False)
        _sync_all_buttons()

    tk.Button(ctrl, text="✔  Select All", bg="#10B981", fg=CLR_BTN_FG,
              activebackground="#0D9E6E",
              command=_select_all, **btn_cfg).pack(side="left", padx=(0, 8))
    tk.Button(ctrl, text="✖  Clear All", bg="#EF4444", fg=CLR_BTN_FG,
              activebackground="#CC3333",
              command=_clear_all, **btn_cfg).pack(side="left")

    count_var = tk.StringVar(value="0 selected")
    tk.Label(ctrl, textvariable=count_var, bg=CLR_BG,
             fg=CLR_SUBTEXT, font=mono).pack(side="left", padx=12)

    # ── Pre-populate saved tickers (must be after count_var is defined) ───
    for sym in _initial_tickers:
        _add_ticker_sym(sym)

    # Re-download and Export toggles
    download_var = tk.BooleanVar(value=False)
    export_var   = tk.BooleanVar(value=False)

    def _make_option_toggle(frame, label, var, side="right", padx=(0, 8)):
        c = tk.Frame(frame, bg=CLR_BG)
        c.pack(side=side, padx=padx)
        b = tk.Button(c, text="☐", font=tick_font,
                      fg="#AAAAAA", bg=CLR_BG, activebackground=CLR_BG,
                      relief="flat", bd=0, cursor="hand2")
        b.pack(side="left")
        tk.Label(c, text=label, bg=CLR_BG,
                 fg=CLR_SUBTEXT, font=bold).pack(side="left")

        def _toggle():
            var.set(not var.get())
            b.config(text="☑" if var.get() else "☐",
                     fg=CLR_ACCENT if var.get() else "#AAAAAA")

        b.config(command=_toggle)

    # Rank mode
    rank_mode_var = tk.StringVar(value=saved_rank_mode)
    _rank_btns: dict = {}

    rank_row = tk.Frame(ctrl, bg=CLR_BG)
    rank_row.pack(side="left", padx=(12, 0))
    tk.Label(rank_row, text="Rank:", bg=CLR_BG,
             fg=CLR_SUBTEXT, font=bold).pack(side="left")

    def _select_rank(chosen):
        rank_mode_var.set(chosen)
        for val, btn in _rank_btns.items():
            btn.config(text="☑" if val == chosen else "☐",
                       fg=CLR_ACCENT if val == chosen else "#AAAAAA")

    for m_val, m_lbl in [("normal", "Normal"), ("weekly", "Weekly"), ("both", "Both")]:
        cell = tk.Frame(rank_row, bg=CLR_BG)
        cell.pack(side="left", padx=(8, 0))
        is_on = saved_rank_mode == m_val
        rb = tk.Button(cell, text="☑" if is_on else "☐",
                       font=tick_font,
                       fg=CLR_ACCENT if is_on else "#AAAAAA",
                       bg=CLR_BG, activebackground=CLR_BG,
                       relief="flat", bd=0, cursor="hand2",
                       command=lambda v=m_val: _select_rank(v))
        rb.pack(side="left")
        tk.Label(cell, text=m_lbl, bg=CLR_BG, fg=CLR_TEXT,
                 font=bold, cursor="hand2").pack(side="left")
        _rank_btns[m_val] = rb

    # Run button (rightmost)
    def _go():
        tickers = [s for s, v in check_vars.items() if v.get()]
        if not tickers:
            return
        on_run_cb(
            tickers,
            download_var.get(),
            export_var.get(),
            rank_mode_var.get(),
        )

    tk.Button(ctrl, text="▶  Run Watchlist",
              bg="#10B981", fg=CLR_BTN_FG,
              activebackground="#0D9668",
              command=_go, **btn_cfg).pack(side="right")

    _make_option_toggle(ctrl, "Export CSV", export_var, side="right", padx=(0, 8))
    _make_option_toggle(ctrl, "Re-download", download_var, side="right", padx=(0, 8))

    search_entry.focus_set()

    # ── Controller ────────────────────────────────────────────────────────
    def _get_selected() -> list[str]:
        return [s for s, v in check_vars.items() if v.get()]

    def _clear_picker():
        for v in check_vars.values():
            v.set(False)
        _sync_all_buttons()
        _update_summary()
        _update_count()
        search_var.set("")

    return {
        "get_selected": _get_selected,
        "clear":        _clear_picker,
    }