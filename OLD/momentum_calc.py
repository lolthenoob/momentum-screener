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
"""

import os
import sqlite3
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
PERIOD      = "2y"          # bumped to 2y — MA200 + regression need more history
TOP_N       = 50
STALE_HOURS = 20

EXP_REG_LEN = 90            # bars for exponential regression
DAYS_IN_YR  = 252


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
    """)
    conn.commit()
    return conn


def _stale_tickers(conn: sqlite3.Connection, tickers: list[str]) -> list[str]:
    cutoff = (datetime.now() - timedelta(hours=STALE_HOURS)).isoformat()
    rows = conn.execute(
        "SELECT symbol, fetched_at FROM fetch_log WHERE symbol IN ({})".format(
            ",".join("?" * len(tickers))
        ), tickers
    ).fetchall()
    fresh = {r[0] for r in rows if r[1] >= cutoff}
    return [t for t in tickers if t not in fresh]


def _store_prices(conn: sqlite3.Connection, data: pd.DataFrame, tickers: list[str]):
    now = datetime.now().isoformat(timespec="seconds")
    if data is None or data.empty:
        return

    close_df = None
    if isinstance(data.columns, pd.MultiIndex):
        levels = list(data.columns.names)
        try:
            if "Price" in levels:
                close_df = data.xs("Close", level="Price", axis=1)
            else:
                for lvl in range(data.columns.nlevels):
                    try:
                        close_df = data.xs("Close", level=lvl, axis=1)
                        break
                    except (KeyError, TypeError):
                        continue
        except (KeyError, TypeError):
            pass
    else:
        if "Close" in data.columns:
            sym = tickers[0]
            close_df = data[["Close"]].rename(columns={"Close": sym})

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


# ── Download ──────────────────────────────────────────────────────────────────

def download_prices(
    market_tickers: dict[str, list[str]],
    force_refresh: bool = False,
    log=None,
) -> pd.DataFrame:
    conn = _get_db()
    all_tickers = [t for tickers in market_tickers.values() for t in tickers]

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
    """Return (%K, %D) for last bar."""
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
    """CCI using close-only (typical price = close when OHLC unavailable)."""
    s = s.dropna()
    if len(s) < period:
        return None
    tp     = s                          # close-only approximation
    ma     = tp.rolling(period).mean()
    md     = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci    = (tp - ma) / (0.015 * md.replace(0, np.nan))
    val    = cci.iloc[-1]
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
    """ATR from close-only (true range = |close[t] - close[t-1]|)."""
    s = s.dropna()
    if len(s) < period + 1:
        return None
    tr  = s.diff().abs()
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if not np.isnan(atr) else None


def _ma_val(s: pd.Series, window: int) -> float | None:
    s = s.dropna()
    if len(s) < window:
        return None
    return float(s.rolling(window).mean().iloc[-1])


def _exp_reg_slope(s: pd.Series, length: int = EXP_REG_LEN) -> float | None:
    """
    Annualised exponential regression slope × R²  (Pine Script port).
    Returns value as a decimal (e.g. 0.25 = 25% annualised growth).
    """
    s = s.dropna()
    if len(s) < length:
        return None
    window = s.iloc[-length:].values
    nl     = np.log(window)
    x      = np.arange(length, dtype=float)
    # OLS slope of log(price) on bar index
    x_m    = x.mean();  y_m = nl.mean()
    x_std  = x.std();   y_std = nl.std()
    if x_std == 0 or y_std == 0:
        return None
    corr   = np.corrcoef(x, nl)[0, 1]
    slope  = corr * (y_std / x_std)
    # Annualise
    ann    = (np.exp(slope) ** DAYS_IN_YR - 1)
    # R² of log(price) vs cumulative bar index
    cum_x  = np.arange(1, length + 1, dtype=float)
    r2     = np.corrcoef(cum_x, nl)[0, 1] ** 2
    result = ann * r2
    return float(result) if np.isfinite(result) else None


def _risk_adj_momentum(s: pd.Series) -> float | None:
    """
    Mom's function — risk-adjusted momentum score.
    12-1M return ÷ annualised vol, z-scored (but z-score needs the full
    cross-section, so here we just return the raw ratio; z-scoring happens
    at the DataFrame level in _compute_signals).
    """
    s = s.dropna()
    if len(s) < 252:
        return None
    momentum = float(s.iloc[-21] / s.iloc[-252] - 1)
    daily_ret = s.pct_change().dropna()
    vol = float(daily_ret.iloc[-252:].std() * np.sqrt(252))
    if vol == 0:
        return None
    return momentum / vol


def _apply_ram_score(series: pd.Series) -> pd.Series:
    """
    Apply mom's z-score + winsorise + asymmetric mapping to a cross-section
    of raw risk-adjusted momentum values.
    """
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


# ── Main signal computation ───────────────────────────────────────────────────

def _compute_signals(prices: pd.DataFrame) -> pd.DataFrame:
    records = []
    for sym in prices.columns:
        col = prices[sym].dropna()
        if len(col) < 30:
            continue

        price = float(col.iloc[-1])

        # Returns
        ret_12_1 = None
        if len(col) >= 252:
            ret_12_1 = float(col.iloc[-21] / col.iloc[-252] - 1)
        ret_3m = _safe_ret(col, 63)

        # Oscillators
        rsi_val  = _rsi(col, 14)
        stoch_k, stoch_d = _stochastic(col, 14)
        cci_val  = _cci(col, 14)
        wpr_val  = _williams_r(col, 14)
        atr_val  = _atr(col, 15)

        # Exp regression slope × R²
        exp_slope = _exp_reg_slope(col, EXP_REG_LEN)

        # Raw risk-adjusted momentum ratio (z-scored cross-sectionally later)
        ram_raw  = _risk_adj_momentum(col)

        # MA levels
        ma25  = _ma_val(col, 25)
        ma50  = _ma_val(col, 50)
        ma100 = _ma_val(col, 100)
        ma200 = _ma_val(col, 200)

        above_ma25  = int(price > ma25)  if ma25  else None
        above_ma50  = int(price > ma50)  if ma50  else None
        above_ma100 = int(price > ma100) if ma100 else None
        above_ma200 = int(price > ma200) if ma200 else None

        # MA score = count of MAs price is above (0–4), used in composite
        ma_flags = [above_ma25, above_ma50, above_ma100, above_ma200]
        ma_score = sum(f for f in ma_flags if f is not None)

        records.append({
            "symbol":       sym,
            "price":        price,
            # composite inputs
            "ram_raw":      ram_raw,
            "exp_slope":    exp_slope,
            "ret_12_1":     ret_12_1,
            "ret_3m":       ret_3m,
            "stoch_k":      stoch_k,
            "rsi":          rsi_val,
            "cci":          cci_val,
            "wpr":          wpr_val,
            "ma_score":     float(ma_score),
            # raw info columns
            "stoch_d":      stoch_d,
            "atr":          atr_val,
            "above_ma25":   above_ma25,
            "above_ma50":   above_ma50,
            "above_ma100":  above_ma100,
            "above_ma200":  above_ma200,
        })

    df = pd.DataFrame(records).set_index("symbol")

    # Apply cross-sectional RAM score (needs full universe)
    if "ram_raw" in df.columns:
        raw = df["ram_raw"].dropna()
        if not raw.empty:
            df["ram_score"] = _apply_ram_score(raw)
        else:
            df["ram_score"] = np.nan

    return df


# ── Rank-normalise + composite ────────────────────────────────────────────────

def _rank_norm(series: pd.Series) -> pd.Series:
    """Rank-normalise to 0–100 across the available universe."""
    s = series.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    return s.rank(pct=True) * 100


# Williams %R is inverted (less negative = more bullish), so we flip it
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
    ("wpr",        _rank_norm_inv),   # Williams %R: higher (less negative) = bullish
    ("ma_score",   _rank_norm),
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

    signals = _compute_signals(prices)
    scored  = _score(signals)

    ticker_to_market = {
        t: market
        for market, tickers in market_tickers.items()
        for t in tickers
    }
    scored["market"] = scored.index.map(lambda s: ticker_to_market.get(s, "?"))

    overall = scored.dropna(subset=["momentum_score"]).head(top_n).copy()

    by_market = {}
    for market in market_tickers:
        mdf = scored[scored["market"] == market].dropna(subset=["momentum_score"])
        by_market[market] = mdf.head(top_n).copy()
        _log(log, f"  {market:<3} — {len(mdf)} scored, top {min(top_n, len(mdf))} kept")

    _log(log, f"  Overall top {len(overall)} computed")

    return {
        "overall":   overall,
        "by_market": by_market,
        "scored_at": datetime.now().isoformat(timespec="seconds"),
    }


def _log(log_fn, msg: str, end: str = "\n"):
    print(msg, end=end, flush=True)
    if log_fn:
        log_fn(msg)
