"""
clear_cache.py
──────────────
Run this once after updating ticker_loader.py to wipe stale ticker lists.
Price data (momentum.db) is preserved — only the ticker JSON files are cleared.

Usage:
    python clear_cache.py          # clears US and MY caches (the changed ones)
    python clear_cache.py --all    # clears all market ticker caches
"""

import os
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

if "--all" in sys.argv:
    markets = ["US", "AU", "NZ", "SG", "MY"]
else:
    markets = ["US", "MY"]    # default: the two new/changed markets

for market in markets:
    path = os.path.join(DATA_DIR, f"tickers_{market}.json")
    if os.path.exists(path):
        os.remove(path)
        print(f"  ✓  Deleted {path}")
    else:
        print(f"  –  {path} not found (already clean)")

print("\nDone. Run main.py to re-fetch.")