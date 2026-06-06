"""
momentum_calc.py
────────────────
Downloads price history for all tickers in batches, caches to SQLite,
and computes momentum scores. Returns top N results per market and overall.

Composite score (9 signals, rank-normalised 0–100, equally weighted):
  1. Risk-adjusted momentum  — 12-1M return ÷ annualised vol, z-scored & mapped
  2. Exp regression slope    — annualised log-regression slope × R² (90-day)
  3. 12-1 month return       — classic price momentum (skip last month)
  4. 3-month return          — shorter-term trend confirmation
  5. Stochastic %K (14)      — price position within recent high/low range
  6. RSI (14)                — momentum strength
  7. CCI (14)                — deviation from average price, scaled
  8. Williams %R (14)        — inverse of stochastic, overbought/oversold
  9. MA score                — count of MAs (25/50/100/200) price is above (0–4)

Raw columns (informational, not in composite):
  · ATR (15)                 — average true range, volatility context
  · MA25/50/100/200          — ✓ / ✗ flags

Signal cache:
  Scored results are persisted to momentum.db after every compute.
  On subsequent runs (no download, no force-recompute) the cached
  signals are loaded directly — no price processing required.
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

# ── Config ────────────────────────────────────────────────────────────────────

_BASE       = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(_BASE, "data", "momentum.db")
BATCH_SZ    = 100
PERIOD      = "2y"
TOP_N       = 50

EXP_REG_LEN = 90
DAYS_IN_YR  = 252

# Signal cache column list — must match _compute_signals output exactly
_SIGNAL_COLS = [
    "price", "ram_raw", "ram_score", "exp_slope", "ret_12_1", "ret_3m",
    "stoch_k", "stoch_d", "rsi", "cci", "wpr", "atr", "ma_score",
    "above_ma25", "above_ma50", "above_ma100", "above_ma200",
    "vol_ratio", "high_52w_pct", "rank_change",
    "market", "momentum_score", "name", "sector",
]


# ── DB setup ──────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_cache (
            symbol      TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            close       REAL,
            PRIMARY KEY (symbol, trade_date)
        );
        CREATE TABLE IF NOT EXISTS fetch_log (
            symbol      TEXT PRIMARY KEY,
            fetched_at  TEXT NOT NULL,
            rows_stored INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS signal_cache (
            symbol      TEXT PRIMARY KEY,
            data_json   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_log (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            scored_at   TEXT NOT NULL,
            top_n       INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_prev (
            symbol      TEXT PRIMARY KEY,
            data_json   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS signal_prev_log (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            scored_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS name_cache (
            symbol      TEXT PRIMARY KEY,
            name        TEXT NOT NULL DEFAULT '',
            fetched_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS volume_cache (
            symbol      TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            volume      REAL,
            PRIMARY KEY (symbol, trade_date)
        );
        CREATE TABLE IF NOT EXISTS sector_cache (
            symbol      TEXT PRIMARY KEY,
            sector      TEXT NOT NULL DEFAULT '',
            fetched_at  TEXT NOT NULL
        );
    """)
    conn.commit()
    return conn


# ── Price cache helpers ───────────────────────────────────────────────────────

def _stale_tickers(conn: sqlite3.Connection, tickers: list[str]) -> list[str]:
    """Return tickers that have never been fetched (no entry in fetch_log at all)."""
    if not tickers:
        return []
    rows = conn.execute(
        "SELECT symbol FROM fetch_log WHERE symbol IN ({})".format(
            ",".join("?" * len(tickers))
        ), tickers
    ).fetchall()
    fetched = {r[0] for r in rows}
    return [t for t in tickers if t not in fetched]


def _store_prices(conn: sqlite3.Connection, data: pd.DataFrame, tickers: list[str]):
    now = datetime.now().isoformat(timespec="seconds")
    if data is None or data.empty:
        return

    close_df  = None
    volume_df = None

    if isinstance(data.columns, pd.MultiIndex):
        levels = list(data.columns.names)
        try:
            if "Price" in levels:
                close_df  = data.xs("Close",  level="Price", axis=1)
                try:
                    volume_df = data.xs("Volume", level="Price", axis=1)
                except (KeyError, TypeError):
                    pass
            else:
                for lvl in range(data.columns.nlevels):
                    try:
                        close_df = data.xs("Close", level=lvl, axis=1)
                        try:
                            volume_df = data.xs("Volume", level=lvl, axis=1)
                        except (KeyError, TypeError):
                            pass
                        break
                    except (KeyError, TypeError):
                        continue
        except (KeyError, TypeError):
            pass
    else:
        if "Close" in data.columns:
            sym = tickers[0]
            close_df = data[["Close"]].rename(columns={"Close": sym})
        if "Volume" in data.columns:
            sym = tickers[0]
            volume_df = data[["Volume"]].rename(columns={"Volume": sym})

    if close_df is None or (hasattr(close_df, "empty") and close_df.empty):
        return
    if isinstance(close_df, pd.Series):
        name = close_df.name if close_df.name else tickers[0]
        close_df = close_df.to_frame(name=name)

    rows_per_ticker = {}
    insert_rows = []
    for sym in close_df.columns:
        series = close_df[sym].dropna()
        count = 0
        for dt, price in series.items():
            insert_rows.append((sym, dt.strftime("%Y-%m-%d"), float(price)))
            count += 1
        rows_per_ticker[sym] = count

    conn.executemany(
        "INSERT OR REPLACE INTO price_cache (symbol, trade_date, close) VALUES (?, ?, ?)",
        insert_rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO fetch_log (symbol, fetched_at, rows_stored) VALUES (?, ?, ?)",
        [(sym, now, rows_per_ticker.get(sym, 0)) for sym in close_df.columns],
    )

    # Store volume if available
    if volume_df is not None:
        if isinstance(volume_df, pd.Series):
            name = volume_df.name if volume_df.name else tickers[0]
            volume_df = volume_df.to_frame(name=name)
        vol_rows = []
        for sym in volume_df.columns:
            for dt, vol in volume_df[sym].dropna().items():
                vol_rows.append((sym, dt.strftime("%Y-%m-%d"), float(vol)))
        if vol_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO volume_cache (symbol, trade_date, volume) VALUES (?, ?, ?)",
                vol_rows,
            )

    conn.commit()


def _load_prices(conn: sqlite3.Connection, tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    rows = conn.execute(
        "SELECT symbol, trade_date, close FROM price_cache WHERE symbol IN ({}) ORDER BY trade_date".format(
            ",".join("?" * len(tickers))
        ), tickers
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    pivot = df.pivot(index="date", columns="symbol", values="close")
    pivot.index = pd.to_datetime(pivot.index)
    return pivot


# ── Signal cache helpers ──────────────────────────────────────────────────────

def save_signals(results: dict):
    """Persist the scored results dict to signal_cache and signal_log tables."""
    try:
        conn = _get_db()

        # Combine overall into a single DataFrame keyed by symbol
        overall = results.get("overall")
        by_market = results.get("by_market", {})
        scored_at = results.get("scored_at", datetime.now().isoformat(timespec="seconds"))
        top_n = len(overall) if overall is not None else 0

        # Build a full universe DataFrame from all market results
        frames = []
        if overall is not None and not overall.empty:
            frames.append(overall)
        for mdf in by_market.values():
            if mdf is not None and not mdf.empty:
                frames.append(mdf)

        if not frames:
            conn.close()
            return

        combined = pd.concat(frames)
        combined = combined[~combined.index.duplicated(keep="first")]

        rows = []
        for sym, row in combined.iterrows():
            d = {}
            for col in _SIGNAL_COLS:
                val = row.get(col)
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    d[col] = None
                else:
                    d[col] = val
            rows.append((sym, json.dumps(d)))

        # Snapshot current signals into signal_prev before overwriting
        prev_rows = conn.execute(
            "SELECT symbol, data_json FROM signal_cache"
        ).fetchall()
        if prev_rows:
            conn.execute("DELETE FROM signal_prev")
            conn.executemany(
                "INSERT INTO signal_prev (symbol, data_json) VALUES (?, ?)", prev_rows
            )
            conn.execute(
                "INSERT OR REPLACE INTO signal_prev_log (id, scored_at) VALUES (1, ?)",
                (conn.execute(
                    "SELECT scored_at FROM signal_log WHERE id = 1"
                ).fetchone() or (scored_at,))[0:1]
            )

        conn.execute("DELETE FROM signal_cache")
        conn.executemany(
            "INSERT INTO signal_cache (symbol, data_json) VALUES (?, ?)", rows
        )
        conn.execute(
            "INSERT OR REPLACE INTO signal_log (id, scored_at, top_n) VALUES (1, ?, ?)",
            (scored_at, top_n)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  ⚠  signal cache save failed: {e}")


def load_signals(market_tickers: dict, top_n: int = TOP_N, log=None) -> dict | None:
    """
    Load previously scored results from signal_cache.
    Returns None if cache is empty or missing.
    """
    try:
        conn = _get_db()

        log_row = conn.execute(
            "SELECT scored_at, top_n FROM signal_log WHERE id = 1"
        ).fetchone()
        if not log_row:
            conn.close()
            return None

        scored_at = log_row[0]
        rows = conn.execute(
            "SELECT symbol, data_json FROM signal_cache"
        ).fetchall()

        if not rows:
            conn.close()
            return None

        records = []
        for sym, data_json in rows:
            d = json.loads(data_json)
            d["symbol"] = sym
            records.append(d)

        df = pd.DataFrame(records).set_index("symbol")

        # Rebuild numeric columns
        for col in _SIGNAL_COLS:
            if col in df.columns and col not in ("market", "name", "sector"):
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "momentum_score" not in df.columns or df.empty:
            conn.close()
            return None

        ticker_to_market = {
            t: market
            for market, tickers in market_tickers.items()
            for t in tickers
        }
        if "market" not in df.columns or df["market"].isna().all():
            df["market"] = df.index.map(lambda s: ticker_to_market.get(s, "?"))

        df = df.sort_values("momentum_score", ascending=False, na_position="last")
        df = _attach_rank_change(df, conn)
        conn.close()

        overall = df.dropna(subset=["momentum_score"]).head(top_n).copy()

        by_market = {}
        for market in market_tickers:
            mdf = df[df["market"] == market].dropna(subset=["momentum_score"])
            by_market[market] = mdf.head(top_n).copy()
            _log(log, f"  {market:<3} — {len(mdf)} cached signals, top {min(top_n, len(mdf))} kept")

        _log(log, f"  Overall top {len(overall)} loaded from cache")

        return {
            "overall":   overall,
            "by_market": by_market,
            "scored_at": scored_at,
        }

    except Exception as e:
        print(f"  ⚠  signal cache load failed: {e}")
        return None



def _attach_rank_change(df, conn):
    """
    Attach a rank_change column to df.
    Positive = moved up (e.g. +3 means ranked 3 places higher than last run).
    Negative = moved down. NaN = new entry (not in previous signals).
    Rank is determined by momentum_score position within the full signal_prev universe.
    """
    try:
        prev_rows = conn.execute(
            "SELECT symbol, data_json FROM signal_prev"
        ).fetchall()
        if not prev_rows:
            df["rank_change"] = np.nan
            return df

        prev_scores = {}
        for sym, data_json in prev_rows:
            try:
                d = json.loads(data_json)
                score = d.get("momentum_score")
                if score is not None:
                    prev_scores[sym] = float(score)
            except Exception:
                pass

        if not prev_scores:
            df["rank_change"] = np.nan
            return df

        # Higher score = rank 1 = best
        prev_series = pd.Series(prev_scores).sort_values(ascending=False)
        prev_rank   = {sym: i + 1 for i, sym in enumerate(prev_series.index)}

        # Current rank from df (already sorted by momentum_score descending)
        curr_rank = {sym: i + 1 for i, sym in enumerate(df.index)}

        changes = {}
        for sym in df.index:
            curr = curr_rank.get(sym)
            prev = prev_rank.get(sym)
            if curr is not None and prev is not None:
                changes[sym] = prev - curr   # positive = moved up
            else:
                changes[sym] = np.nan

        df["rank_change"] = pd.Series(changes)
    except Exception as e:
        print(f"  \u26a0  rank_change attach failed: {e}")
        df["rank_change"] = np.nan

    return df


def signal_cache_info() -> tuple[str | None, int | None]:
    """
    Returns (scored_at_isostring, top_n) from signal_log, or (None, None).
    scored_at is an ISO timestamp string.
    """
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT scored_at, top_n FROM signal_log WHERE id = 1"
        ).fetchone()
        conn.close()
        if row:
            return row[0], row[1]
        return None, None
    except Exception:
        return None, None


# ── Download ──────────────────────────────────────────────────────────────────

def download_prices(
    market_tickers: dict[str, list[str]],
    force_refresh: bool = False,
    log=None,
) -> pd.DataFrame:
    conn = _get_db()
    all_tickers = [t for tickers in market_tickers.values() for t in tickers]

    # Only fetch tickers that have never been downloaded.
    # force_refresh downloads everything regardless.
    to_fetch = all_tickers if force_refresh else _stale_tickers(conn, all_tickers)

    if to_fetch:
        total_batches = (len(to_fetch) + BATCH_SZ - 1) // BATCH_SZ
        _log(log, f"\n  Downloading prices for {len(to_fetch)} tickers "
                  f"({total_batches} batches of up to {BATCH_SZ})…")
        for i in range(0, len(to_fetch), BATCH_SZ):
            batch   = to_fetch[i:i + BATCH_SZ]
            batch_n = i // BATCH_SZ + 1
            _log(log, f"  Batch {batch_n}/{total_batches} — {len(batch)} tickers…", end="")
            try:
                data = yf.download(
                    batch, period=PERIOD, interval="1d",
                    group_by="ticker", auto_adjust=True,
                    progress=False, threads=True,
                )
                _store_prices(conn, data, batch)
                _log(log, " OK")
            except Exception as e:
                _log(log, f" FAILED ({e})")
    else:
        _log(log, f"  All {len(all_tickers)} tickers cached — skipping download")

    prices = _load_prices(conn, all_tickers)
    conn.close()
    return prices


# ── Individual signal helpers ─────────────────────────────────────────────────

def _safe_ret(s: pd.Series, n: int) -> float | None:
    s = s.dropna()
    if len(s) < n + 1:
        return None
    return float(s.iloc[-1] / s.iloc[-n - 1] - 1)


def _rsi(s: pd.Series, period: int = 14) -> float | None:
    s = s.dropna()
    if len(s) < period + 1:
        return None
    delta = s.diff().dropna()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    val   = rsi.iloc[-1]
    return float(val) if not np.isnan(val) else None


def _stochastic(s: pd.Series, period: int = 14) -> tuple[float | None, float | None]:
    s = s.dropna()
    if len(s) < period + 3:
        return None, None
    lo  = s.rolling(period).min()
    hi  = s.rolling(period).max()
    k   = 100 * (s - lo) / (hi - lo).replace(0, np.nan)
    d   = k.rolling(3).mean()
    kv  = k.iloc[-1]
    dv  = d.iloc[-1]
    return (
        float(kv) if not np.isnan(kv) else None,
        float(dv) if not np.isnan(dv) else None,
    )


def _cci(s: pd.Series, period: int = 14) -> float | None:
    s = s.dropna()
    if len(s) < period:
        return None
    tp  = s
    ma  = tp.rolling(period).mean()
    md  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - ma) / (0.015 * md.replace(0, np.nan))
    val = cci.iloc[-1]
    return float(val) if not np.isnan(val) else None


def _williams_r(s: pd.Series, period: int = 14) -> float | None:
    s = s.dropna()
    if len(s) < period:
        return None
    hi  = s.rolling(period).max()
    lo  = s.rolling(period).min()
    wr  = -100 * (hi - s) / (hi - lo).replace(0, np.nan)
    val = wr.iloc[-1]
    return float(val) if not np.isnan(val) else None


def _atr(s: pd.Series, period: int = 15) -> float | None:
    s = s.dropna()
    if len(s) < period + 1:
        return None
    tr  = s.diff().abs()
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if not np.isnan(atr) else None


def _ma_val(s: pd.Series, window: int) -> float | None:
    s = s.dropna()
    if len(s) < window:
        if len(s) >= max(10, int(window * 0.6)):
            return float(s.mean())
        return None
    return float(s.rolling(window).mean().iloc[-1])


def _load_volume(conn: sqlite3.Connection, tickers: list[str]) -> pd.DataFrame:
    """Load volume history from volume_cache. Returns wide DataFrame (dates × symbols)."""
    if not tickers:
        return pd.DataFrame()
    rows = conn.execute(
        "SELECT symbol, trade_date, volume FROM volume_cache WHERE symbol IN ({}) ORDER BY trade_date".format(
            ",".join("?" * len(tickers))
        ), tickers
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "date", "volume"])
    pivot = df.pivot(index="date", columns="symbol", values="volume")
    pivot.index = pd.to_datetime(pivot.index)
    return pivot


def _vol_ratio(vol: pd.Series, short: int = 20, long: int = 50) -> float | None:
    """
    20-day average volume divided by 50-day average volume.
    > 1.0 means recent volume is elevated vs the longer baseline.
    Requires at least long+1 rows.
    """
    vol = vol.dropna()
    if len(vol) < long + 1:
        return None
    avg_short = float(vol.iloc[-short:].mean())
    avg_long  = float(vol.iloc[-long:].mean())
    if avg_long == 0:
        return None
    ratio = avg_short / avg_long
    return float(ratio) if np.isfinite(ratio) else None


def _high_52w_pct(price_series: pd.Series) -> float | None:
    """
    How close current price is to the 52-week high, as a percentage below it.
    0 % = at the 52-week high. -10 % = 10 % below it.
    Requires at least 252 days of history.
    """
    s = price_series.dropna()
    if len(s) < 252:
        return None
    high = float(s.iloc[-252:].max())
    price = float(s.iloc[-1])
    if high == 0:
        return None
    return float((price / high) - 1)


def _exp_reg_slope(s: pd.Series, length: int = EXP_REG_LEN) -> float | None:
    s = s.dropna()
    if len(s) < length:
        return None
    window = s.iloc[-length:].values
    nl     = np.log(window)
    x      = np.arange(length, dtype=float)
    x_m    = x.mean();  y_m = nl.mean()
    x_std  = x.std();   y_std = nl.std()
    if x_std == 0 or y_std == 0:
        return None
    corr   = np.corrcoef(x, nl)[0, 1]
    slope  = corr * (y_std / x_std)
    ann    = (np.exp(slope) ** DAYS_IN_YR - 1)
    cum_x  = np.arange(1, length + 1, dtype=float)
    r2     = np.corrcoef(cum_x, nl)[0, 1] ** 2
    result = ann * r2
    return float(result) if np.isfinite(result) else None


def _risk_adj_momentum(s: pd.Series) -> float | None:
    s = s.dropna()
    if len(s) < 252:
        return None
    momentum  = float(s.iloc[-21] / s.iloc[-252] - 1)
    daily_ret = s.pct_change().dropna()
    vol       = float(daily_ret.iloc[-252:].std() * np.sqrt(252))
    if vol == 0:
        return None
    return momentum / vol


def _apply_ram_score(series: pd.Series) -> pd.Series:
    mean = series.mean()
    std  = series.std()
    if std == 0:
        return pd.Series(np.nan, index=series.index)
    z = ((series - mean) / std).clip(-3, 3)
    score = pd.Series(index=z.index, dtype=float)
    pos = z >= 0
    neg = z < 0
    score[pos] = 1 + z[pos]
    score[neg] = 1 / (1 - z[neg])
    return score


# ── Name cache helpers ────────────────────────────────────────────────────────

def _load_names(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, str]:
    """Read names from name_cache for the given tickers. Returns {symbol: name}."""
    if not tickers:
        return {}
    rows = conn.execute(
        "SELECT symbol, name FROM name_cache WHERE symbol IN ({})".format(
            ",".join("?" * len(tickers))
        ), tickers
    ).fetchall()
    return {sym: name for sym, name in rows}


def _store_names(conn: sqlite3.Connection, names: dict[str, str]):
    """Write {symbol: name} dict into name_cache, upserting existing rows."""
    if not names:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR REPLACE INTO name_cache (symbol, name, fetched_at) VALUES (?, ?, ?)",
        [(sym, name or "", now) for sym, name in names.items()],
    )
    conn.commit()


# ── Name lookup ───────────────────────────────────────────────────────────────

def _fetch_names(tickers: list[str], log=None) -> dict[str, str]:
    """
    Fetch longName for each ticker via yfinance, storing results in name_cache.
    On subsequent calls, cached names are returned immediately — no network call.
    Only tickers missing from the cache hit the network.
    """
    if not tickers:
        return {}

    conn = _get_db()
    cached = _load_names(conn, tickers)
    missing = [t for t in tickers if t not in cached]

    if missing:
        _log(log, f"  Fetching names for {len(missing)} tickers "
                  f"({len(cached)} already cached)…")
        fetched = {}
        total = len(missing)
        for i, sym in enumerate(missing):
            try:
                info = yf.Ticker(sym).fast_info
                name = getattr(info, "long_name", None)
                if not name:
                    full = yf.Ticker(sym).info
                    name = full.get("longName") or full.get("shortName") or ""
                fetched[sym] = name or ""
            except Exception:
                fetched[sym] = ""
            if (i + 1) % 10 == 0 or (i + 1) == total:
                _log(log, f"  Names: {i + 1}/{total}")

        _store_names(conn, fetched)
        cached.update(fetched)
    else:
        _log(log, f"  Names: all {len(tickers)} loaded from cache")

    conn.close()
    return {t: cached.get(t, "") for t in tickers}





# ── Sector cache helpers ──────────────────────────────────────────────────────

def _load_sectors(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, str]:
    """Read sectors from sector_cache. Returns {symbol: sector}."""
    if not tickers:
        return {}
    rows = conn.execute(
        "SELECT symbol, sector FROM sector_cache WHERE symbol IN ({})".format(
            ",".join("?" * len(tickers))
        ), tickers
    ).fetchall()
    return {sym: sector for sym, sector in rows}


def _store_sectors(conn: sqlite3.Connection, sectors: dict[str, str]):
    if not sectors:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR REPLACE INTO sector_cache (symbol, sector, fetched_at) VALUES (?, ?, ?)",
        [(sym, sector or "", now) for sym, sector in sectors.items()],
    )
    conn.commit()


def _fetch_sectors(tickers: list[str], log=None) -> dict[str, str]:
    """
    Fetch sector for each ticker via yfinance .info, caching results permanently.
    Only tickers not already in sector_cache hit the network.
    """
    if not tickers:
        return {}

    conn = _get_db()
    cached = _load_sectors(conn, tickers)
    missing = [t for t in tickers if t not in cached]

    if missing:
        _log(log, f"  Fetching sectors for {len(missing)} tickers "
                  f"({len(cached)} already cached)…")
        fetched = {}
        total = len(missing)
        for i, sym in enumerate(missing):
            try:
                info   = yf.Ticker(sym).info
                sector = info.get("sector") or info.get("industry") or ""
                fetched[sym] = sector
            except Exception:
                fetched[sym] = ""
            if (i + 1) % 10 == 0 or (i + 1) == total:
                _log(log, f"  Sectors: {i + 1}/{total}")

        _store_sectors(conn, fetched)
        cached.update(fetched)
    else:
        _log(log, f"  Sectors: all {len(tickers)} loaded from cache")

    conn.close()
    return {t: cached.get(t, "") for t in tickers}


def _compute_signals(prices: pd.DataFrame, volumes: pd.DataFrame | None = None) -> pd.DataFrame:
    records = []
    for sym in prices.columns:
        col = prices[sym].dropna()
        if len(col) < 30:
            continue

        price = float(col.iloc[-1])

        ret_12_1 = None
        if len(col) >= 252:
            ret_12_1 = float(col.iloc[-21] / col.iloc[-252] - 1)
        ret_3m = _safe_ret(col, 63)

        rsi_val          = _rsi(col, 14)
        stoch_k, stoch_d = _stochastic(col, 14)
        cci_val          = _cci(col, 14)
        wpr_val          = _williams_r(col, 14)
        atr_val          = _atr(col, 15)
        exp_slope        = _exp_reg_slope(col, EXP_REG_LEN)
        ram_raw          = _risk_adj_momentum(col)
        high_52w         = _high_52w_pct(col)

        vol_ratio_val = None
        if volumes is not None and sym in volumes.columns:
            vol_ratio_val = _vol_ratio(volumes[sym])

        ma25  = _ma_val(col, 25)
        ma50  = _ma_val(col, 50)
        ma100 = _ma_val(col, 100)
        ma200 = _ma_val(col, 200)

        above_ma25  = int(price > ma25)  if ma25  else None
        above_ma50  = int(price > ma50)  if ma50  else None
        above_ma100 = int(price > ma100) if ma100 else None
        above_ma200 = int(price > ma200) if ma200 else None

        ma_flags = [above_ma25, above_ma50, above_ma100, above_ma200]
        ma_score = sum(f for f in ma_flags if f is not None)

        records.append({
            "symbol":       sym,
            "price":        price,
            "ram_raw":      ram_raw,
            "exp_slope":    exp_slope,
            "ret_12_1":     ret_12_1,
            "ret_3m":       ret_3m,
            "stoch_k":      stoch_k,
            "rsi":          rsi_val,
            "cci":          cci_val,
            "wpr":          wpr_val,
            "ma_score":     float(ma_score),
            "stoch_d":      stoch_d,
            "atr":          atr_val,
            "above_ma25":   above_ma25,
            "above_ma50":   above_ma50,
            "above_ma100":  above_ma100,
            "above_ma200":  above_ma200,
            "vol_ratio":    vol_ratio_val,
            "high_52w_pct": high_52w,
        })

    df = pd.DataFrame(records).set_index("symbol")

    if "ram_raw" in df.columns:
        raw = df["ram_raw"].dropna()
        if not raw.empty:
            df["ram_score"] = _apply_ram_score(raw)
        else:
            df["ram_score"] = np.nan

    return df


# ── Rank-normalise + composite ────────────────────────────────────────────────

def _rank_norm(series: pd.Series) -> pd.Series:
    s = series.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    return s.rank(pct=True) * 100


def _rank_norm_inv(series: pd.Series) -> pd.Series:
    return _rank_norm(-series)


COMPOSITE_SIGNALS = [
    ("ram_score",  _rank_norm),
    ("exp_slope",  _rank_norm),
    ("ret_12_1",   _rank_norm),
    ("ret_3m",     _rank_norm),
    ("stoch_k",    _rank_norm),
    ("rsi",        _rank_norm),
    ("cci",        _rank_norm),
    ("wpr",        _rank_norm_inv),
    ("ma_score",   _rank_norm),
    ("vol_ratio",  _rank_norm),
]


def _score(df: pd.DataFrame) -> pd.DataFrame:
    rank_cols = []
    for col, fn in COMPOSITE_SIGNALS:
        if col in df.columns:
            rk_col = f"rank_{col}"
            df[rk_col] = fn(df[col])
            rank_cols.append(rk_col)
    df["momentum_score"] = df[rank_cols].mean(axis=1)
    return df.sort_values("momentum_score", ascending=False)


# ── Cache age helpers ─────────────────────────────────────────────────────────

def cache_data_age_days() -> int | None:
    """Days since most recent price fetch, or None if no cache."""
    try:
        conn = _get_db()
        row  = conn.execute("SELECT MAX(fetched_at) FROM fetch_log").fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        last = datetime.fromisoformat(row[0])
        return (datetime.now() - last).days
    except Exception:
        return None


def cache_signals_age_days() -> int | None:
    """Days since signals were last scored, or None if no signal cache."""
    try:
        scored_at, _ = signal_cache_info()
        if not scored_at:
            return None
        last = datetime.fromisoformat(scored_at)
        return (datetime.now() - last).days
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def run_screener(
    market_tickers: dict[str, list[str]],
    prices: pd.DataFrame,
    top_n: int = TOP_N,
    log=None,
) -> dict:
    _log(log, "\n  Computing momentum signals…")

    if prices.empty:
        _log(log, "  No price data available.")
        return {}

    conn        = _get_db()
    all_tickers = list(prices.columns)
    volumes     = _load_volume(conn, all_tickers)

    signals = _compute_signals(prices, volumes if not volumes.empty else None)
    scored  = _score(signals)

    ticker_to_market = {
        t: market
        for market, tickers in market_tickers.items()
        for t in tickers
    }
    scored["market"] = scored.index.map(lambda s: ticker_to_market.get(s, "?"))
    scored = _attach_rank_change(scored, conn)
    conn.close()

    overall = scored.dropna(subset=["momentum_score"]).head(top_n).copy()

    by_market = {}
    for market in market_tickers:
        mdf = scored[scored["market"] == market].dropna(subset=["momentum_score"])
        by_market[market] = mdf.head(top_n).copy()
        _log(log, f"  {market:<3} — {len(mdf)} scored, top {min(top_n, len(mdf))} kept")

    _log(log, f"  Overall top {len(overall)} computed")

    # Fetch display names for every ticker that appears in any result set
    all_result_syms = list(
        dict.fromkeys(
            list(overall.index)
            + [s for mdf in by_market.values() for s in mdf.index]
        )
    )
    names   = _fetch_names(all_result_syms, log=log)
    sectors = _fetch_sectors(all_result_syms, log=log)
    overall["name"]   = overall.index.map(lambda s: names.get(s, ""))
    overall["sector"] = overall.index.map(lambda s: sectors.get(s, ""))
    for market in by_market:
        by_market[market]["name"]   = by_market[market].index.map(lambda s: names.get(s, ""))
        by_market[market]["sector"] = by_market[market].index.map(lambda s: sectors.get(s, ""))

    results = {
        "overall":   overall,
        "by_market": by_market,
        "scored_at": datetime.now().isoformat(timespec="seconds"),
    }

    # Always persist signals after computing
    save_signals(results)

    return results


def _log(log_fn, msg: str, end: str = "\n"):
    print(msg, end=end, flush=True)
    if log_fn:
        log_fn(msg)

def clear_price_cache():
    """
    Delete all rows from price_cache and fetch_log.
    The next run with 'Download latest prices' ticked will re-fetch everything.
    Returns (rows_deleted: int, error: str|None).
    """
    try:
        conn = _get_db()
        price_rows = conn.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
        conn.execute("DELETE FROM price_cache")
        conn.execute("DELETE FROM fetch_log")
        conn.execute("DELETE FROM volume_cache")
        conn.commit()
        conn.close()
        return price_rows, None
    except Exception as e:
        return 0, str(e)


def clear_signal_cache():
    """
    Delete all rows from signal_cache and signal_log.
    The next run will recompute signals from whatever price data is in the DB.
    Returns (rows_deleted: int, error: str|None).
    """
    try:
        conn = _get_db()
        sig_rows = conn.execute("SELECT COUNT(*) FROM signal_cache").fetchone()[0]
        conn.execute("DELETE FROM signal_cache")
        conn.execute("DELETE FROM signal_log")
        conn.commit()
        conn.close()
        return sig_rows, None
    except Exception as e:
        return 0, str(e)