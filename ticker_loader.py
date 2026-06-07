"""
ticker_loader.py
────────────────
Loads and caches ticker lists for all five markets.

  US  — NASDAQ screener CSV (local) + NYSE from GitHub CSV
  AU  — ASX listed companies CSV (downloaded by user from ASX website)
  NZ  — NZSX scraped live from nzx.com
  SG  — Full SGX list scraped from stockanalysis.com
  MY  — Bursa Malaysia (KLSE) parsed from official PDF in data/ folder

Each market list is cached in data/tickers_<market>.json.
Re-fetched automatically if cache is older than CACHE_DAYS days.

Returns { "US": [...], "AU": [...], "NZ": [...], "SG": [...], "MY": [...] }
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

try:
    import pdfplumber
    PDFPLUMBER_OK = True
except ImportError:
    PDFPLUMBER_OK = False

# ── Config ────────────────────────────────────────────────────────────────────

_BASE      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(_BASE, "data")
CACHE_DAYS = 7

MARKETS = ["US", "AU", "NZ", "SG", "MY"]

# NYSE CSV from GitHub (datasets org — updated regularly)
NYSE_CSV_URL = "https://raw.githubusercontent.com/datasets/nyse-other-listings/main/data/nyse-listed.csv"

# AU CSV — user downloads from ASX and drops in the data/ folder.
ASX_CSV_URL = "https://www.asx.com.au/markets/trade-our-cash-market/directory"

# NASDAQ CSV — user downloads from nasdaq.com/market-activity/stocks/screener
# Filename pattern: nasdaq_screener_*.csv


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
    "MY": [
        "1155.KL","1295.KL","5347.KL","6888.KL","5285.KL","1023.KL",
        "5183.KL","4197.KL","3816.KL","5211.KL","5225.KL","1961.KL",
        "5681.KL","6033.KL","2445.KL","3182.KL","4715.KL","1818.KL",
        "5398.KL","6012.KL","5263.KL","4863.KL","5031.KL","5248.KL",
        "5296.KL","7113.KL","5168.KL","3689.KL","4707.KL","1066.KL",
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


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ── US: NASDAQ CSV (local) + NYSE CSV (GitHub) ────────────────────────────────

def _find_nasdaq_csv() -> str | None:
    os.makedirs(DATA_DIR, exist_ok=True)
    candidates = [
        f for f in os.listdir(DATA_DIR)
        if f.startswith("nasdaq_screener_") and f.endswith(".csv")
    ]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return os.path.join(DATA_DIR, candidates[0])


def _parse_nasdaq_csv(path: str, log=None) -> list:
    tickers = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.readlines()
        # Header: Symbol,Name,Last Sale,Net Change,...
        for line in lines[1:]:
            parts = line.split(",")
            if not parts:
                continue
            sym = parts[0].strip().strip('"').strip()
            if sym and sym != "Symbol":
                tickers.append(sym)
        _log(log, f"  US  — {len(tickers)} tickers from NASDAQ CSV")
    except Exception as e:
        _log(log, f"  US  — NASDAQ CSV read failed ({e})")
    return tickers


def _fetch_nyse_csv(log=None) -> list:
    tickers = []
    try:
        content = _get(NYSE_CSV_URL).decode("utf-8")
        lines = content.splitlines()
        # Header: ACT Symbol,Company Name,Exchange,CIK,...
        for line in lines[1:]:
            parts = line.split(",")
            if not parts:
                continue
            sym = parts[0].strip().strip('"').strip()
            if sym and sym != "ACT Symbol":
                tickers.append(sym)
        _log(log, f"  US  — {len(tickers)} tickers from NYSE CSV")
    except Exception as e:
        _log(log, f"  US  — NYSE CSV fetch failed ({e})")
    return tickers


def _fetch_us(log=None) -> list:
    nasdaq_path = _find_nasdaq_csv()
    nasdaq_tickers = []
    nyse_tickers = []

    if nasdaq_path:
        _log(log, f"  US  — reading {os.path.basename(nasdaq_path)}…")
        nasdaq_tickers = _parse_nasdaq_csv(nasdaq_path, log)
    else:
        _log(log, "  US  — no nasdaq_screener_*.csv found in data/ folder")
        _log(log, "  US  — download from: https://www.nasdaq.com/market-activity/stocks/screener")
        _log(log, "  US  — drop the file into the data/ folder, then re-run")

    _log(log, "  US  — fetching NYSE list from GitHub…")
    nyse_tickers = _fetch_nyse_csv(log)

    combined = list(dict.fromkeys(nasdaq_tickers + nyse_tickers))

    if combined:
        _log(log, f"  US  — {len(combined)} tickers total (NASDAQ + NYSE, deduped)")
        return combined

    _log(log, f"  US  — no sources available, using fallback ({len(_FALLBACK['US'])} tickers)")
    return _FALLBACK["US"]


# ── AU: ASX CSV downloaded by user ────────────────────────────────────────────

def _find_asx_csv() -> str | None:
    os.makedirs(DATA_DIR, exist_ok=True)
    candidates = [
        f for f in os.listdir(DATA_DIR)
        if f.startswith("ASX_Listed_Companies") and f.endswith(".csv")
    ]
    if not candidates:
        return None
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
            for line in lines[1:]:
                parts = line.split('","')
                if not parts:
                    continue
                code = parts[0].strip().strip('"').strip()
                if not code or len(code) > 5 or not code.replace(" ", "").isalnum():
                    continue
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
        _log(log, f"  AU  — download from: {ASX_CSV_URL}")
        _log(log, f"  AU  — falling back to Wikipedia ASX 200…")

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
            code_cell = cells[0].text.strip().upper()
            if not code_cell or not (2 <= len(code_cell) <= 5) or not code_cell.isalnum():
                continue
            tickers.append(code_cell + ".NZ")

        tickers = list(dict.fromkeys(tickers))
        if len(tickers) > 10:
            _log(log, f"  NZ  — {len(tickers)} tickers")
            return tickers
        _log(log, "  NZ  — parse returned too few, using fallback")
    except Exception as e:
        _log(log, f"  NZ  — scrape failed ({e}), using fallback")
    return _FALLBACK["NZ"]


# ── SG: scrape stockanalysis.com SGX — full list ─────────────────────────────

_SGX_SKIP_PATTERN = re.compile(r'^[HT][A-Z]{2}[A-Z0-9]D$')

def _fetch_sg(log=None) -> list:
    _log(log, "  SG  — scraping stockanalysis.com (full list)…")
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
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            sym = cells[1].text.strip().upper()
            if not sym or not (2 <= len(sym) <= 6):
                continue
            if _SGX_SKIP_PATTERN.match(sym):
                continue
            tickers.append(sym + ".SI")

        tickers = list(dict.fromkeys(tickers))
        if len(tickers) > 10:
            _log(log, f"  SG  — {len(tickers)} tickers")
            return tickers
        _log(log, "  SG  — parse returned too few, using fallback")
    except Exception as e:
        _log(log, f"  SG  — scrape failed ({e}), using fallback")
    return _FALLBACK["SG"]


# ── MY: Bursa Malaysia PDF in data/ folder ───────────────────────────────────

def _find_klse_pdf() -> str | None:
    os.makedirs(DATA_DIR, exist_ok=True)
    candidates = [
        f for f in os.listdir(DATA_DIR)
        if f.lower().endswith(".pdf") and any(
            kw in f.upper() for kw in ("KLSE", "BURSA", "KLCI", "MALAYSIA")
        )
    ]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return os.path.join(DATA_DIR, candidates[0])


def _fetch_my(log=None) -> list:
    pdf_path = _find_klse_pdf()

    if pdf_path and PDFPLUMBER_OK:
        _log(log, f"  MY  — reading {os.path.basename(pdf_path)}…")
        try:
            tickers = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages[1:]:  # skip cover page
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if not row or len(row) < 3:
                                continue
                            code = row[2]
                            if not code or code in ("STOCK CODE", None):
                                continue
                            code = code.strip()
                            if code:
                                tickers.append(code + ".KL")
            tickers = list(dict.fromkeys(tickers))
            _log(log, f"  MY  — {len(tickers)} tickers from Bursa PDF")
            return tickers
        except Exception as e:
            _log(log, f"  MY  — PDF read failed ({e}), trying stockanalysis.com…")
    elif not pdf_path:
        _log(log, "  MY  — no Bursa Malaysia PDF found in data/ folder")
        _log(log, "  MY  — download from: https://www.bursamalaysia.com/market_information/listed_companies/list_of_companies")
        _log(log, "  MY  — drop the PDF into the data/ folder (name it e.g. KLSE_List_of_Companies.pdf), then re-run")
        _log(log, "  MY  — falling back to stockanalysis.com…")
    elif not PDFPLUMBER_OK:
        _log(log, "  MY  — pdfplumber not installed (pip install pdfplumber), falling back…")

    # Web fallback — stockanalysis.com Malaysia list
    if BS4_OK:
        try:
            _log(log, "  MY  — scraping stockanalysis.com Malaysia list…")
            soup = BeautifulSoup(
                _get("https://stockanalysis.com/list/bursa-malaysia/"),
                "html.parser",
            )
            tickers = []
            for row in soup.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                sym = cells[1].text.strip()
                if not sym:
                    continue
                # Symbols on this page already include .KL
                if not sym.endswith(".KL"):
                    sym = sym + ".KL"
                tickers.append(sym)
            tickers = list(dict.fromkeys(tickers))
            if len(tickers) > 10:
                _log(log, f"  MY  — {len(tickers)} tickers from stockanalysis.com")
                return tickers
        except Exception as e:
            _log(log, f"  MY  — stockanalysis.com failed ({e})")

    _log(log, f"  MY  — using fallback list ({len(_FALLBACK['MY'])} tickers)")
    return _FALLBACK["MY"]


# ── Public API ────────────────────────────────────────────────────────────────

_FETCHERS = {
    "US": _fetch_us,
    "AU": _fetch_au,
    "NZ": _fetch_nz,
    "SG": _fetch_sg,
    "MY": _fetch_my,
}


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