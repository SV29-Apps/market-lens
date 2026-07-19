"""
jlaw_data_core.py — data + M.E.T.S. feature engine for the JLaw skill.

Pure-Python core (no MCP dependency) so it can be tested standalone and reused
by the MCP server. Data source: Yahoo public chart/search endpoints (no API key).
Works for any market via exchange suffix (US: none, India: .NS/.BO, UK: .L, etc.).

DESIGN: this module only produces FACTS (prices, MAs, RS, structure, a chart PNG).
All JUDGMENT (the JLaw verdict) lives in the skill/persona layer, not here.
Educational use only — not financial advice.
"""
from __future__ import annotations
import json, math, time, urllib.request, urllib.parse, os
from typing import Optional

import numpy as np
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
SEARCH_BASE = "https://query2.finance.yahoo.com/v1/finance/search"
AV_BASE = "https://www.alphavantage.co/query"

# Exchange (Yahoo exchange code) -> benchmark index for relative strength / broad market.
EXCH_INDEX = {
    # US
    "NMS": "^GSPC", "NYQ": "^GSPC", "NGM": "^GSPC", "PCX": "^GSPC", "ASE": "^GSPC", "BTS": "^GSPC",
    # India
    "NSI": "^NSEI", "BSE": "^BSESN",
    # UK
    "LSE": "^FTSE", "IOB": "^FTSE",
    # a few more majors
    "GER": "^GDAXI", "FRA": "^GDAXI", "PAR": "^FCHI", "AMS": "^AEX",
    "HKG": "^HSI", "TOR": "^GSPTSE", "ASX": "^AXJO", "TYO": "^N225", "SHH": "000001.SS", "SHZ": "399001.SZ",
}
INDEX_NAME = {
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^NSEI": "Nifty 50", "^BSESN": "BSE Sensex",
    "^FTSE": "FTSE 100", "^GDAXI": "DAX", "^FCHI": "CAC 40", "^AEX": "AEX",
    "^HSI": "Hang Seng", "^GSPTSE": "TSX", "^AXJO": "ASX 200", "^N225": "Nikkei 225",
}


# ----------------------------------------------------------------------------- helpers
def _http_json(url: str, tries: int = 3) -> dict:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception as e:  # noqa
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"fetch failed for {url}: {last}")


def _http_text(url: str, tries: int = 2) -> str:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"fetch failed for {url}: {last}")


def _round(x, n=2):
    try:
        if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
            return None
        return round(float(x), n)
    except Exception:
        return None


# Country hint -> set of Yahoo exchange codes (for disambiguating a name across markets).
COUNTRY_EXCH = {
    # NCM = Nasdaq Capital Market (small caps, e.g. AEHR) — leaving it out made the US
    # hint filter DROP the real company and resolve the ticker to a lookalike ETF.
    "US": {"NMS", "NYQ", "NGM", "NCM", "PCX", "ASE", "BTS"},
    "IN": {"NSI", "BSE"}, "INDIA": {"NSI", "BSE"},
    "UK": {"LSE", "IOB"}, "GB": {"LSE", "IOB"},
    "DE": {"GER", "FRA"}, "FR": {"PAR"}, "NL": {"AMS"},
    "HK": {"HKG"}, "CA": {"TOR"}, "AU": {"ASX"}, "JP": {"TYO"},
}


def _cand(x: dict) -> dict:
    exch = x.get("exchange", "")
    idx = EXCH_INDEX.get(exch, "^GSPC")
    return {"symbol": x["symbol"],
            "name": x.get("shortname") or x.get("longname") or x["symbol"],
            "exchange": exch, "quote_type": x.get("quoteType"),
            "benchmark": idx, "benchmark_name": INDEX_NAME.get(idx, idx)}


def resolve(name_or_ticker: str, market: Optional[str] = None) -> dict:
    """Resolve a name or ticker to a canonical Yahoo symbol + benchmark index.

    `market` is an optional country hint ("US","IN","UK","DE",...). When a name
    matches equities on multiple exchanges and no decisive hint is given, returns
    ambiguous=True with ranked candidates so the caller (skill) can disambiguate
    instead of silently guessing a US listing.
    """
    q = urllib.parse.urlencode({"q": name_or_ticker, "quotesCount": 12, "newsCount": 0})
    data = _http_json(f"{SEARCH_BASE}?{q}")
    quotes = [x for x in data.get("quotes", []) if x.get("symbol")]
    eq = [x for x in quotes if x.get("quoteType") in ("EQUITY", "ETF")] or quotes
    if not eq:
        return {"ok": False, "error": f"no match for '{name_or_ticker}'"}

    cands = [_cand(x) for x in eq]
    # apply country hint if given
    if market:
        want = COUNTRY_EXCH.get(market.strip().upper(), set())
        hinted = [c for c in cands if c["exchange"] in want]
        if hinted:
            cands = hinted

    # INDIA: prefer the NSE listing over BSE when the same name trades on both — on
    # Yahoo, .BO tapes are often stubs (LICI.BO: ONE row of history, 2026-07-19) that
    # produce a confidently wrong starved read. Stable sort, so ranking is otherwise kept.
    cands.sort(key=lambda c: 0 if c["exchange"] == "NSI" else 1)

    # Exact ticker typed → that candidate WINS, wherever Yahoo ranked it. Without this
    # re-rank, "AEHR" resolved to AEHG (a 2X leveraged ETF with "AEHR" in its name).
    typed = name_or_ticker.strip().upper()
    exacts = [c for c in cands if c["symbol"].upper() == typed]
    if exacts:
        cands = exacts + [c for c in cands if c["symbol"].upper() != typed]

    top = cands[0]
    # Exact ticker typed → trust it (cross-listings are not ambiguity).
    exact = typed == top["symbol"].upper()
    # Genuine ambiguity only if another candidate is a DIFFERENT company (name mismatch),
    # not just the same company cross-listed on another exchange.
    import difflib
    _norm = lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum())
    different_company = any(
        c["exchange"] != top["exchange"]
        and difflib.SequenceMatcher(None, _norm(c["name"]), _norm(top["name"])).ratio() < 0.6
        for c in cands[1:]
    )
    ambiguous = (market is None) and (not exact) and different_company and top["quote_type"] == "EQUITY"

    return {"ok": True, **top,
            "ambiguous": ambiguous,
            "candidates": cands[:6],
            "alternatives": [f'{c["symbol"]} ({c["exchange"]})' for c in cands[1:6]],
            "hint_used": market}


# ----------------------------------------------------------------------------- ohlcv
_RANGE_DAYS = {"6mo": 190, "1y": 370, "2y": 740, "3y": 1110, "5y": 1850}

# Scan-scoped fetch memo. During the "Strong" list scan EVERY name re-fetches the
# SAME market benchmark (the RS index + the broad-market regime) — hundreds of
# identical requests that risk throttling. memo_on() makes get_ohlcv reuse an
# in-process copy for the duration of the scan; memo_off() clears it. Off by
# default, so the single-stock read is always fresh.
_MEMO: Optional[dict] = None


def memo_on() -> None:
    global _MEMO
    _MEMO = {}


def memo_off() -> None:
    global _MEMO
    _MEMO = None


def _as_of_end(as_of: str):
    """Tolerant 'as of' parser: accepts ISO dates, 'YYYY-MM', 'YYYY', or free text
    like 'Sept 2024' / '2018/2021' (a range takes the most recent year)."""
    import datetime as _dt, re
    s = (as_of or "").strip()
    try:                                   # strict ISO date YYYY-MM-DD
        return _dt.date.fromisoformat(s)
    except Exception:
        pass
    yrs = re.findall(r"(?:19|20)\d{2}", s)
    if not yrs:
        raise ValueError(f"no year in as_of {as_of!r}")
    y = int(yrs[-1])
    months = {m: i + 1 for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
    low = s.lower()
    mo = next((num for name, num in months.items() if name in low), None)
    if mo is None:                         # numeric month, ignoring the year digits
        m2 = re.search(r"\b(0?[1-9]|1[0-2])\b", re.sub(r"(?:19|20)\d{2}", "", s))
        mo = int(m2.group(1)) if m2 else 12
    first_next = _dt.date(y + (mo // 12), (mo % 12) + 1, 1)
    return first_next - _dt.timedelta(days=1)


def get_ohlcv(symbol: str, rng: str = "2y", interval: str = "1d",
              as_of: Optional[str] = None) -> pd.DataFrame:
    if _MEMO is not None:
        mk = (symbol, rng, interval, as_of)
        hit = _MEMO.get(mk)
        if hit is not None:
            return hit
    if as_of:
        import datetime as _dt
        end = _as_of_end(as_of)
        p2 = int(_dt.datetime(end.year, end.month, end.day, 23, 59).timestamp())
        p1 = p2 - _RANGE_DAYS.get(rng, 740) * 86400
        url = (f"{CHART_BASE}{urllib.parse.quote(symbol)}"
               f"?period1={p1}&period2={p2}&interval={interval}")
    else:
        url = f"{CHART_BASE}{urllib.parse.quote(symbol)}?range={rng}&interval={interval}"
    def _pull(u: str = "") -> pd.DataFrame:
        d = _http_json(u or url)
        res = d["chart"]["result"]
        if not res:
            raise RuntimeError(f"no data for {symbol}")
        res = res[0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        out = pd.DataFrame(
            {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]},
            index=pd.to_datetime(ts, unit="s"),
        ).dropna(subset=["close"])
        out.attrs["meta"] = res.get("meta", {})
        return out

    df = _pull()
    # TRUNCATION GUARD (2026-07-19, the LICI case): Yahoo occasionally answers 200 OK
    # with a FRACTION of the requested history (a flaky backend shard). A short daily
    # tape silently wrecks every window downstream — <15 bars kills the ATR (so every
    # risk floor and "extended" measure switches off) and <30 kills relative strength,
    # so a real leader reads "not a clear leader" by starvation, with the whole page
    # then cached. Estimate how many trading rows the request SHOULD have produced
    # (respecting the listing's own age via meta.firstTradeDate) and refetch once when
    # the answer is implausibly short; keep the longer of the two.
    if interval == "1d":
        # ABSOLUTE FLOOR: under ~25 daily bars NOTHING downstream is readable (no 50-day
        # line, no relative strength, no swing, no ATR) — yet such a tape used to render
        # a confident "mixed" page (LICI.BO: ONE row). A genuinely week-old listing is
        # honestly unreadable too; the caller shows "couldn't read" instead of a guess.
        if len(df) < 25:
            raise RuntimeError(f"too little history for {symbol}: {len(df)} rows")
        cal_days = _RANGE_DAYS.get(rng, 740)
        end_ts = p2 if as_of else int(time.time())
        ftd = (df.attrs.get("meta") or {}).get("firstTradeDate")
        eff_start = max(end_ts - cal_days * 86400, ftd or 0)
        exp_rows = max(0.0, (end_ts - eff_start) / 86400) * (5 / 7) * 0.9
        # Degradation comes in TWO shapes (both seen live 2026-07-19): a short stub, and
        # a full-length tape whose older high/low values are null (closes intact — the
        # 52-wk high then drifts and the ATR dies while everything LOOKS complete). So
        # measure VALID rows (high+low+close all present), not raw length.
        n_valid = len(df[["high", "low", "close"]].dropna())
        if exp_rows >= 20 and n_valid < exp_rows * 0.6:
            # retry on Yahoo's ALTERNATE host — a throttled shared IP (Render) tends to
            # keep getting stubs from the same shard; query2 is a different front door.
            retry = _pull(url.replace("query1.", "query2."))
            if len(retry[["high", "low", "close"]].dropna()) > n_valid:
                df = retry
                n_valid = len(df[["high", "low", "close"]].dropna())
        if exp_rows >= 20 and n_valid < exp_rows * 0.6:
            # STILL starved after the retry: refuse to read. A stub tape produces a
            # confidently WRONG page (no ATR -> no risk floors, starved RS -> a real
            # leader reads "not a clear leader", broken chart, drifting 52-wk high).
            # No read is better than a false read; the caller shows "try again" and
            # nothing gets cached.
            raise RuntimeError(f"degraded history for {symbol}: "
                               f"{n_valid} valid rows where ~{int(exp_rows)} expected")
    if _MEMO is not None:
        _MEMO[(symbol, rng, interval, as_of)] = df
    return df


# ----------------------------------------------------------------------------- features
def _ma_block(df: pd.DataFrame, windows) -> dict:
    out = {}
    close = df["close"]
    for w in windows:
        if len(close) >= w:
            ma = close.rolling(w).mean()
            val = ma.iloc[-1]
            prev = ma.iloc[-min(len(ma), 11)]  # ~10 bars ago
            slope = "rising" if val > prev else ("falling" if val < prev else "flat")
            out[f"ma{w}"] = {
                "value": _round(val),
                "slope": slope,
                "price_vs_ma_pct": _round((close.iloc[-1] / val - 1) * 100),
            }
        else:
            out[f"ma{w}"] = None
    return out


def _stack(df: pd.DataFrame, windows) -> str:
    close = df["close"].iloc[-1]
    vals = []
    for w in windows:
        if len(df) >= w:
            vals.append(df["close"].rolling(w).mean().iloc[-1])
        else:
            vals.append(None)
    if any(v is None for v in vals):
        return "insufficient_history"
    bullish = close > vals[0] and all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
    bearish = close < vals[0] and all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
    return "bullish_stack" if bullish else ("bearish_stack" if bearish else "mixed")


def _atr(df: pd.DataFrame, n=14) -> Optional[float]:
    # NaN-SAFE (2026-07-19, the LICI case): get_ohlcv drops rows with a null CLOSE, but
    # Yahoo's India feed also ships scattered rows with null HIGH/LOW and a valid close.
    # One such row inside the window made the rolling mean NaN -> ATR None -> every
    # downstream ATR guard (risk floor, extended-in-ATRs, tight stop) silently off.
    # Compute the true range on valid rows only.
    v = df[["high", "low", "close"]].dropna()
    if len(v) < n + 1:
        return None
    h, l, c = v["high"], v["low"], v["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return _round(tr.rolling(n).mean().iloc[-1])


def _candle(df: pd.DataFrame) -> dict:
    o, h, l, c = (df[k].iloc[-1] for k in ("open", "high", "low", "close"))
    rng = (h - l) or 1e-9
    return {
        "color": "green" if c >= o else "red",
        "body_pct_of_range": _round(abs(c - o) / rng * 100),
        "upper_wick_pct": _round((h - max(o, c)) / rng * 100),
        "lower_wick_pct": _round((min(o, c) - l) / rng * 100),
    }


def _gaps(df: pd.DataFrame, lookback=10, thresh=2.0) -> list:
    out = []
    for i in range(max(1, len(df) - lookback), len(df)):
        prev_c = df["close"].iloc[i - 1]
        op = df["open"].iloc[i]
        g = (op / prev_c - 1) * 100
        if abs(g) >= thresh:
            out.append({"date": str(df.index[i].date()), "gap_pct": _round(g),
                        "dir": "up" if g > 0 else "down"})
    return out


def _swing(df: pd.DataFrame, win=20) -> dict:
    # swing_high feeds the TARGET (resistance overhead) — today's high is a valid recent
    # high, so keep it. #6's danger (an exit at today's fresh low = near-zero risk) is
    # handled downstream in plain_read: _floored_stop forces every exit at least ~1x ATR
    # below the entry, so a brand-new-low bar can never produce a coin-flip stop. (An
    # earlier version excluded today's bar here and wrongly dropped swing_high below the
    # 2%-above-price target threshold, cascading FIG's target to its far 1-year high and
    # blowing R:R up to 41.6 — reverted 2026-07-17.)
    recent = df.tail(win)
    return {"swing_high": _round(recent["high"].max()), "swing_low": _round(recent["low"].min())}


def _rel_return(s: pd.Series, bars: int) -> Optional[float]:
    if len(s) <= bars:
        return None
    return (s.iloc[-1] / s.iloc[-1 - bars] - 1) * 100


def relative_strength(stock: pd.DataFrame, index: pd.DataFrame) -> dict:
    j = stock["close"].to_frame("s").join(index["close"].to_frame("i"), how="inner").dropna()
    if len(j) < 30:
        return {"available": False}
    rs = j["s"] / j["i"]
    rs_ma = rs.rolling(min(50, len(rs))).mean()
    new_high_lb = min(126, len(rs))  # ~6 months
    rs_new_high = bool(rs.iloc[-1] >= rs.tail(new_high_lb).max() * 0.999)
    out = {"available": True,
           # NAMING NOTE (audit M7, verified 2026-07-17): despite the key, this is the RS
           # line's POSITION vs its own 50-bar mean — i.e. "is relative strength SUSTAINED",
           # not the raw 10-bar direction. This is deliberate: I measured a raw 10-bar slope
           # against this on 29 names — it disagreed on 13 and would FLIP 7 verdict tags,
           # and the flips were WRONG (MSFT/CRM/TEAM, genuine broken laggards, would jump
           # from "avoid" to "wait" on a transient RS uptick — undoing the structural-weak
           # fix). The mean-based measure is the more robust leadership signal; the field
           # name is the only thing that's off. `rs_vs_mean` is the honest alias.
           "rs_line_slope": "rising" if rs.iloc[-1] > rs_ma.iloc[-1] else "falling",
           "rs_vs_mean": "above" if rs.iloc[-1] > rs_ma.iloc[-1] else "below",
           "rs_at_new_high_6m": rs_new_high,
           "leader_flag": bool(rs_new_high and rs.iloc[-1] > rs_ma.iloc[-1])}
    for label, bars in (("1m", 21), ("3m", 63), ("6m", 126)):
        sr, ir = _rel_return(j["s"], bars), _rel_return(j["i"], bars)
        out[f"stock_vs_index_{label}"] = (
            {"stock_pct": _round(sr), "index_pct": _round(ir), "excess_pct": _round(sr - ir)}
            if sr is not None and ir is not None else None)
    return out


def broad_market(index_symbol: str, as_of: Optional[str] = None) -> dict:
    """Risk-On / Neutral / Risk-Off read on the benchmark index (the JLaw gate)."""
    try:
        df = get_ohlcv(index_symbol, rng="2y", interval="1d", as_of=as_of)
    except Exception as e:  # noqa
        return {"available": False, "error": str(e)}
    c = df["close"]
    ma20 = c.rolling(20).mean().iloc[-1]
    ma50 = c.rolling(50).mean().iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else None
    sl50 = "rising" if ma50 > c.rolling(50).mean().iloc[-11] else "falling"
    above50, above200 = c.iloc[-1] > ma50, (ma200 is not None and c.iloc[-1] > ma200)
    # Risk-On needs CLEAR DAYLIGHT above the 50-day (>2.5%) and the 20-day intact — an
    # index chopping right around its 50-day is JLaw's textbook CONSOLIDATION (Neutral),
    # not risk-on. Calibrated against his own labels (2026-07-12 fidelity test): his
    # "Risk-On" date sat +7.8% above the 50-day; his three "Neutral" dates sat +1.3-1.6%
    # (both blind judges flagged the old flat rule as one notch too bullish).
    above20 = c.iloc[-1] > ma20
    clear50 = c.iloc[-1] > ma50 * 1.025
    if above50 and above200 and sl50 == "rising" and above20 and clear50:
        regime = "Risk-On"
    elif (not above50) and (ma200 is not None and not above200):
        regime = "Risk-Off"
    else:
        regime = "Neutral"
    return {"available": True, "index": index_symbol, "name": INDEX_NAME.get(index_symbol, index_symbol),
            "regime": regime, "last": _round(c.iloc[-1]),
            "above_50dma": bool(above50), "above_200dma": bool(above200),
            "ma50_slope": sl50, "pct_from_200dma": _round((c.iloc[-1] / ma200 - 1) * 100) if ma200 else None}


def get_news(symbol: str, n: int = 8) -> list:
    """Recent headlines for a symbol (Yahoo search `news` array — no key/auth needed)."""
    import datetime as _dt
    q = urllib.parse.urlencode({"q": symbol, "quotesCount": 1, "newsCount": n})
    try:
        d = _http_json(f"{SEARCH_BASE}?{q}")
    except Exception:
        return []
    out = []
    for it in d.get("news", [])[:n]:
        ts = it.get("providerPublishTime")
        date = _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else None
        out.append({"title": it.get("title"), "publisher": it.get("publisher"),
                    "date": date, "link": it.get("link")})
    return out


def google_news(query: str, n: int = 5) -> list:
    """Recent STOCK-SPECIFIC headlines via Google News RSS — no key/auth, per query.
    `query` is best as the company NAME (a bare ticker like 'BSE' is ambiguous). Returns
    a list of {title, publisher, date (YYYY-MM-DD), link}. Best-effort — [] on any error."""
    import xml.etree.ElementTree as ET
    import email.utils as _eu
    q = urllib.parse.quote_plus(f"{query} stock")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        root = ET.fromstring(_http_text(url))
    except Exception:
        return []
    out = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        # Google appends " - Publisher" to the title AND repeats it in a <source> tag.
        # Strip the redundant suffix so the headline reads cleanly (only when it matches
        # the source, so real " - " inside a headline is left intact).
        pub = (item.findtext("source") or "").strip() or None
        if pub and title.endswith(f" - {pub}"):
            title = title[: -(len(pub) + 3)]
        elif not pub and " - " in title:
            title, pub = title.rsplit(" - ", 1)
        date = None
        pd_ = item.findtext("pubDate")
        if pd_:
            try:
                date = _eu.parsedate_to_datetime(pd_).strftime("%Y-%m-%d")
            except Exception:
                date = None
        out.append({"title": title.strip(), "publisher": pub,
                    "date": date, "link": (item.findtext("link") or "").strip() or None})
        if len(out) >= n:
            break
    return out


def catalysts(symbol: str, features: Optional[dict] = None) -> dict:
    """Catalyst/news context for the 'why' + the normal-vs-structural judgment.
    NOTE: headlines are CURRENT (not point-in-time) — fine for live screening; for a historical
    backtest treat them as context only. Earnings calendar isn't available without auth, but
    earnings/M&A/guidance news shows up in the headlines and in `recent_event_gaps`."""
    gaps = (features or {}).get("daily", {}).get("recent_gaps", []) if features else []
    return {"recent_news": get_news(symbol, 8),
            "recent_event_gaps": gaps,
            "how_to_use": "Read the headlines: a sharp move WITH a fundamental catalyst "
                          "(earnings, M&A, guidance cut, regulatory) is real and re-rates the thesis; "
                          "a sharp move with NO negative fundamental news (index-rebalancing, options "
                          "expiry, sector beta, profit-taking) is mechanical/flow — lean 'normal pullback' "
                          "if structure + RS hold. Match a big bar in `recent_event_gaps` to a headline."}


def news_sentiment(symbol: str, days: int = 14, max_articles: int = 50) -> dict:
    """Aggregate recent NEWS SENTIMENT for `symbol` from Alpha Vantage NEWS_SENTIMENT.

    This is the one signal a deterministic read can ACT on (headlines alone give nothing
    to compute). It needs a FREE key in env ALPHAVANTAGE_API_KEY. The free tier is tiny
    (25 requests/day, 5/min), so the app calls this ONLY for the single-stock read and
    caches it daily — never for the many-name "Strong" list.

    Returns {"have": True, "score", "label", "n", "pos", "neg", "latest"} where score is
    the relevance-weighted average ticker sentiment (Alpha Vantage bands: <=-0.35 very
    negative, <=-0.15 negative, <0.15 mixed, <0.35 positive, else very positive). Any of
    no key / rate-limit / non-US ticker with no coverage / error -> {"have": False,...},
    so the price-only read simply stands. Best-effort; never raises."""
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not key:
        return {"have": False, "reason": "no_key"}
    # NON-US GUARD (audit M10): AV coverage is US-centric and keyed on the bare ticker.
    # Truncating "TITAN.NS" -> "TITAN" would fetch the sentiment of an UNRELATED US "TITAN"
    # and mis-attribute it to the Indian stock. Only query when the symbol is a plain US
    # ticker (no exchange suffix). India/UK reads simply run news-free (they already do in
    # prod anyway — AV is throttled on Render's shared IP).
    if "." in symbol:
        return {"have": False, "reason": "non_us_symbol"}
    av_ticker = symbol.upper()
    since = time.strftime("%Y%m%dT0000", time.gmtime(time.time() - days * 86400))
    q = urllib.parse.urlencode({"function": "NEWS_SENTIMENT", "tickers": av_ticker,
                                "time_from": since, "sort": "LATEST",
                                "limit": max_articles, "apikey": key})
    try:
        d = _http_json(f"{AV_BASE}?{q}", tries=2)
    except Exception:
        return {"have": False, "reason": "fetch_error"}
    # Rate-limit / invalid-key / info responses come back as a Note/Information/Error field
    # (with no "feed"), not an HTTP error.
    if not isinstance(d, dict) or any(k in d for k in ("Note", "Information", "Error Message")):
        return {"have": False, "reason": "limited_or_invalid"}
    scores, weights, pos, neg = [], [], 0, 0
    for art in d.get("feed", []) or []:
        for ts in art.get("ticker_sentiment", []) or []:
            if (ts.get("ticker") or "").upper() != av_ticker:
                continue
            try:
                sc = float(ts.get("ticker_sentiment_score"))
                rel = float(ts.get("relevance_score") or 0)
            except (TypeError, ValueError):
                continue
            if rel <= 0:
                continue
            scores.append(sc)
            weights.append(rel)
            if sc >= 0.15:
                pos += 1
            elif sc <= -0.15:
                neg += 1
    if not scores or sum(weights) <= 0:
        return {"have": False, "reason": "no_ticker_news"}
    avg = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
    if avg <= -0.35:
        label = "very negative"
    elif avg <= -0.15:
        label = "negative"
    elif avg < 0.15:
        label = "mixed"
    elif avg < 0.35:
        label = "positive"
    else:
        label = "very positive"
    latest = None
    feed = d.get("feed") or []
    if feed:
        latest = (feed[0].get("title") or None)
    return {"have": True, "score": round(avg, 3), "label": label,
            "n": len(scores), "pos": pos, "neg": neg, "latest": latest}


def rr(entry: float, stop: float, target: float) -> dict:
    risk = abs(entry - stop)
    reward = abs(target - entry)
    return {"risk_per_share": _round(risk), "reward_per_share": _round(reward),
            "r_multiple": _round(reward / risk, 2) if risk else None}


def _freshness(meta: dict, as_of: Optional[str], bar_date: str) -> dict:
    """How fresh the last bar is, from Yahoo meta. `intraday` = the market is in its
    regular session RIGHT NOW, so the last daily bar is a live PARTIAL bar (its volume is
    only part of a day, and its close is a moving last price). `session_frac` = elapsed
    fraction of today's session (to time-adjust that partial volume, audit H3). For a
    backtest `as_of` read the last bar is historical, so never intraday."""
    if as_of:
        return {"bar_date": bar_date, "as_of": as_of, "intraday": False,
                "session_frac": None, "observed_ts": None}
    rmt = meta.get("regularMarketTime")
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = reg.get("start"), reg.get("end")
    now = time.time()
    intraday = bool(start and end and start <= now < end)
    frac = max(0.0, min(1.0, (now - start) / (end - start))) if (intraday and end > start) else None
    return {"bar_date": bar_date, "as_of": None, "intraday": intraday,
            "session_frac": frac, "observed_ts": rmt}


def _volume_block(daily: pd.DataFrame, fresh: dict) -> dict:
    """Today vs the 50-day average — but time-adjusted when the last bar is a live partial
    (audit H3: raw partial-vs-full-day made every intraday read look "calm/quiet"). Just
    after the open (frac < 5%) the ratio is meaningless -> None, and the read degrades to
    'no clear reading yet' instead of a false 'calm'."""
    vl = daily["volume"].iloc[-1]
    v_last = None if (vl is None or (isinstance(vl, float) and math.isnan(vl))) else int(vl)
    a50 = daily["volume"].tail(50).mean()
    avg50 = None if math.isnan(a50) else int(a50)
    ratio, adjusted = None, False
    if v_last is not None and avg50:
        if fresh.get("intraday"):
            frac = fresh.get("session_frac")
            if frac and frac >= 0.05:
                ratio, adjusted = _round(v_last / (avg50 * frac)), True
            # else: session barely open -> leave ratio None (no honest reading yet)
        else:
            ratio = _round(v_last / avg50)          # a completed day (or as_of): honest
    return {"last": v_last, "avg50": avg50, "ratio_vs_avg50": ratio,
            "session_adjusted": adjusted}


def _trend_memory(df: pd.DataFrame) -> dict:
    """The read's small MEMORY (2026-07-18) — two facts about the recent PAST that a
    last-bar snapshot can't see, both computed from bars already fetched:
    - days_below_50: consecutive completed sessions the close has been under the 50-day
      line, counting back from the latest bar (0 = above it now). JLaw gives a name
      ~4-6 trading days to reclaim the line before calling the trend broken.
    - worst_drop_3d: the most negative 1-day % change across the last 3 completed
      sessions. A green "buyable" must not fire the day after a high-energy decline
      (the NTAP case: -7.1% on 15 Jul was invisible to a 1-day lookback on the 16th).
    """
    c = df["close"]
    out = {"days_below_50": None, "worst_drop_3d": None}
    if len(c) > 3:
        out["worst_drop_3d"] = _round(((c / c.shift(1) - 1) * 100).tail(3).min())
    if len(c) >= 50:
        below = c < c.rolling(50).mean()
        n = 0
        for v in below.iloc[::-1]:
            if not bool(v):
                break
            n += 1
        out["days_below_50"] = n
    return out


def compute_features(symbol: str, benchmark: str = "^GSPC", as_of: Optional[str] = None,
                     light: bool = False) -> dict:
    # light=True skips the weekly bars (a 3rd Yahoo fetch/name) — the plain read never
    # reads f["weekly"], so the read/tag is identical, but it's ~1/3 fewer requests
    # across the ~300-name list scan. Used only on the list path.
    daily = get_ohlcv(symbol, rng="2y", interval="1d", as_of=as_of)
    weekly = None if light else get_ohlcv(symbol, rng="5y", interval="1wk", as_of=as_of)
    idx = get_ohlcv(benchmark, rng="2y", interval="1d", as_of=as_of)
    meta = daily.attrs.get("meta", {})
    c = daily["close"]
    fresh = _freshness(meta, as_of, str(daily.index[-1].date()))
    feat = {
        "symbol": symbol,
        "currency": meta.get("currency"),
        "freshness": fresh,
        "last_close": _round(c.iloc[-1]),
        "pct_change_1d": _round((c.iloc[-1] / c.iloc[-2] - 1) * 100) if len(c) > 1 else None,
        "fifty_two_week": {
            "high": _round(daily["high"].tail(252).max()),
            "low": _round(daily["low"].tail(252).min()),
            "pct_from_high": _round((c.iloc[-1] / daily["high"].tail(252).max() - 1) * 100),
            "pct_from_low": _round((c.iloc[-1] / daily["low"].tail(252).min() - 1) * 100),
        },
        "daily": {
            "moving_averages": _ma_block(daily, [10, 20, 50, 200]),
            "ma_stack": _stack(daily, [10, 20, 50, 200]),
            "atr14": _atr(daily),
            "last_candle": _candle(daily),
            "recent_gaps": _gaps(daily),
            "swing": _swing(daily, 20),
            "volume": _volume_block(daily, fresh),
            "trend_memory": _trend_memory(daily),
        },
        "weekly": None if weekly is None else {
            "moving_averages": _ma_block(weekly, [10, 20, 50]),
            "ma_stack": _stack(weekly, [10, 20, 50]),
            "last_candle": _candle(weekly),
        },
        "relative_strength": relative_strength(daily, idx),
        "suggested_stop_ideas": {
            "below_recent_swing_low": _swing(daily, 20)["swing_low"],
            "atr_1_5x_below_close": _round(c.iloc[-1] - 1.5 * (_atr(daily) or 0)),
        },
    }
    return feat


# ----------------------------------------------------------------------------- chart
def render_chart(symbol: str, outdir: str, timeframe: str = "daily",
                 as_of: Optional[str] = None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import mplfinance as mpf
    rng, interval, mas = ("1y", "1d", (10, 20, 50, 200)) if timeframe == "daily" else ("3y", "1wk", (10, 20, 50))
    df = get_ohlcv(symbol, rng=rng, interval=interval, as_of=as_of)[["open", "high", "low", "close", "volume"]]
    df.index.name = "Date"
    os.makedirs(outdir, exist_ok=True)
    safe = symbol.replace("^", "IDX_").replace("/", "_") + (f"_{as_of}" if as_of else "")
    path = os.path.join(outdir, f"{safe}_{timeframe}.png")
    mpf.plot(df, type="candle", style="yahoo", mav=mas, volume=True,
             title=f"{symbol} — {timeframe} (MAs {', '.join(map(str, mas))})",
             savefig=dict(fname=path, dpi=110, bbox_inches="tight"))
    return path


# ----------------------------------------------------------------------------- orchestrator
def screen(name_or_ticker: str, outdir: Optional[str] = None, make_charts: bool = True,
           market: Optional[str] = None, as_of: Optional[str] = None,
           light: bool = False) -> dict:
    r = resolve(name_or_ticker, market)
    if not r.get("ok"):
        return r
    if r.get("ambiguous"):
        return {"resolved": r, "needs_disambiguation": True,
                "message": f"'{name_or_ticker}' matches several markets — pass a market hint "
                           f"(e.g. US/IN/UK) or an exact symbol.",
                "candidates": r["candidates"]}
    sym, bench = r["symbol"], r["benchmark"]
    feats = compute_features(sym, bench, as_of=as_of, light=light)
    bundle = {"resolved": r, "as_of": as_of or "latest",
              "broad_market": broad_market(bench, as_of=as_of),
              "features": feats,
              "catalysts": catalysts(sym, feats)}
    if make_charts and outdir:
        bundle["charts"] = {}
        for tf in ("daily", "weekly"):
            try:
                bundle["charts"][tf] = render_chart(sym, outdir, tf, as_of=as_of)
            except Exception as e:  # noqa
                bundle["charts"][tf] = f"ERROR: {e}"
    return bundle


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    out = screen(target, outdir=os.path.join(os.path.dirname(__file__), "..", "charts_out"))
    print(json.dumps(out, indent=2, default=str))
