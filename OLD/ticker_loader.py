"""
ticker_loader.py
────────────────
Loads and caches ticker lists for all four markets.

  US  — S&P 500 scraped from Wikipedia
  AU  — ASX listed companies CSV (downloaded by user from ASX website)
  NZ  — NZSX scraped live from nzx.com
  SG  — Top SGX stocks scraped from stockanalysis.com

Each market list is cached in data/tickers_<market>.json.
Re-fetched automatically if cache is older than CACHE_DAYS days.

Returns { "US": [...], "AU": [...], "NZ": [...], "SG": [...] }
Each entry is a plain ticker string ready for yfinance (suffixes included).
"""

import os
import json
import re
import urllib.request
from datetime import datetime, timedelta

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

# ── Config ────────────────────────────────────────────────────────────────────

_BASE      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(_BASE, "data")
CACHE_DAYS = 7

MARKETS = ["US", "AU", "NZ", "SG"]

# How many top-N SGX stocks to include (by market cap order on stockanalysis.com)
SGX_TOP_N = 150

# AU CSV — user downloads this from ASX and drops it in the data/ folder.
# Filename pattern: ASX_Listed_Companies_*.csv
ASX_CSV_URL = "https://www.asx.com.au/markets/trade-our-cash-market/directory"


# ── Fallback lists (used if all live sources fail) ───────────────────────────

_FALLBACK = {
    "US": [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","BRK-B","LLY","AVGO",
        "TSLA","WMT","JPM","UNH","XOM","V","ORCL","MA","COST","HD","PG","JNJ",
        "ABBV","BAC","NFLX","CRM","CVX","MRK","KO","AMD","PEP","TMO","ACN",
        "MCD","CSCO","IBM","GE","DHR","ABT","INTC","INTU","NOW","RTX","CAT",
        "AMGN","SPGI","GS","TXN","NEE","ISRG","BLK","SYK","AXP","VRTX","BKNG",
    ],
    "AU": [
        "BHP.AX","CBA.AX","CSL.AX","NAB.AX","WBC.AX","ANZ.AX","MQG.AX",
        "WES.AX","RIO.AX","TLS.AX","WOW.AX","GMG.AX","FMG.AX","REA.AX",
        "COL.AX","TCL.AX","STO.AX","ALL.AX","IAG.AX","QBE.AX","XRO.AX",
        "BXB.AX","CPU.AX","JHX.AX","MIN.AX","ORG.AX","QAN.AX","SHL.AX",
        "WDS.AX","AMC.AX","AMP.AX","BOQ.AX","BEN.AX","CAR.AX","CWY.AX",
    ],
    "NZ": [
        "FPH.NZ","ATM.NZ","MEL.NZ","CEN.NZ","SPK.NZ","AIA.NZ","RYM.NZ",
        "PCT.NZ","MFT.NZ","SKC.NZ","WHS.NZ","VHP.NZ","IFT.NZ","NZX.NZ",
        "PFI.NZ","ARG.NZ","GNE.NZ","HLG.NZ","KMD.NZ","SCL.NZ","SKT.NZ",
        "STU.NZ","SUM.NZ","TRA.NZ","TWR.NZ","VCT.NZ","GTK.NZ","EBO.NZ",
        "FBU.NZ","FCG.NZ","CHI.NZ","MCY.NZ","GNZ.NZ","ERD.NZ","SKL.NZ",
    ],
    "SG": [
        "D05.SI","O39.SI","U11.SI","Z74.SI","Y92.SI","C6L.SI","S63.SI",
        "G13.SI","BN4.SI","F34.SI","C38U.SI","A17U.SI","N2IU.SI","ME8U.SI",
        "BUOU.SI","K71U.SI","T82U.SI","U96.SI","H78.SI","S58.SI","V03.SI",
        "BS6.SI","CC3.SI","C07.SI","E5H.SI","J36.SI","S68.SI","U14.SI",
    ],
}


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(market: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"tickers_{market}.json")


def _is_stale(path: str) -> bool:
    if not os.path.exists(path):
        return True
    try:
        with open(path) as f:
            data = json.load(f)
        ts = datetime.fromisoformat(data["fetched_at"])
        return datetime.now() - ts > timedelta(days=CACHE_DAYS)
    except Exception:
        return True


def _load_cache(path: str) -> list:
    with open(path) as f:
        return json.load(f)["tickers"]


def _save_cache(path: str, tickers: list):
    with open(path, "w") as f:
        json.dump({"fetched_at": datetime.now().isoformat(), "tickers": tickers}, f)


def _get(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ── US: S&P 500 from Wikipedia ────────────────────────────────────────────────

def _fetch_us(log=None) -> list:
    _log(log, "  US  — fetching S&P 500 from Wikipedia…")
    if not BS4_OK:
        _log(log, "  US  — bs4 missing, using fallback")
        return _FALLBACK["US"]
    try:
        soup = BeautifulSoup(
            _get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"),
            "html.parser",
        )
        table = soup.find("table", {"id": "constituents"})
        tickers = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if cells:
                tickers.append(cells[0].text.strip().replace(".", "-"))
        _log(log, f"  US  — {len(tickers)} tickers")
        return tickers
    except Exception as e:
        _log(log, f"  US  — failed ({e}), using fallback")
        return _FALLBACK["US"]


# ── AU: ASX CSV downloaded by user ────────────────────────────────────────────

def _find_asx_csv() -> str | None:
    """Find the most recent ASX_Listed_Companies_*.csv in the data/ folder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    candidates = [
        f for f in os.listdir(DATA_DIR)
        if f.startswith("ASX_Listed_Companies") and f.endswith(".csv")
    ]
    if not candidates:
        return None
    # Most recent by filename (they include the date)
    candidates.sort(reverse=True)
    return os.path.join(DATA_DIR, candidates[0])


def _fetch_au(log=None) -> list:
    csv_path = _find_asx_csv()

    if csv_path:
        _log(log, f"  AU  — reading {os.path.basename(csv_path)}…")
        try:
            tickers = []
            with open(csv_path, encoding="utf-8-sig") as f:
                lines = f.readlines()
            for line in lines[1:]:          # skip header
                # CSV format: "ASX code","Company name","GICs...","Listing date","Market Cap"
                parts = line.split('","')
                if not parts:
                    continue
                code = parts[0].strip().strip('"').strip()
                # Skip blank, suspended, or clearly non-equity codes
                if not code or len(code) > 5 or not code.replace(" ", "").isalnum():
                    continue
                # Skip if market cap column says SUSPENDED
                if len(parts) >= 5 and "SUSPENDED" in parts[4].upper():
                    continue
                tickers.append(code + ".AX")
            tickers = list(dict.fromkeys(tickers))
            _log(log, f"  AU  — {len(tickers)} tickers from CSV")
            return tickers
        except Exception as e:
            _log(log, f"  AU  — CSV read failed ({e}), trying Wikipedia…")

    else:
        _log(log, f"  AU  — no ASX CSV found in data/ folder")
        _log(log, f"  AU  — download it from: {ASX_CSV_URL}")
        _log(log, f"  AU  — drop the file into the data/ folder, then re-run")
        _log(log, f"  AU  — falling back to Wikipedia ASX 200 for now…")

    # Wikipedia ASX 200 fallback
    if BS4_OK:
        try:
            soup = BeautifulSoup(
                _get("https://en.wikipedia.org/wiki/S%26P/ASX_200"),
                "html.parser",
            )
            tickers = []
            for table in soup.find_all("table", {"class": "wikitable"}):
                headers = [th.text.strip().lower() for th in table.find_all("th")]
                ticker_col = next(
                    (i for i, h in enumerate(headers)
                     if h in ("ticker", "code", "asx code", "asx ticker")),
                    None,
                )
                if ticker_col is None:
                    continue
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all("td")
                    if len(cells) > ticker_col:
                        raw = cells[ticker_col].text.strip().upper()
                        if raw and 2 <= len(raw) <= 5 and raw.isalnum():
                            tickers.append(raw + ".AX")
            tickers = list(dict.fromkeys(tickers))
            if len(tickers) > 10:
                _log(log, f"  AU  — {len(tickers)} tickers from Wikipedia ASX 200")
                return tickers
        except Exception as e:
            _log(log, f"  AU  — Wikipedia failed ({e})")

    _log(log, f"  AU  — using fallback list ({len(_FALLBACK['AU'])} tickers)")
    return _FALLBACK["AU"]


# ── NZ: scrape nzx.com/markets/NZSX ─────────────────────────────────────────

# Patterns that identify non-equity instruments on NZX
_NZX_SKIP_SUFFIXES = ("WA", "WB", "WC", "WH", "WI", "PA", "PB")   # warrants, prefs
_NZX_SKIP_KEYWORDS = ("ETF", "SMART ", "FUND", " BOND", "WARRANT")  # ETFs, funds

def _fetch_nz(log=None) -> list:
    _log(log, "  NZ  — scraping nzx.com…")
    if not BS4_OK:
        _log(log, "  NZ  — bs4 missing, using fallback")
        return _FALLBACK["NZ"]
    try:
        soup = BeautifulSoup(
            _get("https://www.nzx.com/markets/NZSX"),
            "html.parser",
        )
        tickers = []
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            # First cell has the instrument code link
            code_cell = cells[0].text.strip().upper()
            name_cell = cells[1].text.strip().upper() if len(cells) > 1 else ""

            # Skip warrants, preference shares, rights
            if any(code_cell.endswith(s) for s in _NZX_SKIP_SUFFIXES):
                continue
            # Skip ETFs and funds by name
            if any(kw in name_cell for kw in _NZX_SKIP_KEYWORDS):
                continue
            # Code must be 2–5 alpha/numeric chars
            if not code_cell or not (2 <= len(code_cell) <= 5) or not code_cell.isalnum():
                continue

            tickers.append(code_cell + ".NZ")

        tickers = list(dict.fromkeys(tickers))
        if len(tickers) > 10:
            _log(log, f"  NZ  — {len(tickers)} equities (ETFs/warrants excluded)")
            return tickers
        _log(log, "  NZ  — parse returned too few, using fallback")
    except Exception as e:
        _log(log, f"  NZ  — scrape failed ({e}), using fallback")
    return _FALLBACK["NZ"]


# ── SG: scrape stockanalysis.com SGX list ────────────────────────────────────

# SGX has many cross-listed Chinese / HK stocks with codes like H___D or T___D
# yfinance won't have price data for them as .SI — filter them out.
_SGX_SKIP_PATTERN = re.compile(r'^[HT][A-Z]{2}[A-Z0-9]D$')   # e.g. HTCD, HBBD

def _fetch_sg(log=None) -> list:
    _log(log, f"  SG  — scraping stockanalysis.com (top {SGX_TOP_N})…")
    if not BS4_OK:
        _log(log, "  SG  — bs4 missing, using fallback")
        return _FALLBACK["SG"]
    try:
        soup = BeautifulSoup(
            _get("https://stockanalysis.com/list/singapore-exchange/"),
            "html.parser",
        )
        tickers = []
        for row in soup.find_all("tr"):
            if len(tickers) >= SGX_TOP_N:
                break
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            # Column 1 (index 1) is the Symbol
            sym = cells[1].text.strip().upper()
            if not sym or not (2 <= len(sym) <= 6):
                continue
            if _SGX_SKIP_PATTERN.match(sym):
                continue          # cross-listed HK/China stock, skip
            tickers.append(sym + ".SI")

        tickers = list(dict.fromkeys(tickers))
        if len(tickers) > 10:
            _log(log, f"  SG  — {len(tickers)} tickers")
            return tickers
        _log(log, "  SG  — parse returned too few, using fallback")
    except Exception as e:
        _log(log, f"  SG  — scrape failed ({e}), using fallback")
    return _FALLBACK["SG"]


# ── Public API ────────────────────────────────────────────────────────────────

_FETCHERS = {"US": _fetch_us, "AU": _fetch_au, "NZ": _fetch_nz, "SG": _fetch_sg}


def _log(log_fn, msg: str):
    print(msg)
    if log_fn:
        log_fn(msg)


def load_all_tickers(force_refresh: bool = False, log=None) -> dict:
    result = {}
    for market in MARKETS:
        path = _cache_path(market)
        if not force_refresh and not _is_stale(path):
            tickers = _load_cache(path)
            _log(log, f"  {market:<3} — {len(tickers)} tickers (cached)")
        else:
            tickers = _FETCHERS[market](log=log)
            _save_cache(path, tickers)
        result[market] = tickers
    return result


def ticker_count(market_tickers: dict) -> int:
    return sum(len(v) for v in market_tickers.values())