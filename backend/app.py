"""Market Lens — FastAPI backend.

A plain-English stock read for non-traders. Two endpoints do the work:

  GET /api/read?ticker=AAPL&market=US   -> the plain read (verdict + why + action)
  GET /api/strong?market=US             -> a categorised list of strong names

The read is computed on the server from free Yahoo data (no API key), via the
bundled JLaw engine (jlaw_data_core) + the plain-language rules (plain_read).
Educational only — never buy/sell advice.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import jlaw_data_core as J
from backend.plain_read import build_plain_read
from backend.market_scan import strongest_list, momentum_list

HERE = os.path.dirname(__file__)
FRONTEND = os.path.join(HERE, "..", "frontend")

app = FastAPI(title="Market Lens")

# Markets the app actually supports (scan profiles + suffix handling exist for these).
_MARKETS = {"US", "IN", "UK"}
# "Strong right now" list: show ALL names that pass the screen (no small cap), deep-read
# via the same engine so the list tag == the stock-read tag. _DEEP_MAX is only a runaway
# safety ceiling (log if a market's net ever exceeds it); the scan is cached daily and
# uses J.memo_on() so the shared market benchmark is fetched once, not per-name.
_SCAN_LIMIT = 600
_DEEP_MAX = 450

# A small starter universe per market so "Strong right now" works out of the box.
# (The full market-wide scan is the next step; this keeps the screen useful today.)
_STARTERS = {
    "US": ["NVDA", "ASML", "MSFT", "AAPL", "AVGO", "LLY", "AMD", "META", "GOOGL", "NFLX"],
    "IN": ["RELIANCE", "MARKSANS", "LUPIN", "DIXON", "BSE", "TATAMOTORS", "INFY",
           "SUNPHARMA", "TITAN", "TRENT"],
    "UK": ["SHEL", "AZN", "HSBA", "BP", "GLEN", "RIO", "ULVR", "BARC", "LSEG", "TSCO"],
}

# tiny daily cache so repeat hits don't re-fetch: key -> (yyyymmdd, value)
_CACHE: dict[str, tuple] = {}


def _today() -> str:
    return time.strftime("%Y%m%d")


def _cached(key: str):
    hit = _CACHE.get(key)
    return hit[1] if hit and hit[0] == _today() else None


def _put(key: str, value):
    _CACHE[key] = (_today(), value)


def _screen_resolved(ticker: str, market: str | None, light: bool = False) -> dict:
    """Screen a ticker, resolving it correctly. For India/UK, a bare TICKER (single
    token) is screened via its exchange-suffixed symbol FIRST — Yahoo's name search
    for a bare ticker is unreliable (e.g. 'BSE' wrongly matched GROWWPOWER, while
    'BSE.NS' is correct). Falls back to the plain name/ticker resolve otherwise.
    light=True skips the unused weekly bars (list path only)."""
    tk = (ticker or "").strip()
    mk = (market or "").strip().upper()
    suffix = {"IN": ".NS", "UK": ".L"}.get(mk)
    if (suffix and tk and " " not in tk
            and not tk.upper().endswith((".NS", ".BO", ".L"))):
        b = J.screen(tk + suffix, outdir=None, make_charts=False, market=mk, light=light)
        if b.get("features"):                       # direct symbol resolved -> trust it
            return b
    return J.screen(tk, outdir=None, make_charts=False, market=market or None, light=light)


def _news_for(symbol: str) -> dict:
    """Recent-news sentiment for one symbol, daily-cached. Alpha Vantage's free tier is
    tiny (25/day, 5/min), so we fetch at most once per symbol per day and only from the
    single-stock read path — never the many-name list. No key -> {have: False} (the app
    stays fully usable key-free; news factoring just switches off)."""
    key = f"news:{symbol.upper()}"
    hit = _cached(key)
    if hit is not None:
        return hit
    try:
        n = J.news_sentiment(symbol)
    except Exception:  # noqa: BLE001  news is best-effort
        n = {"have": False, "reason": "error"}
    _put(key, n)
    return n


def _read_one(ticker: str, market: str | None, with_chart: bool = True) -> dict:
    """Engine + plain-language read for one ticker. Adds a small price line for the
    chart unless with_chart=False (list items skip it to save a network call).

    News sentiment is fetched ONLY on the single read (with_chart=True); the list path
    passes no news, so its price tag stays identical to the read's price tag."""
    # list path (no chart) skips the weekly fetch — the read ignores it, so the tag is
    # unchanged, but it's one fewer Yahoo request per name across the ~300-name scan.
    bundle = _screen_resolved(ticker, market, light=not with_chart)
    news = None
    if with_chart:
        sym = (bundle.get("resolved") or {}).get("symbol")
        if sym:
            news = _news_for(sym)
    read = build_plain_read(bundle, news=news)
    if with_chart and read.get("ok") and read.get("symbol"):
        try:
            read["chart"] = _chart_payload(read["symbol"], bundle)
        except Exception:  # noqa: BLE001  chart is best-effort
            pass
        _add_period(read)
        try:  # header stats (sector / week / month / P/E / turnover) — best-effort
            from backend.market_scan import snapshot
            mk = (market or "").strip().upper() or _mkt_for(read.get("symbol", ""))
            snap = snapshot(read["symbol"], mk)
            if snap:
                read["stats"] = snap
        except Exception:  # noqa: BLE001
            pass
    return read


def _mkt_for(symbol: str) -> str:
    s = str(symbol).upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "IN"
    if s.endswith(".L"):
        return "UK"
    return "US"


def _add_period(read: dict) -> None:
    """Rough 'typically ~N weeks to reach the target', from the stock's own daily
    volatility: a move of size m takes about (m / daily_move)^2 trading days. Very
    approximate (paths are random) — best-effort, skipped for weak names / no target."""
    try:
        import numpy as np
        closes = (read.get("chart") or {}).get("closes")
        tag = (read.get("verdict") or {}).get("tag")
        entry = read.get("price")     # time-to-target is measured from where it is now
        target = (read.get("lines") or {}).get("swing_high")
        if not (closes and len(closes) > 30 and tag not in ("weak", "avoid")
                and entry and target and target > entry * 1.01):
            return
        rets = np.diff(np.log(closes))
        dvol = float(np.std(rets))
        if dvol <= 0:
            return
        move = (target - entry) / entry
        weeks = max(1, round(((move / dvol) ** 2) / 5))       # ~5 trading days / week
        read.setdefault("detail", {})["period"] = {
            "weeks": weeks,
            "text": f"typically ~{weeks} week{'s' if weeks != 1 else ''} to reach the target "
                    f"(very rough — actual timing varies a lot)"}
    except Exception:  # noqa: BLE001
        pass


def _chart_payload(symbol: str, bundle: dict) -> dict:
    """Price + 20/50/200-day moving averages + a relative-strength line (stock vs its
    benchmark, rebased to 100) — the advanced overlays. 15mo of history so the 200-day
    average is complete over the ~130 bars shown."""
    import pandas as pd
    df = J.get_ohlcv(symbol, rng="15mo")
    close = df["close"]
    ma20, ma50, ma200 = (close.rolling(w).mean() for w in (20, 50, 200))

    rs = None
    bench = (bundle.get("resolved") or {}).get("benchmark")
    if bench:
        try:
            bclose = J.get_ohlcv(bench, rng="15mo")["close"].reindex(df.index).ffill()
            rs = close / bclose
        except Exception:  # noqa: BLE001
            rs = None

    tail = df.tail(130)
    idx = tail.index

    def arr(s):
        s = s.reindex(idx)
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    chart = {
        "dates": [d.strftime("%Y-%m-%d") for d in idx],
        "closes": [round(float(c), 2) for c in tail["close"]],
        "ma20": arr(ma20), "ma50": arr(ma50), "ma200": arr(ma200),
    }
    if rs is not None:
        rt = rs.reindex(idx)
        base = next((float(v) for v in rt if not pd.isna(v)), None)
        if base:
            chart["rs"] = [None if pd.isna(v) else round(float(v) / base * 100, 2) for v in rt]

    # Probability cone — the stock's OWN daily volatility projected forward as ±1σ / ±2σ
    # bands (widening as √time). It's a DISTRIBUTION OF NORMAL OUTCOMES, not a forecast of
    # direction: no drift, centred on today's price. Honest framing enforced in the UI.
    try:
        import numpy as np
        c_arr = tail["close"].to_numpy(dtype=float)
        rets = np.diff(np.log(c_arr))[-60:]        # ~3 months of daily moves = recent "normal"
        dvol = float(np.std(rets))
        last = float(c_arr[-1])
        if dvol > 0 and last > 0 and len(rets) >= 20:
            H = 30                                  # horizon ≈ 6 trading weeks
            fdates = pd.bdate_range(start=idx[-1] + pd.Timedelta(days=1), periods=H)
            up1, lo1, up2, lo2 = [], [], [], []
            for t in range(1, H + 1):
                s = dvol * (t ** 0.5)
                up1.append(round(last * float(np.exp(s)), 2))
                lo1.append(round(last * float(np.exp(-s)), 2))
                up2.append(round(last * float(np.exp(2 * s)), 2))
                lo2.append(round(last * float(np.exp(-2 * s)), 2))
            sH = dvol * (H ** 0.5)
            chart["cone"] = {
                "dates": [d.strftime("%Y-%m-%d") for d in fdates],
                "up1": up1, "lo1": lo1, "up2": up2, "lo2": lo2, "weeks": round(H / 5),
                "b1_lo": round(last * float(np.exp(-sH))), "b1_hi": round(last * float(np.exp(sH))),
                "b2_lo": round(last * float(np.exp(-2 * sH))), "b2_hi": round(last * float(np.exp(2 * sH))),
                "pct1": round((float(np.exp(sH)) - 1) * 100),
            }
    except Exception:  # noqa: BLE001  cone is best-effort
        pass
    return chart


@app.get("/api/health")
def health():
    return {"ok": True, "service": "market-lens"}


@app.get("/api/_diag")
def _diag(symbol: str = "NVDA"):
    """TEMP diagnostic: confirms the news key reached the process and shows the exact
    reason news_sentiment returns (no secrets leaked — only a bool + reason)."""
    import os as _os
    key = _os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    out = {"av_key_present": bool(key), "av_key_len": len(key)}
    try:
        out["news"] = J.news_sentiment(symbol)
    except Exception as e:  # noqa: BLE001
        out["news"] = {"have": False, "reason": "exception", "detail": str(e)}
    return out


@app.get("/api/read")
def read(ticker: str, market: str = ""):
    ticker = (ticker or "").strip()
    if not ticker:
        return JSONResponse({"ok": False, "error": "Type a stock first."})
    mk = market.strip().upper()
    key = f"read:{ticker.upper()}:{mk}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        out = _read_one(ticker, mk if mk in _MARKETS else None)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False,
                             "error": "Couldn't read that stock. Check the ticker and your "
                                      "internet, then try again.",
                             "detail": str(e)})
    _put(key, out)
    return out


def _mom_item(d: dict) -> dict:
    return {"ticker": d["ticker"], "name": d["name"], "market": d["market"],
            "price_str": d["price_str"], "sector": d["sector"],
            "industry": d.get("industry") or "", "raw_sector": d.get("raw_sector") or "",
            "lanes": d["lanes"], "why": d["why"], "n_lanes": d["n_lanes"],
            "perf_w": d.get("perf_w"), "perf_m": d.get("perf_m")}


def _momentum_cached(mk: str) -> list:
    """The raw momentum screen for a market, cached daily (one ~15s TradingView pass,
    no per-name deep read)."""
    key = f"mom:{mk}"
    hit = _cached(key)
    if hit is not None:
        return hit
    lst = momentum_list(mk)
    _put(key, lst)
    return lst


@app.get("/api/strong")
def strong(market: str = "US", n: int = 0):
    """The 'Strong right now' MOMENTUM SCREENER — where money is flowing now (fresh
    movers + quiet leaders at new highs). Grouped by friendly sector; NO buy/wait
    judgment here (that happens when a stock is opened, via the JLaw read). n>0 = a
    light preview (top n names) for the home teaser; n=0 = the full grouped list."""
    mk = market.strip().upper()
    if mk not in _STARTERS:
        mk = "US"
    lst = _momentum_cached(mk)
    if not lst:
        return {"ok": True, "market": mk, "scanned": False, "count": 0,
                "sectors": [], "top": [],
                "note": "Couldn't reach the market scanner just now — try again shortly."}

    # n>0 = light teaser (top n); full list = ALL names (uncapped), ranked strongest-first.
    top = [_mom_item(d) for d in (lst[:n] if n and n > 0 else lst)]
    note = f"{len(lst)} names with fresh momentum right now — where money is flowing."
    if n and n > 0:                                   # teaser: light payload, no grouping
        return {"ok": True, "market": mk, "scanned": True, "count": len(lst),
                "top": top, "note": note}

    groups: dict[str, list] = {}
    for d in lst:
        groups.setdefault(d["sector"], []).append(_mom_item(d))
    sectors = [{"name": s, "count": len(v), "items": v} for s, v in groups.items()]
    sectors.sort(key=lambda x: x["count"], reverse=True)   # biggest money-flow first
    return {"ok": True, "market": mk, "scanned": True, "count": len(lst),
            "top": top, "sectors": sectors, "note": note}


# serve the UI (mounted last so /api/* wins). The single-page app is served with
# no-cache so a browser always gets the latest HTML/JS after a change — otherwise a
# stale cached page runs old code against the new API (empty list, wrong labels).
_NOCACHE = {"Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0"}

if os.path.isdir(FRONTEND):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND, "index.html"), headers=_NOCACHE)

    app.mount("/", StaticFiles(directory=FRONTEND), name="static")
