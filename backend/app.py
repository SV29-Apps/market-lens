"""Market Lens — FastAPI backend.

A plain-English stock read for non-traders. Two endpoints do the work:

  GET /api/read?ticker=AAPL&market=US   -> the plain read (verdict + why + action)
  GET /api/strong?market=US             -> a categorised list of strong names

The read is computed on the server from free Yahoo data (no API key), via the
bundled JLaw engine (jlaw_data_core) + the plain-language rules (plain_read).
Educational only — never buy/sell advice.
"""

from __future__ import annotations

import base64
import os
import secrets
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import jlaw_data_core as J
from backend.plain_read import build_plain_read
from backend.market_scan import strongest_list, momentum_list

HERE = os.path.dirname(__file__)
FRONTEND = os.path.join(HERE, "..", "frontend")

app = FastAPI(title="Market Lens")


@app.middleware("http")
async def _basic_auth(request: Request, call_next):
    """Optional site-wide login gate (HTTP Basic Auth).

    When BOTH ``APP_USERNAME`` and ``APP_PASSWORD`` are set in the environment, every
    request except the health check must carry matching credentials — otherwise the
    browser is challenged with a username/password popup. When either var is unset
    (e.g. local dev) the site is fully open. To CHANGE the credentials at any time,
    edit those two env vars on the host (Render dashboard) and redeploy; users are then
    re-prompted. Served only over HTTPS on Render, so credentials are encrypted in
    transit. ``compare_digest`` avoids timing-based guessing."""
    user = os.environ.get("APP_USERNAME", "").strip()
    pw = os.environ.get("APP_PASSWORD", "").strip()
    if user and pw and request.url.path != "/api/health":
        ok = False
        hdr = request.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                raw = base64.b64decode(hdr[6:]).decode("utf-8")
                u, _, p = raw.partition(":")
                ok = (secrets.compare_digest(u, user)
                      and secrets.compare_digest(p, pw))
            except Exception:  # noqa: BLE001  malformed header -> re-challenge
                ok = False
        if not ok:
            return Response(status_code=401, content="Authentication required.",
                            headers={"WWW-Authenticate": 'Basic realm="Market Lens"'})
    return await call_next(request)

# Markets the app supports (scan profiles + suffix handling exist for these).
_MARKETS = {"US", "IN", "UK"}
# Markets currently SHOWN to users. UK is built and working but hidden for now
# (TradingView pence-vs-pounds display needs a proper pass before it goes public).
# To re-enable: set ENABLED_MARKETS=US,IN,UK on the host (Render env var) — no code change.
_ENABLED = [m.strip() for m in os.environ.get("ENABLED_MARKETS", "US,IN").upper().split(",")
            if m.strip() in _MARKETS] or ["US"]

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
_MOM_LOCK = threading.Lock()      # single-flight for the ~15s momentum scan


def _today() -> str:
    return time.strftime("%Y%m%d")


def _cached(key: str):
    hit = _CACHE.get(key)
    return hit[1] if hit and hit[0] == _today() else None


def _put(key: str, value):
    """Store, and keep the cache bounded: stale-day entries are evicted so the dict
    can't grow forever across days (each read payload carries ~130-bar chart arrays)."""
    today = _today()
    if len(_CACHE) > 1500:
        for k in [k for k, (d, _) in _CACHE.items() if d != today]:
            _CACHE.pop(k, None)
    _CACHE[key] = (today, value)


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


def _about_for(name: str) -> str | None:
    """1-2 plain lines about the company (Wikipedia summary, best-effort, daily-cached).
    Guards against wrong-page hits: the found title must contain the company name's
    first word AND the text must read like a business description. None -> the read
    simply shows no 'about' line (same graceful-absence pattern as the News check)."""
    nm = (name or "").strip()
    if not nm:
        return None
    key = f"about:{nm.lower()}"
    hit = _cached(key)
    if hit is not None:
        return hit or None            # cached "" = known miss; don't refetch today
    out = ""
    try:
        import json as _json
        import ssl
        import urllib.parse
        import urllib.request
        try:  # Windows Python often lacks a wired CA store for urllib; Render is fine
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001
            ctx = None

        def get(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
                return _json.load(r)

        s = get("https://en.wikipedia.org/w/rest.php/v1/search/title?q="
                + urllib.parse.quote(nm) + "&limit=1")
        pages = s.get("pages") or []
        first = next((w for w in nm.split() if len(w) > 2 and w.lower() != "the"),
                     nm.split()[0])
        if pages and first.lower() in (pages[0].get("title") or "").lower():
            j = get("https://en.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(pages[0]["key"]))
            ext = (j.get("extract") or "").replace("\n", " ").strip()
            low = ext.lower()
            biz = any(w in low for w in ("compan", "corporation", "manufactur", "subsidiary",
                                         "bank", "conglomerate", "retailer", "producer",
                                         "group", "firm", "brand", "insurer", "operator"))
            if ext and biz:
                out = ". ".join(ext.split(". ")[:2]).strip()
                if not out.endswith("."):
                    out += "."
                if len(out) > 260:
                    out = out[:257].rsplit(" ", 1)[0] + "…"
    except Exception:  # noqa: BLE001  about is best-effort
        out = ""
    _put(key, out)
    return out or None


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
        try:  # 1-2 lines about the business — best-effort
            ab = _about_for(read.get("name") or "")
            if ab:
                read["about"] = ab
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
        target = (read.get("lines") or {}).get("target")   # the read's effective target
        # target must be REAL by the same rule the "Where it could go" box uses
        # (> 2% above price) — otherwise the page says "near its high, no target"
        # while this line promises "~1 week to reach the target".
        if not (closes and len(closes) > 30 and tag not in ("weak", "avoid")
                and entry and target and target > entry * 1.02):
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
async def health():
    # async def on purpose: it never touches the threadpool, so the platform health
    # check still answers even if slow upstream reads have every worker thread busy.
    return {"ok": True, "service": "market-lens"}


@app.get("/api/config")
async def config():
    """What the frontend should show — currently just the enabled market pills."""
    return {"ok": True, "markets": _ENABLED}


@app.get("/api/read")
def read(ticker: str, market: str = ""):
    ticker = (ticker or "").strip()
    if not ticker:
        return JSONResponse({"ok": False, "error": "Type a stock first."})
    mk = market.strip().upper()
    mk = mk if mk in _MARKETS else ""          # validate BEFORE it becomes a cache key
    key = f"read:{ticker.upper()}:{mk}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        out = _read_one(ticker, mk or None)
    except Exception as e:  # noqa: BLE001
        print(f"[read] {ticker} failed: {e}", flush=True)   # server log, not the client
        return JSONResponse({"ok": False,
                             "error": "Couldn't read that stock. Check the ticker and your "
                                      "internet, then try again."})
    if out.get("ok"):        # never day-cache a failure — a throttled lookup would make a
        _put(key, out)       # valid ticker "unreadable" for every user until midnight
    return out


def _mom_item(d: dict) -> dict:
    return {"ticker": d["ticker"], "name": d["name"], "market": d["market"],
            "price_str": d["price_str"], "sector": d["sector"],
            "industry": d.get("industry") or "", "raw_sector": d.get("raw_sector") or "",
            "lanes": d["lanes"], "why": d["why"], "n_lanes": d["n_lanes"],
            "perf_w": d.get("perf_w"), "perf_m": d.get("perf_m"),
            "rvol": d.get("rvol"), "ready": d.get("ready"), "dip_q": d.get("dip_q")}


def _momentum_cached(mk: str) -> list:
    """The raw momentum screen for a market, cached daily (one ~15s TradingView pass,
    no per-name deep read). Single-flight: concurrent cold hits wait on one scan instead
    of each launching their own (a burst of identical queries invites throttling).
    A FAILED scan ([]) is never cached — otherwise one hiccup at the day's first request
    would freeze an empty screener until midnight while the UI says 'try again'."""
    key = f"mom:{mk}"
    hit = _cached(key)
    if hit is not None:
        return hit
    with _MOM_LOCK:
        hit = _cached(key)               # another thread may have filled it while we waited
        if hit is not None:
            return hit
        lst = momentum_list(mk)
        if lst:
            _put(key, lst)
        else:
            print(f"[scan] momentum_list({mk}) returned empty — NOT cached", flush=True)
        return lst


def _regime_cached(mk: str) -> str | None:
    """The market's Risk-On/Neutral/Risk-Off read for the strip, daily-cached.
    Shown to the user only as plain words (healthy / so-so / weak)."""
    key = f"regime:{mk}"
    hit = _cached(key)
    if hit is not None:
        return hit or None
    bench = {"US": "^GSPC", "IN": "^NSEI", "UK": "^FTSE"}.get(mk)
    reg = ""
    try:
        bm = J.broad_market(bench) if bench else {}
        reg = bm.get("regime") or ""
    except Exception:  # noqa: BLE001  strip is best-effort
        reg = ""
    _put(key, reg)
    return reg or None


@app.get("/api/strong")
def strong(market: str = "US", n: int = 0):
    """The 'Strong right now' MOMENTUM SCREENER — where money is flowing now (fresh
    movers + quiet leaders at new highs). Grouped by friendly sector; NO buy/wait
    judgment here (that happens when a stock is opened, via the JLaw read). n>0 = a
    light preview (top n names) for the home teaser; n=0 = the full grouped list."""
    mk = market.strip().upper()
    if mk not in _ENABLED:
        mk = _ENABLED[0]
    lst = _momentum_cached(mk)
    regime = _regime_cached(mk)
    if not lst:
        return {"ok": True, "market": mk, "scanned": False, "count": 0,
                "sectors": [], "top": [], "regime": regime,
                "note": "Couldn't reach the market scanner just now — try again shortly."}

    # n>0 = light teaser (top n); full list = ALL names (uncapped), ranked strongest-first.
    top = [_mom_item(d) for d in (lst[:n] if n and n > 0 else lst)]
    note = f"{len(lst)} names with fresh momentum right now — where money is flowing."
    if n and n > 0:                                   # teaser: light payload, no grouping
        return {"ok": True, "market": mk, "scanned": True, "count": len(lst),
                "top": top, "note": note, "regime": regime}

    return {"ok": True, "market": mk, "scanned": True, "count": len(lst),
            "top": top, "note": note, "regime": regime}


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
