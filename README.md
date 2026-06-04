# momentum-screener

> Multi-market momentum stock screener — US, AU, NZ, SG — powered by yfinance with SQLite price caching.

Companion project to [fundamentals-dashboard](https://github.com/lolthenoob/fundamentals-dashboard).

---

## Quick start

```
git clone <your-repo-url>
cd momentum-screener
pip install -r requirements.txt
python main.py
```

---

## How it works

### 1. Ticker lists

| Market | Source | Count |
|--------|--------|-------|
| US     | S&P 500 via Wikipedia | ~503 |
| AU     | ASX 300 via ASX.com.au | ~300 |
| NZ     | NZX 50 (static list) | ~50 |
| SG     | STI + SGX large-cap | ~40 |

Lists are cached in `data/tickers_<market>.json` and re-fetched weekly.

### 2. Price download

All tickers are downloaded in batches of 100 using `yf.download()` — one API call per batch, not one per ticker. Prices are cached in `data/momentum.db` (SQLite) and only re-downloaded if the cache is older than 20 hours.

First run with an empty cache: ~2–4 minutes depending on connection speed.  
Subsequent runs: usually under 10 seconds.

### 3. Momentum scoring

Five signals, each rank-normalised to 0–100 across the full universe:

| Signal | Description |
|--------|-------------|
| 12-1M return | Classic price momentum — 12 months back, skip last month |
| 3M return | Short-term trend confirmation |
| Price vs 200MA | Trend regime filter (above = bullish) |
| RSI 14 | Momentum strength, capped at 75 to avoid overbought chasing |
| MA20/MA50 ratio | Short vs medium MA alignment |

**Final score = average of the five rank signals (0–100)**

### 4. Results

Interactive sortable table with tabs:
- **Overall** — top 50 across all four markets combined
- **US / AU / NZ / SG** — top 50 within each market

Click any column header to sort ascending/descending.

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Launcher UI + status window |
| `ticker_loader.py` | Fetches and caches ticker lists per market |
| `momentum_calc.py` | Batch price download, signal calc, scoring |
| `screener_table.py` | Interactive results table |
| `data/` | SQLite price cache + ticker list JSON files |

---

## Notes

- Yahoo Finance data is for personal/research use only.
- NZX tickers occasionally have thin volume — low RSI/momentum scores are expected for smaller NZ stocks.
- SGX tickers use the `.SI` suffix format used by Yahoo Finance.

---

## License

MIT
