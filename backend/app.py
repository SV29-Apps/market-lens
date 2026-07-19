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
from backend import kite_live
from backend.plain_read import build_plain_read, _money
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
    try:
        return J.screen(tk, outdir=None, make_charts=False, market=market or None, light=light)
    except Exception:
        # An explicitly requested BSE symbol whose Yahoo tape is a stub (LICI.BO = ONE
        # row, 2026-07-19): the same company lists on NSE — read that instead of
        # dead-ending, since the user means the company, not the exchange.
        if tk.upper().endswith(".BO"):
            b = J.screen(tk[:-3] + ".NS", outdir=None, make_charts=False,
                         market=mk or "IN", light=light)
            if b.get("features"):
                return b
        raise


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


def _kite_overlay(bundle: dict) -> dict | None:
    """Live Kite freshness for an INDIAN read (optional — see kite_live.py). Adjusts
    the bundle's volume ratio to 'vs the normal pace for this time of day' (the honest
    version of the quiet/heavy check) and returns {price, pct_1d} for the header.
    None whenever Kite is unavailable — the read is then byte-identical to the free
    route, which is also the permanent state on Render."""
    try:
        f = bundle.get("features") or {}
        sym = (bundle.get("resolved") or {}).get("symbol", "")
        base = sym.split(".")[0]
        if not base or not kite_live.available():
            return None
        q = kite_live.quotes([base]).get(base)
        if not q:
            return None
        vol = (f.get("daily") or {}).get("volume") or {}
        if vol.get("avg50") and q.get("volume"):
            frac = kite_live.session_fraction()
            vol["ratio_vs_avg50"] = round(q["volume"] / (vol["avg50"] * frac), 2)
            vol["live_adjusted"] = True
        return {"price": q["price"], "pct_1d": q["pct_1d"]}
    except Exception:  # noqa: BLE001  live layer is best-effort, always
        return None


def _read_one(ticker: str, market: str | None, with_chart: bool = True) -> dict:
    """Engine + plain-language read for one ticker. Adds a small price line for the
    chart unless with_chart=False (list items skip it to save a network call).

    News sentiment is fetched ONLY on the single read (with_chart=True); the list path
    passes no news, so its price tag stays identical to the read's price tag."""
    # list path (no chart) skips the weekly fetch — the read ignores it, so the tag is
    # unchanged, but it's one fewer Yahoo request per name across the ~300-name scan.
    bundle = _screen_resolved(ticker, market, light=not with_chart)
    live = None
    if (market or "").strip().upper() == "IN":
        live = _kite_overlay(bundle)
    news = None
    if with_chart:
        sym = (bundle.get("resolved") or {}).get("symbol")
        if sym:
            news = _news_for(sym)
    read = build_plain_read(bundle, news=news)
    if read.get("ok"):
        # honest freshness stamp (audit H1): never present a price as "now" unlabelled.
        fr = read.get("freshness") or {}
        if fr.get("as_of"):
            read["as_of_str"] = f"as of {fr['as_of']} (historical)"
        elif live:                       # Kite live overlay (IN) — a true real-time price
            read["as_of_str"] = "live price"
        elif fr.get("intraday"):
            read["as_of_str"] = "live — updates through the trading day"
        elif fr.get("bar_date"):
            read["as_of_str"] = f"at the {fr['bar_date']} close"
    if read.get("ok") and live:
        read["live"] = {"price_str": _money(live["price"], read.get("currency")),
                        "pct_1d": round(live["pct_1d"], 1)}
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
                try:   # group-health check line — show-only, never touches the verdict
                    _group_check(read, snap, mk)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        try:  # 1-2 lines about the business — best-effort. NOT for Indian stocks
            # (user call, 2026-07-19): Wikipedia lookups on short Indian names are
            # unreliable — "Bhel" returned the street-food disambiguation page.
            if (market or "").strip().upper() != "IN":
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
        dvol = float(np.std(rets, ddof=1))                    # sample stdev (audit L14)
        if dvol <= 0:
            return
        # LOG move to match the log-return vol (audit M8: mixing a simple % move with a
        # log-return sigma over-stated the horizon by ~30%). (move/dvol)^2 is the number of
        # DAYS at which this move is a ~1-sigma event — NOT a promise the target is reached
        # (for a driftless walk the median time-to-target is unbounded). Word it honestly.
        move = np.log(target / entry)
        weeks = max(1, round(((move / dvol) ** 2) / 5))       # ~5 trading days / week
        read.setdefault("detail", {})["period"] = {
            "weeks": weeks,
            "text": f"a move this size is roughly a normal ~{weeks}-week swing for it "
                    f"(rough — this is not a prediction that it will get there)"}
    except Exception:  # noqa: BLE001
        pass


def _chart_payload(symbol: str, bundle: dict) -> dict:
    """Price + 20/50/200-day moving averages + a relative-strength line (stock vs its
    benchmark, rebased to 100) — the advanced overlays. 15mo of history so the 200-day
    average is complete over the ~130 bars shown."""
    import pandas as pd
    # REUSE the frames the read already fetched (2026-07-19): the chart used to make
    # two MORE Yahoo calls for the same history, so under a throttle wave the chart
    # died while the read lived — chartless pages. Now the chart can only fail if the
    # read itself failed. (Fallback fetch kept for safety.)
    fr = (bundle.get("features") or {}).get("_frames") or {}
    df = fr.get("daily")
    if df is None or len(df) < 60:
        df = J.get_ohlcv(symbol, rng="15mo")
    close = df["close"]
    ma20, ma50, ma200 = (close.rolling(w).mean() for w in (20, 50, 200))

    rs = None
    bench = (bundle.get("resolved") or {}).get("benchmark")
    if bench:
        try:
            bdf = fr.get("index")
            bclose = (bdf["close"] if bdf is not None
                      else J.get_ohlcv(bench, rng="15mo")["close"]).reindex(df.index).ffill()
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
    # `build` = the running commit (Render injects RENDER_GIT_COMMIT) — health is the
    # only unauthenticated surface, so this is how a deploy is verified from outside
    # (2026-07-19: three pushes were live-verified only by health 200, which can't
    # tell builds apart — a stalled deploy was invisible).
    return {"ok": True, "service": "market-lens",
            "build": (os.environ.get("RENDER_GIT_COMMIT") or "local")[:8]}


@app.get("/api/config")
async def config():
    """What the frontend should show — currently just the enabled market pills."""
    return {"ok": True, "markets": _ENABLED}


# Yahoo exchange code -> (market pill, friendly label) for the search suggestions.
# Only exchanges belonging to markets this app can actually read are listed —
# suggesting a Frankfurt listing the read engine has no benchmark for is a dead end.
_EXCH_UI = {
    "NMS": ("US", "NASDAQ"), "NGM": ("US", "NASDAQ"), "NCM": ("US", "NASDAQ"),
    "NYQ": ("US", "NYSE"), "PCX": ("US", "NYSE Arca"), "ASE": ("US", "NYSE Am."),
    "BTS": ("US", "BATS"),
    "NSI": ("IN", "NSE"), "BSE": ("IN", "BSE"),
    "LSE": ("UK", "LSE"), "IOB": ("UK", "LSE IOB"),
}


def _sugg_search(q: str) -> list[dict]:
    """One Yahoo search call -> suggestion items for enabled markets (may be [])."""
    import urllib.parse
    data = J._http_json(J.SEARCH_BASE + "?" + urllib.parse.urlencode(
        {"q": q, "quotesCount": 10, "newsCount": 0}))
    items = []
    for x in data.get("quotes", []):
        if not x.get("symbol") or x.get("quoteType") not in ("EQUITY", "ETF"):
            continue
        ui = _EXCH_UI.get(x.get("exchange", ""))
        if not ui or ui[0] not in _ENABLED:
            continue
        items.append({"symbol": x["symbol"],
                      "name": x.get("shortname") or x.get("longname") or x["symbol"],
                      "market": ui[0], "exch": ui[1]})
    return items


@app.get("/api/suggest")
def suggest(q: str = "", market: str = "US"):
    """Type-ahead for the home search box: name/ticker candidates with their market,
    so the user PICKS a stock instead of guessing what the box will resolve to.
    Day-cached per (query, market); selected-market matches rank first.

    SUFFIX FALLBACK (ABB case, 2026-07-15): Yahoo's plain search ranks the global
    brand first — "ABB" returns the Swiss parent + US look-alikes and ABB.NS never
    appears, so an Indian user got no Indian rows. When the selected market has an
    exchange suffix (IN .NS / UK .L), the query is a bare single token, and the first
    pass found nothing for that market, retry with the suffix and put those rows on
    top (same trick the read path uses in _screen_resolved)."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"ok": True, "items": []}
    mk = market.strip().upper()
    key = f"sugg:{mk}:{q.lower()}"
    hit = _cached(key)
    if hit is not None:
        return hit
    try:
        items = _sugg_search(q)
        suffix = {"IN": ".NS", "UK": ".L"}.get(mk)
        if (suffix and " " not in q and not q.upper().endswith((".NS", ".BO", ".L"))
                and not any(it["market"] == mk for it in items)):
            extra = _sugg_search(q + suffix)
            seen = {it["symbol"] for it in extra}
            items = extra + [it for it in items if it["symbol"] not in seen]
    except Exception:  # noqa: BLE001  suggestions are best-effort — empty, not error
        return {"ok": True, "items": []}
    # BSE twins hide behind their NSE listing (2026-07-19, user-hit): Yahoo's .BO tapes
    # are often stubs (LICI.BO = ONE row), so picking the BSE row from this dropdown
    # dead-ended in "couldn't read". Keep a .BO row only when no NSE twin exists.
    ns_bases = {it["symbol"][:-3] for it in items if it["symbol"].endswith(".NS")}
    items = [it for it in items if not (it["symbol"].endswith(".BO")
                                        and it["symbol"][:-3] in ns_bases)]
    items.sort(key=lambda it: 0 if it["market"] == mk else 1)   # stable: Yahoo rank kept
    out = {"ok": True, "items": items[:6]}
    _put(key, out)
    return out


# Markets whose day's-first scan is currently being built by a background thread
# (so repeated home polls don't stack threads on the single-flight lock).
_BUILDING: set[str] = set()


def _kick_scan(mk: str) -> None:
    """Fire-and-forget: build today's momentum list in the background so the home
    study list fills in by itself (~30-60s) instead of waiting for a "see all" tap.
    _momentum_cached is single-flight, so this can never run two scans at once."""
    if mk in _BUILDING:
        return
    _BUILDING.add(mk)

    def run():
        try:
            _momentum_cached(mk)
        except Exception as e:  # noqa: BLE001  background build is best-effort
            print(f"[home] background scan for {mk} failed: {e}", flush=True)
        finally:
            _BUILDING.discard(mk)

    threading.Thread(target=run, daemon=True).start()


@app.get("/api/home")
def home(market: str = "US"):
    """Everything the home screen needs. When today's scan cache is warm: the market
    mood + top Buy-zone names. Cold: kicks the scan in a BACKGROUND thread and returns
    building:true — the frontend shows "Building today's list…" and polls until the
    rows appear. The request itself never blocks on the 30-60s scan."""
    mk = market.strip().upper()
    if mk not in _ENABLED:
        mk = _ENABLED[0]
    regime = _regime_cached(mk)
    lst = _cached(f"mom:{mk}")            # peek; the scan runs in the background
    if not lst:
        _kick_scan(mk)
        return {"ok": True, "market": mk, "regime": regime, "scanned": False,
                "building": True, "study": [], "buyzone_count": None}
    bz = sorted([d for d in lst if "buyzone" in d.get("lanes", [])],
                key=lambda d: 9 if d.get("dip_q") is None else d["dip_q"])
    study = [{"ticker": d["ticker"], "name": d["name"], "market": d["market"],
              "price_str": d["price_str"], "change": d.get("change"),
              "ready": d.get("ready"), "why": d.get("why")} for d in bz[:3]]
    return {"ok": True, "market": mk, "regime": regime, "scanned": True,
            "building": False, "study": study, "buyzone_count": len(bz)}


@app.get("/api/read")
def read(ticker: str, market: str = ""):
    ticker = (ticker or "").strip()
    if not ticker:
        return JSONResponse({"ok": False, "error": "Type a stock first."})
    mk = market.strip().upper()
    mk = mk if mk in _MARKETS else ""          # validate BEFORE it becomes a cache key
    # FRESHNESS (audit H1): a single read is bucketed on ~15 minutes, not the whole day, so
    # an intraday price never freezes for the session and a read first taken PRE-OPEN (last
    # bar = yesterday) refreshes once the market opens. (The heavy many-name LIST scan stays
    # daily-cached — only these one-off reads re-fetch.) The read also carries an honest
    # "as of" stamp so the price is never shown as "now" unlabelled.
    key = f"read:{ticker.upper()}:{mk}:{int(time.time() // 900)}"
    if mk == "IN":
        try:  # with Kite live, an Indian read stays fresh in ~10-min buckets
            if kite_live.available():
                key += f":live{int(time.time() // 600)}"
        except Exception:  # noqa: BLE001
            pass
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
    # never cache a failure — a throttled lookup would make a valid ticker "unreadable"
    # for every user until midnight. SAME principle for a HALF-failure (2026-07-18, LICI):
    # the chart is fetched best-effort, so one Yahoo blip used to pin a chartless page
    # for the whole 15-min bucket; now that read stays uncached and heals on the next tap.
    if out.get("ok") and out.get("chart"):
        _put(key, out)
    return out


def _mom_item(d: dict) -> dict:
    return {"ticker": d["ticker"], "name": d["name"], "market": d["market"],
            "price_str": d["price_str"], "sector": d["sector"],
            "industry": d.get("industry") or "", "raw_sector": d.get("raw_sector") or "",
            "lanes": d["lanes"], "why": d["why"], "n_lanes": d["n_lanes"],
            "perf_w": d.get("perf_w"), "perf_m": d.get("perf_m"),
            "rvol": d.get("rvol"), "ready": d.get("ready"), "dip_q": d.get("dip_q")}


def _verify_buyzone(lst: list, mk: str) -> None:
    """The Buy-zone tab makes the app's strongest promise ("a calm entry may exist
    today"), and the scanner (TradingView) and the read (Yahoo) can disagree on
    razor-edge names — GENUSPOWER sat exactly ON its 50-day (TV +0.0%, Yahoo -0.2%),
    so the lane said "resting" while the read said WEAK (2026-07-12). No threshold
    margin closes a two-source straddle, so every candidate is VERIFIED by the ACTUAL
    read engine before the tab shows it: read tag buy/emerging stays (green dot), a
    settling "wait" stays (amber), weak/avoid/mixed/don't-chase lose the lane. The tab
    is CURATED: the 50 tightest-to-support candidates get verified (IN ran 122 raw
    candidates — the rest are dropped, quality over quantity); ~20s parallel work on
    the day's first scan. SORT NOTE: dip_q can be exactly 0.0 (sitting ON the line —
    the BEST candidates), so never use `or 9` for the missing-value fallback: falsy
    0.0 would sort the tightest names LAST and the cap would drop them (THERMAX case,
    2026-07-12)."""
    import concurrent.futures as cf
    from backend.market_scan import _LANE_WHY
    cand = sorted([d for d in lst if "buyzone" in d.get("lanes", [])],
                  key=lambda d: 9 if d.get("dip_q") is None else d["dip_q"])
    keep, overflow = cand[:50], cand[50:]

    def check(d):
        try:
            r = _read_one(d["ticker"], mk, with_chart=False)
            v = r.get("verdict") or {}
            tag, hl = v.get("tag"), v.get("headline", "")
            if tag in ("buy", "emerging"):
                d["ready"] = "calm"
                return True
            if tag == "wait" and ("steady" in hl or "settle" in hl):
                d["ready"] = "hot"                 # almost ready — amber, honest
                return True
            return False
        except Exception:  # noqa: BLE001  FAIL CLOSED (audit #8, 2026-07-17): on a data
            # error DROP the row. Returning True kept it, and an unverified buyzone row is
            # green-by-construction, so one Yahoo throttle during the day's single scan
            # would freeze unverified "calm entry" rows until midnight. The tab is already
            # curated — losing a few names to a transient error is the safe direction.
            return False

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check, keep))
    for d in [d for d, ok in zip(keep, results) if not ok] + overflow:
        d["lanes"] = [l for l in d["lanes"] if l != "buyzone"]
        d["n_lanes"] = len(d["lanes"])
        d["why"] = _LANE_WHY.get(d["lanes"][0], "momentum") if d["lanes"] else "momentum"
        d.pop("dip_q", None)
    lst[:] = [d for d in lst if d["lanes"]]        # laneless rows leave the list


def _verify_dots(lst: list, mk: str) -> None:
    """VERIFIED DOTS (2026-07-18): the Early/Quiet/Fast readiness dots used to be a
    cheap heuristic that could contradict the stock's own page (the AGCO case). Every
    non-Buy-zone row's dot now comes from the ACTUAL read engine, same as Buy-zone:
      read buy/emerging -> green "calm" · read wait -> amber "hot" ·
      read weak/avoid/mixed -> the row LEAVES the list (a momentum row whose own page
      says "weak / no edge" is a contradiction, not a candidate).
    Unlike Buy-zone (which fails CLOSED — it promises a possible entry), a transient
    read error here keeps the row with a cautious amber dot: these tabs promise no
    entry, so fail-soft is honest and one Yahoo hiccup can't empty the screener.
    Cost: ~60-90s once per market per day, parallel, inside the same daily cache."""
    import concurrent.futures as cf
    todo = [d for d in lst if "buyzone" not in d.get("lanes", [])]

    def check(d):
        try:
            r = _read_one(d["ticker"], mk, with_chart=False)
            tag = (r.get("verdict") or {}).get("tag")
            if tag in ("buy", "emerging"):
                d["ready"] = "calm"
                return True
            if tag == "wait":
                d["ready"] = "hot"
                return True
            return False                    # weak/avoid/mixed — drop the row
        except Exception:  # noqa: BLE001
            d["ready"] = "hot"              # fail-soft: cautious amber, keep the row
            return True

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check, todo))
    dead = {id(d) for d, ok in zip(todo, results) if not ok}
    if dead:
        lst[:] = [d for d in lst if id(d) not in dead]


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
            try:
                _verify_buyzone(lst, mk)
            except Exception as e:  # noqa: BLE001  never let verification kill the scan
                print(f"[scan] buyzone verification failed for {mk}: {e}", flush=True)
            try:
                _verify_dots(lst, mk)
            except Exception as e:  # noqa: BLE001
                print(f"[scan] dot verification failed for {mk}: {e}", flush=True)
            _put(key, lst)
        else:
            print(f"[scan] momentum_list({mk}) returned empty — NOT cached", flush=True)
        return lst


def _breadth_cached(mk: str) -> dict:
    """Per-industry group-health breadth, one TradingView pass per market per day.
    Never day-caches a failure (audit M11 class): one hiccup must not blank the
    group line until midnight."""
    key = f"breadth:{mk}"
    hit = _cached(key)
    if hit is not None:
        return hit
    b = {}
    try:
        from backend.market_scan import industry_breadth
        b = industry_breadth(mk)
    except Exception as e:  # noqa: BLE001  group line is best-effort
        print(f"[breadth] {mk} failed: {e}", flush=True)
    if b:
        _put(key, b)
    return b


def _group_check(read: dict, snap: dict, mk: str) -> None:
    """GROUP HEALTH check line (2026-07-18, step-1: SHOW ONLY — it never changes the
    verdict; the green-demoting gate is a separate, later step that first has to earn
    its power against past-article tests). A stock rarely fights its whole group: when
    most similar stocks are breaking their trend lines, even a strong chart deserves
    extra caution. Thin/unknown groups show nothing rather than a guess."""
    ind = snap.get("industry")
    if not ind or not isinstance(ind, str):
        return
    g = _breadth_cached(mk).get(ind)
    if not g:
        return
    n, b20, hw = g["n"], g["below20"], g["hardweek"]
    if g["health"] == "breaking":
        state = "bad"
        label = (f"Its group is under pressure — {b20} of {n} similar stocks are "
                 f"below their 20-day line"
                 + (f", {hw} fell hard this week." if hw else "."))
    elif g["health"] == "mixed":
        state = "watch"
        label = (f"Its group is mixed — {b20} of {n} similar stocks are below "
                 f"their 20-day line.")
    else:
        state = "good"
        label = "Its group is healthy — most similar stocks are holding their trend lines."
    checks = (read.get("detail") or {}).get("checks")
    if isinstance(checks, list):
        checks.append({"state": state, "label": label})


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
    if reg:            # never day-cache a FAILURE (audit M11): one Yahoo hiccup on the
        _put(key, reg)  # day's first strip request would blank the mood strip until midnight
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
    nifty_live = None
    if mk == "IN":
        try:  # live Kite overlay: fresh prices + today's % on every row (one bulk call)
            if kite_live.available():
                qs = kite_live.quotes([it["ticker"] for it in top])
                for it in top:
                    q = qs.get(it["ticker"])
                    if q:
                        it["price_str"] = _money(q["price"], "INR")
                        it["live_pct"] = q["pct_1d"]
                nifty_live = kite_live.nifty_pct()
        except Exception:  # noqa: BLE001  live layer is best-effort
            pass
    note = f"{len(lst)} names with fresh momentum right now — where money is flowing."
    if n and n > 0:                                   # teaser: light payload, no grouping
        return {"ok": True, "market": mk, "scanned": True, "count": len(lst),
                "top": top, "note": note, "regime": regime, "nifty_live_pct": nifty_live}

    return {"ok": True, "market": mk, "scanned": True, "count": len(lst),
            "top": top, "note": note, "regime": regime, "nifty_live_pct": nifty_live}


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
