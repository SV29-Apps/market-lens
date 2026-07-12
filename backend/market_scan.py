"""market_scan.py — find the strongest momentum names market-wide.

Uses TradingView's scanner (server-side, free, ~15-min delayed) to pull the
strongest names in a clean uptrend, so "Strong right now" covers the WHOLE
market instead of a hand-picked list. The deep per-stock read still comes from
the JLaw engine + plain_read when a user taps a name.

Building a Query touches no network; .get_scanner_data() does. Educational only.
"""

from __future__ import annotations

# Per-market scan profile. The "Strong right now" list is a MOMENTUM SCREENER
# (Sanat-style, 2026-07-02): it finds where money is flowing NOW — fresh movers +
# quiet leaders making new highs — WITHOUT a 6-month-strength gate. A stock qualifies
# via any lane (see momentum_list): up big this WEEK / MONTH / DAY (and above its
# trend lines), OR quietly at a NEW HIGH above all its moving averages. The JLaw
# buy/wait judgment is NOT applied to the list — it happens when you OPEN a stock.
#   wk/mo/day  = momentum bars (% moves) for the weekly / monthly / intraday lanes
#   near_high  = quiet-leader lane: within this % of the 52-week high (making new highs)
#   floors: price_min, mcap_min, dollar_vol (liquid, real stocks — kills micro-pumps).
#   dollar_vol is a FULL-DAY turnover floor, enforced in Python on the 10-day AVERAGE
#   (avg volume × close) — never on the session's running total, which starts near zero
#   every morning and would thin the lanes early in the day (the Early-tab bug class).
#   UK NOTE: TradingView quotes LSE in PENCE, so price_min/dollar_vol are in pence
#   (100 = £1; 200M = £2M/day) and closes are divided by 100 for display.
# (perf6m kept only for the legacy strongest_list fallback; unused by momentum_list.)
_SCAN = {
    "US": dict(market="america", exchange="",    cur="$", price_min=15.0,  mcap_min=1_000_000_000,   dollar_vol=50_000_000,  perf6m=10.0, wk=10.0, mo=30.0, day=6.0, near_high=3.0, bench="^GSPC"),
    "IN": dict(market="india",   exchange="NSE", cur="₹", price_min=75.0,  mcap_min=50_000_000_000,  dollar_vol=100_000_000, perf6m=10.0, wk=8.0,  mo=22.0, day=4.0, near_high=3.0, bench="^NSEI"),
    "UK": dict(market="uk",      exchange="LSE", cur="£", price_min=100.0, mcap_min=500_000_000,     dollar_vol=200_000_000, perf6m=8.0,  wk=6.0,  mo=18.0, day=3.5, near_high=3.0, bench="^FTSE"),
}

# TradingView files semiconductor-EQUIPMENT makers under "Industrial Machinery"
# (next to Caterpillar), which confuses beginners. Reclassify these into "Chips".
_SEMI_EQUIP = {"AMAT", "LRCX", "KLAC", "ICHR", "UCTT", "ACMR", "KLIC", "ONTO", "AEHR",
               "AEIS", "COHU", "FORM", "MKSI", "ACLS", "NVMI", "CAMT", "ASYS", "VECO",
               "PLAB", "AMKR", "CCMP", "OLED", "IPGP", "MTSI", "SITM", "POWI"}

# Ordered (keyword-in-industry -> friendly bucket). First match wins. Keyed on the
# TradingView `industry` (finer than its odd top-level `sector`), lower-cased.
_SECTOR_RULES = [
    ("semiconductor", "Chips"), ("electronic component", "Chips"),
    ("electronic equipment", "Chips"), ("electronic production", "Chips"),
    ("computer processing", "Chips"), ("telecommunications equipment", "Chips"),
    ("computer peripheral", "Chips"),
    ("software", "Software & Internet"), ("internet", "Software & Internet"),
    ("information technology services", "Software & Internet"),
    ("data processing", "Software & Internet"), ("data center", "Software & Internet"),
    ("biotechnology", "Healthcare"), ("pharmaceutical", "Healthcare"),
    ("medical", "Healthcare"), ("health", "Healthcare"), ("hospital", "Healthcare"),
    ("drug", "Healthcare"),
    ("bank", "Finance"), ("insurance", "Finance"), ("investment", "Finance"),
    ("financ", "Finance"), ("real estate", "Finance"), ("broker", "Finance"),
    ("savings", "Finance"),
    ("aerospace", "Industrials"), ("building products", "Industrials"),
    ("electrical product", "Industrials"), ("industrial machinery", "Industrials"),
    ("construction", "Industrials"), ("trucks", "Industrials"), ("machinery", "Industrials"),
    ("auto parts", "Industrials"), ("wholesale", "Industrials"), ("distributor", "Industrials"),
    ("airlines", "Industrials"), ("marine", "Industrials"), ("transportation", "Industrials"),
    ("engineering", "Industrials"), ("industrial", "Industrials"),
    ("motor vehicle", "Consumer"), ("specialty stores", "Consumer"), ("retail", "Consumer"),
    ("movies", "Consumer"), ("entertainment", "Consumer"), ("electronics/appliances", "Consumer"),
    ("restaurant", "Consumer"), ("apparel", "Consumer"), ("consumer", "Consumer"),
    ("hotels", "Consumer"), ("recreational", "Consumer"), ("food", "Consumer"),
    ("beverages", "Consumer"), ("household", "Consumer"), ("textiles", "Consumer"),
    ("oil", "Energy & Materials"), ("gas", "Energy & Materials"), ("energy", "Energy & Materials"),
    ("metals", "Energy & Materials"), ("mineral", "Energy & Materials"), ("mining", "Energy & Materials"),
    ("containers", "Energy & Materials"), ("packaging", "Energy & Materials"),
    ("chemical", "Energy & Materials"), ("steel", "Energy & Materials"), ("coal", "Energy & Materials"),
    ("forest", "Energy & Materials"), ("agricultural", "Energy & Materials"),
]


def friendly_sector(sector: str, industry: str, ticker: str) -> str:
    """Map TradingView's coarse sector/industry to a clear, beginner-friendly bucket
    (Chips / Software & Internet / Healthcare / Finance / Industrials / Consumer /
    Energy & Materials / Other), fixing the semiconductor-equipment mislabel."""
    tk = (ticker or "").split(":")[-1].upper()
    for suf in (".NS", ".BO", ".L"):
        if tk.endswith(suf):
            tk = tk[:-len(suf)]
    ind = (industry or "").lower()
    if tk in _SEMI_EQUIP:
        return "Chips"
    for kw, bucket in _SECTOR_RULES:
        if kw in ind:
            return bucket
    # fall back to a couple of the broad `sector` labels if industry didn't match
    sec = (sector or "").lower()
    if "technology" in sec or "electronic" in sec:
        return "Software & Internet"
    if "health" in sec:
        return "Healthcare"
    if "finance" in sec:
        return "Finance"
    return "Other"

# Classify a scan row the SAME way the deep read does (extended above the 50-day,
# or jumped hard today -> "wait, don't chase"; otherwise a resting leader -> "buy").
# Lightweight (no per-name fetch) so the list can be big and load in one query.
_SUB = {"buy": "A leader, resting at a calmer spot.",
        "wait": "A real leader, but it has run up. Better to wait."}


def _classify(close, sma50, change, high52w) -> str:
    extended = sma50 and ((close / sma50) - 1) * 100 > 12       # >12% above the 50-day
    popped = (change or 0) > 4                                  # jumped hard today
    near_high = high52w and close >= high52w * 0.95             # within ~5% of the 1-year high
    # matches the deep read's "wait" triggers so the list and the read agree.
    return "wait" if (extended or popped or near_high) else "buy"


_SNAP_COLS = ["description", "sector", "industry", "Perf.W", "Perf.1M",
              "price_earnings_ttm", "Value.Traded"]


def snapshot(ticker: str, market_key: str) -> dict | None:
    """One-off header stats for a single stock (sector, week/month %, P/E, weekly
    turnover) from TradingView. Best-effort — returns None on any failure."""
    p = _SCAN.get((market_key or "").strip().upper())
    if not p:
        return None
    try:
        from tradingview_screener import Query, col
    except Exception:  # noqa: BLE001
        return None
    sym = str(ticker).split(":")[-1].upper()
    for suf in (".NS", ".BO", ".L"):
        if sym.endswith(suf):
            sym = sym[:-len(suf)]
    flt = [col("name") == sym]
    if p["exchange"]:
        flt.append(col("exchange") == p["exchange"])
    try:
        _, df = (Query().set_markets(p["market"]).select(*_SNAP_COLS)
                 .where(*flt).limit(1).get_scanner_data())
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty:
        return None
    row = df.iloc[0]

    def g(k):
        v = row.get(k)
        try:
            return None if v is None or (isinstance(v, float) and v != v) else v
        except Exception:  # noqa: BLE001
            return v

    vt, cur = g("Value.Traded"), p["cur"]
    if vt:
        turnover = (f"{cur}{round(vt/1e7):,} Cr" if cur == "₹"
                    else (f"{cur}{vt/1e9:.1f}B" if vt >= 1e9 else f"{cur}{round(vt/1e6):,}M"))
    else:
        turnover = None
    def num(k):
        v = g(k)
        try:
            return float(v) if v is not None else None
        except Exception:  # noqa: BLE001
            return None

    return {"sector": g("sector"), "industry": g("industry"),
            "perf_w": num("Perf.W"), "perf_m": num("Perf.1M"),
            "pe": num("price_earnings_ttm"), "turnover": turnover}


# momentum lanes, in display priority order + a plain "why" phrase per lane.
# buyzone first: when a name is both "resting at support" and e.g. "up big this month",
# the resting fact is the actionable one.
_LANE_ORDER = ["buyzone", "day", "week", "month", "newhigh", "early"]
_LANE_WHY = {"buyzone": "resting at support — possible calm entry",
             "day": "jumped today", "week": "up big this week",
             "month": "up big this month", "newhigh": "at new highs, beating the market",
             "early": "early turn — reclaimed its trend, RS rising"}


def _num(v):
    try:
        return None if v is None or (isinstance(v, float) and v != v) else float(v)
    except Exception:  # noqa: BLE001
        return None


def _bench_perf(bench_symbol: str | None) -> dict:
    """Market index return over ~1/3/6 months, for the true relative-strength check
    (a stock 'beating the market'). One Yahoo fetch per scan; {m1,m3,m6}=None on failure
    so the RS gate simply doesn't apply (lane falls back to price structure only)."""
    out = {"m1": None, "m3": None, "m6": None}
    if not bench_symbol:
        return out
    try:
        from backend import jlaw_data_core as J
        c = J.get_ohlcv(bench_symbol, rng="1y")["close"]
        n = len(c)
        for k, days in (("m1", 21), ("m3", 63), ("m6", 126)):
            if n > days:
                out[k] = (c.iloc[-1] / c.iloc[-1 - days] - 1) * 100
    except Exception:  # noqa: BLE001
        pass
    return out


def momentum_list(market_key: str, cap: int = 400) -> list[dict]:
    """The MOMENTUM SCREENER — where money is flowing now. A stock qualifies via any
    lane (fresh movers + quiet leaders), NO 6-month-strength gate. Each result is
    tagged with the lane(s) it passed and a friendly sector. No JLaw buy/wait judgment
    here (that happens when the stock is opened). [] on failure so the caller falls back.

    Lanes (all also require the base floors: real liquid stock, price/mcap/turnover):
      day     — up > day% today AND at least flat on the month, above the 200-day
      week    — up > wk% this week, above the 10/20/50/200-day
      month   — up > mo% this month, above the 200-day
      newhigh — above the 10/20/50/200-day AND within near_high% of the 52-week high
                (+ true-RS vs the index, applied in Python)
      early   — Stage 1->2 turn: above all MAs, 50>200, turning up but NOT a fast mover,
                just reclaimed the 50-day, room below highs (details in Python below)
    """
    p = _SCAN.get((market_key or "").strip().upper())
    if not p:
        return []
    try:
        from tradingview_screener import Query, col
    except Exception:  # noqa: BLE001
        return []

    base = [
        col("type") == "stock",
        col("typespecs").has(["common"]),
        col("close") >= p["price_min"],
        col("market_cap_basic") >= p["mcap_min"],
        # coarse junk filter only (5% of the floor): Value.Traded is the SESSION'S
        # RUNNING total, near zero at the open — the real full-day liquidity floor is
        # enforced in Python below on the 10-day average, which doesn't swing intraday.
        col("Value.Traded") >= p["dollar_vol"] * 0.05,
    ]
    if p["exchange"]:
        base.append(col("exchange") == p["exchange"])

    bench = _bench_perf(p.get("bench"))          # market return for the true-RS check

    lanes = {
        # day lane also requires the MONTH to be at least flat: a one-day jump in a
        # stock that's DOWN on the month is a bounce, not momentum (2026-07-11 — the
        # India Fast movers tab was showing -2%/-6%-month names off a single up day).
        "day":   [col("change") > p["day"], col("close") > col("SMA200"),
                  col("Perf.1M") >= 0],
        "week":  [col("Perf.W") > p["wk"], col("close") > col("SMA10"),
                  col("close") > col("SMA20"), col("close") > col("SMA50"),
                  col("close") > col("SMA200")],
        "month": [col("Perf.1M") > p["mo"], col("close") > col("SMA200")],
        # quiet leader: above all MAs; the near-high test AND the true-RS test (beating
        # the index over 3 & 6 months) are applied in Python below.
        "newhigh": [col("close") > col("SMA10"), col("close") > col("SMA20"),
                    col("close") > col("SMA50"), col("close") > col("SMA200")],
        # early / emerging (JLaw's Stage 1->2 turn): long trend intact, just turning up.
        # NO volume gate (see NOTE below) — volume RANKS the tab instead (rvol, frontend).
        # "just reclaimed the 50-day (not extended)", "room below highs" and "starting to
        # beat the market" are applied in Python below.
        "early": [col("close") > col("SMA10"), col("close") > col("SMA20"),
                  col("close") > col("SMA50"), col("close") > col("SMA200"),
                  col("SMA50") > col("SMA200"),                 # long trend intact (200 not rolling over)
                  # NOTE: there is deliberately NO volume gate here. The original
                  # `relative_volume_10d_calc >= 1.0` was an INTRADAY-cumulative field
                  # (~0.1–0.4 at most scan times) that silently ZEROED the whole lane
                  # whenever the scan ran outside late-session hours — the "Early tab is
                  # empty" bug (2026-07-06). Two blind reviewers + the deep read agreed
                  # volume should RANK an early turn, not EXCLUDE it ("by the time volume is
                  # clearly building, the move is no longer *early*"), so it's dropped as a
                  # hard filter. The structural + performance gates below define "early".
                  col("Perf.1M") > 0, col("Perf.W") < p["wk"],  # turning up, but NOT a fast mover
                  # < 4% today matches the read's own "just popped, don't chase" bar (4%),
                  # so an Early candidate can never read "don't chase the jump" the same day
                  col("change") < 4, col("change") > -4],
    }
    # buyzone — JLaw's actual entry hunt (added 2026-07-12): a PROVEN leader whose dip
    # has already happened and which is now RESTING AT SUPPORT. Motion lanes can't see
    # these (verified: none of the read's "Looks buyable" leaders appeared in any lane).
    # Query keeps only the cheap structure; the leader/dip/support tests run in Python.
    # week floor is -15, not tighter: a sharp down-week is often what CREATES the dip
    # onto the 50-day (MRVL -12.5% week landing on its rising 50-day, 2026-07-12) —
    # the on-support + calm-today + true-RS gates below handle genuine brokenness.
    lanes["buyzone"] = [col("close") > col("SMA200"),
                        col("Perf.W") < p["wk"], col("Perf.W") > -15,
                        col("change") < 4, col("change") > -4]         # calm today

    near_factor = 1 - p["near_high"] / 100.0
    cols = ["name", "description", "close", "change", "Perf.W", "Perf.1M", "Perf.3M",
            "Perf.6M", "SMA20", "SMA50", "ATR", "relative_volume_10d_calc",
            "price_52_week_high", "market_cap_basic", "sector", "industry"]

    merged: dict[str, dict] = {}
    for lane, extra in lanes.items():
        try:
            _, df = (Query().set_markets(p["market"]).select(*cols)
                     .where(*base, *extra)
                     .order_by("market_cap_basic", ascending=False)
                     .limit(500).get_scanner_data())
        except Exception:  # noqa: BLE001  one lane failing shouldn't kill the screen
            continue
        if df is None or df.empty or "name" not in df:
            continue
        for _, r in df.iterrows():
            c = _num(r.get("close")); hi = _num(r.get("price_52_week_high"))
            sma20 = _num(r.get("SMA20")); sma50 = _num(r.get("SMA50"))
            atr = _num(r.get("ATR"))
            p1 = _num(r.get("Perf.1M")); p3 = _num(r.get("Perf.3M")); p6 = _num(r.get("Perf.6M"))
            # the REAL liquidity floor: 10-day-average turnover (avg volume × close) —
            # stable all day, unlike the session's cumulative Value.Traded.
            avg_vol = _num(r.get("average_volume_10d_calc"))
            if avg_vol is not None and c and avg_vol * c < p["dollar_vol"]:
                continue
            # --- per-lane Python gates (what the TradingView query couldn't express) ---
            if lane == "newhigh":
                if not (c and hi and c >= hi * near_factor):          # near the 52w high
                    continue
                if bench["m3"] is not None and not (p3 is not None and p3 > bench["m3"]):
                    continue                                          # true RS: beat index 3m
                if bench["m6"] is not None and not (p6 is not None and p6 > bench["m6"]):
                    continue                                          # true RS: beat index 6m
            elif lane == "early":
                if not (c and sma50 and 0 <= (c / sma50 - 1) <= 0.10):  # just reclaimed 50-day
                    continue
                if not (c and hi and c <= hi * 0.90):                 # room below its highs
                    continue
                if bench["m1"] is not None and not (p1 is not None and p1 > bench["m1"]):
                    continue                                          # starting to beat market
                if p6 is not None and p6 >= 30:                       # hasn't already run huge
                    continue
                # a genuine Stage 1->2 turn comes FROM BEHIND: still clearly lagging the
                # index over 6 months (by >= 2 pts), only now starting to beat it.
                # Without this, an ESTABLISHED leader that dipped and re-approached its
                # 50-day (e.g. NVDA, +12% in 6m) lands in "Early" while its own read
                # calls it "a real leader" (user-reported 2026-07-11). The 2-pt margin
                # + the read's own 2-pt leader bar keep borderline names from straddling
                # the two data sources (TradingView here, Yahoo in the read).
                if bench["m6"] is not None and p6 is not None and p6 > bench["m6"] - 2:
                    continue
            elif lane == "buyzone":
                if not (c and hi and atr and sma50):
                    continue
                # a PROVEN leader (true RS over 3 & 6 months, like the newhigh lane)
                if bench["m3"] is not None and not (p3 is not None and p3 > bench["m3"]):
                    continue
                if bench["m6"] is not None and not (p6 is not None and p6 > bench["m6"]):
                    continue
                if c > hi * 0.95:                          # the dip hasn't happened yet
                    continue
                # resting ON support, not hanging under it: must be above at least one
                # of the two lines. Without this, a WEAK name below BOTH its 20- and
                # 50-day can sit "within 1 ATR" of the 50 from BENEATH (LSCC/NXPI case,
                # 2026-07-12). No max-depth floor: a deep-but-healthy pullback (MRVL,
                # ~28% off its high with rising RS) is exactly what JLaw wants to catch;
                # the true-RS + above-200-day + on-support tests handle brokenness.
                if not ((sma20 and c >= sma20) or c >= sma50):
                    continue
                d20 = abs(c - sma20) / atr if sma20 else 99.0
                d50 = abs(c - sma50) / atr
                if min(d20, d50) > 1.0:                    # sitting within 1 ATR of support
                    continue
                bz_why = ("resting near its 20-day line" if d20 <= d50
                          else "resting near its 50-day line")
                bz_q = round(min(d20, d50), 2)
            tk = str(r["name"])
            d = merged.get(tk)
            if d is None:
                close = c or 0.0
                if p["cur"] == "£":
                    close = close / 100.0        # LSE quotes in pence -> pounds for display
                chg = _num(r.get("change"))
                # readiness dot (same graded ATR scale as the read): amber "hot" when
                # stretched >4 ATRs above the 50-day or when today moved >±4%.
                hot = bool((atr and sma50 and c and (c - sma50) / atr > 4)
                           or (chg is not None and abs(chg) > 4))
                d = merged[tk] = {
                    "ticker": tk,
                    "name": str(r.get("description") or tk),
                    "market": market_key.strip().upper(),
                    "price_str": f"{p['cur']}{round(close):,}",
                    "rvol": _num(r.get("relative_volume_10d_calc")),
                    "ready": "hot" if hot else "calm",
                    "sector": friendly_sector(r.get("sector"), r.get("industry"), tk),
                    "raw_sector": str(r.get("sector") or ""),
                    "industry": str(r.get("industry") or ""),
                    "perf_w": _num(r.get("Perf.W")), "perf_m": p1,
                    "change": chg,
                    "lanes": set(),
                }
            d["lanes"].add(lane)
            if lane == "buyzone":
                d["dip_q"] = bz_q          # distance to support in ATRs (sort key)
                d["bz_why"] = bz_why

    out = []
    for d in merged.values():
        lanes_sorted = [l for l in _LANE_ORDER if l in d["lanes"]]
        d["lanes"] = lanes_sorted
        d["n_lanes"] = len(lanes_sorted)
        d["why"] = (d.get("bz_why") if "buyzone" in d["lanes"] else None) \
            or (_LANE_WHY.get(lanes_sorted[0], "momentum") if lanes_sorted else "momentum")
        out.append(d)
    # strongest signal first: most lanes, then biggest monthly move (Sanat's ranking).
    out.sort(key=lambda x: (x["n_lanes"], x["perf_m"] or -999), reverse=True)
    return out[:cap]


def strongest_list(market_key: str, limit: int = 30) -> list[dict]:
    """The strongest uptrending names in a market, each pre-classified buy/wait.
    Returns [] on any failure so the caller can fall back to a starter list."""
    p = _SCAN.get((market_key or "").strip().upper())
    if not p:
        return []
    try:
        from tradingview_screener import Query, col
    except Exception:  # noqa: BLE001  library missing -> caller falls back
        return []

    filters = [
        col("type") == "stock",
        col("typespecs").has(["common"]),                 # drop ETFs / preferreds / ADRs
        col("close") >= p["price_min"],
        col("market_cap_basic") >= p["mcap_min"],
        col("close") > col("SMA50"),                      # uptrend intact (medium-term)
        col("close") > col("SMA200"),                     # uptrend intact (long-term)
        col("Perf.6M") > p["perf6m"],                     # a real leader over 6 months
        col("Value.Traded") >= p["dollar_vol"],           # liquid only — kills micro-cap pumps
    ]
    if p["exchange"]:
        filters.append(col("exchange") == p["exchange"])

    try:
        _, df = (
            Query()
            .set_markets(p["market"])
            .select("name", "description", "close", "change", "SMA50",
                    "price_52_week_high", "market_cap_basic", "sector", "industry")
            # biggest, most-liquid strong names first (quality leaders, not the
            # highest spike, which is usually a low-quality pump).
            .order_by("market_cap_basic", ascending=False)
            .where(*filters)
            .limit(limit)
            .get_scanner_data()
        )
    except Exception:  # noqa: BLE001  field rename / network -> fall back
        return []
    if df is None or df.empty or "name" not in df:
        return []

    out = []
    for _, r in df.iterrows():
        try:
            close = float(r["close"])
            tag = _classify(close, float(r.get("SMA50") or 0), float(r.get("change") or 0),
                            float(r.get("price_52_week_high") or 0))
            out.append({
                "ticker": str(r["name"]),
                "name": str(r.get("description") or r["name"]),
                "market": market_key.strip().upper(),
                "price_str": f"{p['cur']}{round(close):,}",
                "tag": tag,
                "subline": _SUB[tag],
                "sector": str(r.get("sector") or "Other"),
                "industry": str(r.get("industry") or ""),
            })
        except Exception:  # noqa: BLE001  skip any malformed row
            continue
    return out
