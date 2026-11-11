"""Check a live feed from THIS machine:  python scripts/check_nasdaq.py [SYMBOL ...] [--yahoo]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from meridian.data.providers import NasdaqProvider, ProviderError, YahooProvider  # noqa: E402

symbols = sys.argv[1:] or ["AAPL", "NVDA", "MSFT"]
which = "yahoo" if "--yahoo" in sys.argv else "nasdaq"
symbols = [x for x in symbols if not x.startswith("--")] or ["AAPL", "NVDA", "MSFT"]
try:
    p = YahooProvider() if which == "yahoo" else NasdaqProvider(timeout_s=10)
except ProviderError as e:
    sys.exit(f"{e}")
print(f"Checking live source: {which}")
ok = True
for s in symbols:
    for name, fn in (("quote", lambda s=s: p.quote(s)), ("history", lambda s=s: p.history(s, 60)), ("fundamentals", lambda s=s: p.fundamentals(s))):
        try:
            r = fn()
            if name == "quote":
                info = f"price {r['price']}  ({r['change_pct']}%)  as of {r['provenance'].get('as_of')}"
            elif name == "history":
                info = f"{len(r['candles'])} candles, last {r['candles'][-1]['date']} close {r['candles'][-1]['close']}"
            else:
                info = ", ".join(f"{k}={v}" for k, v in list(r.items())[:4])
            print(f"OK    {s:5} {name:12} {info}")
        except Exception as e:
            ok = False
            print(f"FAIL  {s:5} {name:12} {e}")
print("\nLIVE Nasdaq feed works." if ok else "\nSome calls failed. The app still runs: MERIDIAN_PROVIDER=auto falls back to labelled simulated data.")
sys.exit(0 if ok else 1)
