"""plain_read.py — turn the JLaw data engine's numbers into a plain-English read.

This is the heart of Market Lens. It takes the feature bundle from
jlaw_data_core.screen() and produces a beginner-friendly read with three parts:

  verdict   — a one-line call + colour (green / amber / red)
  paragraph — why, in plain words (short sentences, common words)
  action    — ONE number to act on, shown as coloured above/below rules

No AI, no API key: this is deterministic rules over the engine's numbers, so it
runs free and instantly on the server. The rules mirror the tuned JLaw logic:
relative strength first, only buy at a low-risk edge (not extended / not chasing),
and for weak names give a clear "line in the sand" exit. Educational only.
"""

from __future__ import annotations


# --------------------------------------------------------------------------- helpers
def _sym(currency: str) -> str:
    return {"USD": "$", "INR": "₹", "GBP": "£", "GBp": "£", "EUR": "€"}.get(currency or "", "")


def _money(v, currency: str) -> str:
    """Plain price string. Whole units for normal prices, but 2 DECIMALS under 10 units —
    a £3.87 stock rounded to "£4" makes the buy and the exit collapse to the same number
    and hides ~15% of the real risk (audit #4, 2026-07-17; this is the same rule the
    frontend's fmtMoney already had — it was never ported here, so the two drifted).
    London (LSE) quotes come in PENCE (currency 'GBp'), so convert to pounds first."""
    if v is None or v != v:          # None or NaN
        return "—"
    if currency == "GBp":
        v = v / 100.0
    s = _sym(currency)
    return f"{s}{v:.2f}" if abs(v) < 10 else f"{s}{round(v):,}"


def _pct(v) -> str:
    return "—" if v is None else f"{round(v)}%"


def _g(d: dict, *path, default=None):
    """Safe nested get."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


# --------------------------------------------------------------------------- main
def build_plain_read(bundle: dict, news: dict | None = None) -> dict:
    """bundle = jlaw_data_core.screen(...) output. Returns the plain read dict.

    `news` (optional) = jlaw_data_core.news_sentiment(...) — a recent-news sentiment
    summary. When present with real data it FACTORS INTO the read: a pullback on bad
    news reads as likely real damage (lean wait), a fresh positive catalyst confirms an
    up-move (may be priced in). It does NOT change the price `tag` — that stays identical
    to what the many-name list computes (the list can't afford the API's tiny quota), so
    the list and the read never contradict; news adds a clearly-labelled 'News check'
    layer on top. None / no-data -> the price-only read stands (default, key-free)."""
    if not bundle or bundle.get("needs_disambiguation"):
        return {"ok": False,
                "error": "That name matched more than one stock. Try the exact ticker, "
                         "and pick a market (US / India / UK).",
                "candidates": bundle.get("candidates") if bundle else None}
    if not _g(bundle, "features"):
        return {"ok": False, "error": "Couldn't read that stock. Check the ticker and try again."}

    f = bundle["features"]
    name = (_g(bundle, "resolved", "name") or _g(bundle, "resolved", "symbol") or "This stock")
    name = name.split(" - ")[0].title() if name.isupper() else name.split(" - ")[0]
    symbol = _g(bundle, "resolved", "symbol", default="")
    currency = f.get("currency", "")
    price = f.get("last_close")
    pct_1d = f.get("pct_change_1d") or 0

    d_ma = _g(f, "daily", "moving_averages", default={})
    v_ma50 = _g(d_ma, "ma50", "price_vs_ma_pct")          # % price is above/below 50-day
    v_ma20 = _g(d_ma, "ma20", "price_vs_ma_pct")
    v_ma200 = _g(d_ma, "ma200", "price_vs_ma_pct")
    ma10 = _g(d_ma, "ma10", "value")
    ma20 = _g(d_ma, "ma20", "value")
    ma50v = _g(d_ma, "ma50", "value")
    ma200v = _g(d_ma, "ma200", "value")
    pct_from_high = _g(f, "fifty_two_week", "pct_from_high")   # negative = below high
    high_52w = _g(f, "fifty_two_week", "high")
    swing_low = _g(f, "daily", "swing", "swing_low")
    swing_high = _g(f, "daily", "swing", "swing_high")

    rs = _g(f, "relative_strength", default={})
    ex_1m = _g(rs, "stock_vs_index_1m", "excess_pct")
    ex_3m = _g(rs, "stock_vs_index_3m", "excess_pct")
    ex_6m = _g(rs, "stock_vs_index_6m", "excess_pct")
    stock_6m = _g(rs, "stock_vs_index_6m", "stock_pct")
    rs_falling = _g(rs, "rs_line_slope") == "falling"
    rs_rising = _g(rs, "rs_line_slope") == "rising"
    vol_ratio = _g(f, "daily", "volume", "ratio_vs_avg50")   # <1 = quieter than usual

    regime = _g(bundle, "broad_market", "regime", default="Neutral")

    # ---- signals (all best-effort; treat missing as neutral) ----
    above50 = (v_ma50 or 0) > 0
    above20 = (v_ma20 or 0) > 0
    # TRI-STATE (audit M4): a stock with < 200 bars of history has NO 200-day line, so
    # v_ma200 is None. Treating None as "below the 200-day" wrongly bars a young name from
    # the leader tier and forces the weak cell to the harsher red "avoid". Keep it None =
    # "unknown" and let the rules that care require `is False` / `is True` explicitly.
    above200 = None if v_ma200 is None else (v_ma200 > 0)
    # An ESTABLISHED leader must be ahead over 6 months by more than a rounding error
    # (> 2 pts, not > 0): a name ahead by +0.1% is statistical noise, and blind judges
    # + the screener's independent data source both read such names as EARLY turns,
    # not proven leaders (AMBA case, 2026-07-11). Hairline names fall to the emerging
    # tier, which fits them better (starter-size, higher-risk framing).
    strong_rs = (ex_3m or 0) > 0 and (ex_6m or 0) > 2
    # within 5% of the 1-year high. NOTE: `pct_from_high` is 0.0 for a stock AT its high,
    # and 0.0 is FALSY — an `(x or -99)` here would swallow it and read the single most
    # extended state as "not near its high" -> a GREEN buy at the exact top (audit #1,
    # 2026-07-17). Test for None explicitly; never let a meaningful 0 fall through an `or`.
    near_high = pct_from_high is not None and pct_from_high > -5
    just_popped = pct_1d > 4
    # the MIRROR of just_popped (added 2026-07-11, MDB case): a big DOWN day is
    # "mid-fall", not a calm entry — JLaw buys when it STEADIES. Same 4% bar the
    # screener's Early lane uses to exclude dumping names, so list and read agree.
    just_dumped = pct_1d < -4
    # THE READ'S MEMORY (2026-07-18, "give the app memory"). Two facts from the recent
    # past — see jlaw_data_core._trend_memory. worst_drop_3d covers TODAY's bar too, so
    # recent_shock is a strict superset of just_dumped: a >4% down day any time in the
    # last 3 sessions means this is not a calm spot yet (the NTAP case — its -7.1% shock
    # was one day back and the old 1-day gate read it green "leader resting").
    mem = _g(f, "daily", "trend_memory", default={}) or {}
    days_b50 = mem.get("days_below_50")
    worst3 = mem.get("worst_drop_3d")
    recent_shock = (worst3 is not None and worst3 < -4) or just_dumped
    weak_now = (not above20 and not above50) and ((ex_1m or 0) < 0 or rs_falling)
    # STRUCTURAL WEAK (added 2026-07-15, TEAM/CRM from the 15-Jul Midweek Pulse):
    # JLaw calls a name "weak structure" when it sits below its LONG-TERM trend
    # (the 200-day) and keeps losing to the market — even if a short bounce has
    # lifted it back above its 20-day, so the "below its 20 AND 50-day" gate above
    # misses it. Require below BOTH the 50- and 200-day + a falling RS line + a big
    # 6-month shortfall (ex_6m < -20) so this can ONLY fire on a genuinely broken
    # laggard: a real leader in a dip is always well ABOVE its 200-day and can never
    # trip it. Without this, TEAM/CRM (~20% below the 200-day, RS falling, 6-month
    # excess -47/-44) fell to "mixed" (no-edge) instead of weak.
    if (not above50 and above200 is False) and rs_falling and (ex_6m or 0) < -20:
        weak_now = True   # `is False` not `not above200` — an unknown 200-day (young name,
        #                   above200 is None) must NOT be assumed broken (audit M4)
    # RECLAIM WINDOW (2026-07-18): JLaw gives a name ~4-6 trading days below its 50-day
    # to climb back above. Past the window, unreclaimed = the market has answered — the
    # name reads firmly weak even if a bounce keeps its short-term signals mixed. (1-3
    # days below stays a soft "just slipped" wait — see _cell_reclaim.)
    if days_b50 is not None and days_b50 > 6:
        weak_now = True

    # "Extended" the JLaw way = stretched above the 50-day in ATR (volatility) terms,
    # NOT a flat % (READ_LOGIC: "JLaw measures 'extended' in ATR terms"). ONE graded
    # scale drives BOTH the verdict and the setup-check dot so they can never
    # contradict: > 4 ATRs above the 50-day = stretched (don't chase), > 7 = parabolic.
    # Flat-% fallback only when ATR is unavailable.
    atr14 = _g(f, "daily", "atr14")
    atrs_above_50 = ((price - ma50v) / atr14) if (atr14 and ma50v and price) else None
    extended = (atrs_above_50 > 4) if atrs_above_50 is not None else (v_ma50 or 0) > 12
    over_extended = atrs_above_50 is not None and atrs_above_50 > 7

    # DEEP FADE — a 6-month leader that is pulling back UN-healthily: its relative-strength
    # line has turned DOWN (it's lagging, not leading, during the dip), it's below its
    # short-term trend (20-day), and it's dropped a lot from its high. JLaw's "abnormal
    # pullback" test: a deep decline where the stock stops showing relative strength is NOT
    # a clean buyable dip — and a drop that big is often news-driven. Wait for it to steady
    # and reclaim before buying. (Fixes the NBIS-type "buy the dip" read the price engine
    # gives to a leader whose caution is really about a deep, RS-losing correction.)
    deep_fade = bool(rs_falling and not above20 and (pct_from_high or 0) < -18)

    # --------------------------------------------------------------- classify (MATRIX)
    # The verdict is a 2-AXIS MATRIX (refactor 2026-07-11 — same rules, safer shape):
    #   AXIS 1 — how strong is the stock (leadership tier), strongest signal first:
    #     weak     — below its 20 & 50-day and losing to the market (JLaw: relative
    #                weakness is the mirror of leadership)
    #     leader   — beating the market over 3 & 6 months, above its 200-day
    #     emerging — RS line turning up + reclaiming its trend (Stage 1->2), not yet
    #                a proven leader
    #     mixed    — none of the above: no edge, point the user at stronger names
    #   AXIS 2 — what price is doing right now (pullback health), worst state first:
    #     deep_fade — dropped >18% from its high, below the 20-day, RS falling
    #     sliding   — below the 20-day with RS falling, OR down >4% today (still going
    #                 down — a bounce day or being near its high must NOT override this)
    #     stretched — extended (>4 ATRs above the 50-day), near its 1-yr high, or
    #                 just popped >4% today (JLaw: never chase)
    #     resting   — calm: the low-risk spot JLaw actually buys
    # ONE cell = ONE complete package (tag + headline + paragraph + action + chart buy
    # line), built together in _CELLS below — so a "wait" headline can never sit above
    # a "buy now" action box. Future rule changes = edit a cell or move a boundary,
    # not a new elif whose position silently outranks the others.
    if weak_now:
        tier = "weak"
    elif strong_rs and above200:
        tier = "leader"
    elif rs_rising and (
            (above200 and ((ex_1m or 0) > 0 or (ex_3m or 0) > 0))
            or (above50 and above20)):
        # Two ways into "emerging": (a) an intact long uptrend (above the 200-day)
        # that's turning up and beating the market lately; or (b) an EARLY REPAIR that
        # reclaimed BOTH its 20- and 50-day lines with RS rising even while still below
        # the 200-day. Catches fresh-momentum / turnaround names (APP, NOW, FIG, HOOD)
        # that used to land on "not a clear leader".
        tier = "emerging"
    else:
        tier = "mixed"

    if deep_fade:
        phase = "deep_fade"
    elif (not above20 and rs_falling) or just_dumped:
        phase = "sliding"          # still going down (trend-sliding OR a >4% down day
        #                            TODAY — a bounce/near-high must not override this)
    elif not above50:
        # BELOW THE 50-DAY LINE — JLaw's core position-trade rule: below the 50-day, you
        # wait for it to RECLAIM before buying, whatever the RS line is doing (audit #2,
        # 2026-07-17). Without this, "resting" was a fall-through and a leader 10% below
        # its 50-day with RS rising read a GREEN "Looks buyable". "resting" (below) is now
        # only reachable when the stock is genuinely above its 50-day = a real calm spot.
        phase = "below_trend"
    elif extended or near_high or just_popped:
        phase = "stretched"
    elif recent_shock:
        # SHOCK GATE (2026-07-18, the NTAP case): a >4% down day within the LAST 3
        # sessions means this is not a calm resting spot yet, even if today's bar is
        # quiet — the old 1-day lookback read NTAP green the day after its -7.1% shock.
        # Checked AFTER stretched so a pop/near-high keeps the more specific "don't
        # chase" message (CHENNPETRO: +7% today after a -4% day must stay "don't chase").
        phase = "sliding"
    else:
        phase = "resting"          # calm AND above its 50-day = the low-risk spot to buy

    # tight starter-stop for EMERGING names: ~1.5x the stock's daily range below the entry.
    # JLaw sizes early entries small with a tight stop. NOTE (audit #5, 2026-07-17): this
    # used to be max(swing_low, price-1.5*ATR) — the MAX picks the TIGHTER of the two, so a
    # swing low only 0.5*ATR below price made the "tight" stop a coin-flip inside the daily
    # wobble and blew the reward:risk up (16.7:1). It's now a straight 1.5*ATR, and every
    # stop passes through _floored_stop below so risk can never fall inside ~1*ATR.
    tight_stop = round(price - 1.5 * atr14, 2) if (price and atr14) else None

    ctx = {"name": name, "price": price, "currency": currency, "regime": regime,
           "stock_6m": stock_6m, "ex_1m": ex_1m, "pct_1d": pct_1d,
           "near_high": near_high, "extended": extended, "above200": above200,
           "pct_from_high": pct_from_high, "swing_low": swing_low,
           "tight_stop": tight_stop, "atr14": atr14,
           "ma10": ma10, "ma20": ma20, "ma50": ma50v,
           "days_below_50": days_b50,
           # sliding entered ONLY because of an earlier-day shock (calm-ish today, trend
           # intact) -> the wording must say "just had a sharp drop", not "still falling".
           "shock_earlier": bool(recent_shock and not just_dumped
                                 and (above20 or not rs_falling))}
    cell = _CELLS[(tier, phase)](ctx)
    tag, color = cell["tag"], cell["color"]
    headline, subline = cell["headline"], cell["subline"]
    paragraph, buy_level, action = cell["paragraph"], cell["buy_level"], cell["action"]

    # MARKET GATE — in a Risk-Off market a fresh buy is a bad bet even on a great stock
    # (JLaw: don't fight the market). Downgrade ANY buy-now — established leader OR
    # emerging starter — to a wait. Headline, paragraph, action box and chart buy-line
    # all move TOGETHER here (fix 2026-07-11: the old gate rewrote only the headline,
    # leaving a "good spot to buy" action box under a "go slow" banner).
    riskoff_stop = _floored_stop(price, swing_low, atr14, min_atrs=0.0)
    if regime == "Risk-Off" and tag in ("buy", "emerging"):
        tag, color = "wait", "amber"
        headline = "Strong, but the market is weak"
        subline = "Good stock, risky time. Go slow."
        paragraph = _para_riskoff(name, stock_6m)
        buy_level = None
        action = _riskoff_action(riskoff_stop, currency)
        cell = {**cell, "stop": riskoff_stop}   # keep the one-source stop coherent

    # Pull-back zone + stacked supports — for leaders and emerging names (buy / wait /
    # emerging), where a dip to support is a place to act. Weak/avoid get an exit line.
    supports = None
    if tag in ("buy", "wait", "emerging"):
        supports = _supports(price, ma10, ma20, ma50v, ma200v, swing_low, currency)

    # News lens — factor recent sentiment into the guidance. A big recent bar means a
    # catalyst probably happened (recent_event_gaps), which sharpens the read.
    recent_gaps = _g(f, "daily", "recent_gaps", default=[]) or []
    big_move = any(abs(gp.get("gap_pct") or 0) >= 3 for gp in recent_gaps)
    news_lens = _news_lens(tag, news, big_move, name)

    # Chart signals — plain-language JLaw price-action edges from the last bar + gaps + RS.
    # Informational only; does NOT change the verdict.
    last_candle = _g(f, "daily", "last_candle", default={})
    signals = _patterns(last_candle, recent_gaps, above50, strong_rs, regime, pct_1d, tag,
                        vol_ratio)

    # effective TARGET (JLaw: the next ceiling overhead): the recent swing high when
    # it's meaningfully above; else the 1-YEAR high when THAT is meaningfully above —
    # an older ceiling is still the next objective (SMLMAH case, 2026-07-11: at the top
    # of its recent range but 29% below its yearly high, R:R was wrongly "unmeasurable");
    # else none (truly at its yearly high).
    if swing_high and price and swing_high > price * 1.02:
        eff_target, target_kind = swing_high, "recent"
    elif high_52w and price and high_52w > price * 1.02:
        eff_target, target_kind = high_52w, "year"
    else:
        eff_target, target_kind = None, None
    # the stop the numbers are judged against. It comes from the CHOSEN cell, which built
    # it to pair with its own buy_level and floored it below the entry (audit #3/#5/#6).
    # ONE source for lines.stop, the ladder and reward:risk, so they can never quote
    # different exits. Fallback only if a cell somehow left it unset.
    eff_stop = cell.get("stop")
    if eff_stop is None:
        eff_stop = _floored_stop(price, swing_low, atr14, min_atrs=0.0)

    # COHERENCE GUARD (user-caught 2026-07-15: LLY showed "Exit 1,115" INSIDE the
    # "Buy zone 1,079–1,172"). The zone and the stop are built by independent rules —
    # the zone floor can be a round number / deep support BELOW the exit (KVUE), and
    # the emerging tier's tight stop hangs off a buy-at-current-price entry (LLY,
    # HOOD). On one screen those numbers must agree: you can never be shown a dip-buy
    # level that sits below your own exit. Rule: clip the zone's floor up to the exit;
    # if the exit sits at/above the zone's ceiling, the dip zone isn't playable — drop
    # the zone (the ladder/chart then show just the exit). Blind invariant sweep
    # (scratchpad invariant_sweep.py, I1): 4/26 names violated before, 0 after.
    if supports and eff_stop is not None:
        z = supports["zone"]
        if eff_stop >= z["high"] * 0.995:
            supports = None
        elif eff_stop > z["low"]:
            z["low"] = eff_stop
            z["low_str"] = _money(eff_stop, currency)
            z["single"] = z["low_str"] == z["high_str"]

    return {
        "ok": True,
        "symbol": symbol,
        "name": name,
        "price": price,
        "price_str": _money(price, currency),
        "high_52w_str": _money(high_52w, currency) if high_52w else None,
        "currency": currency,
        "pct_1d": round(pct_1d, 1),
        "verdict": {"tag": tag, "color": color, "headline": headline, "subline": subline},
        "paragraph": paragraph,
        "action": action,
        "detail": _detail(currency, tag, over_extended, extended, vol_ratio, rs_rising,
                          ex_1m, ex_6m, pct_1d, price, eff_target, target_kind,
                          buy_level, eff_stop, atr=atr14,
                          live_vol=bool(_g(f, "daily", "volume", "live_adjusted")
                                        or _g(f, "daily", "volume", "session_adjusted"))),
        "supports": supports,
        "news": news_lens,
        "signals": signals,
        "freshness": _g(f, "freshness", default={}),
        "lines": {"swing_high": swing_high, "swing_low": swing_low, "buy": buy_level,
                  "target": eff_target, "stop": eff_stop},
    }


# --------------------------------------------------------------------------- the matrix
def _dip_below(price, ma10, ma20, ma50):
    """The dip-to-buy level must sit BELOW the current price — the nearest support
    beneath it (20-day, else 50-day, else 10-day, else ~3% down). Prevents nonsense
    like "wait for a dip to 282" when price is already 278."""
    return (ma20 if (ma20 and ma20 < price) else
            ma50 if (ma50 and ma50 < price) else
            ma10 if (ma10 and ma10 < price) else
            round(price * 0.97, 2))


def _dip_stop(dip, swing_low, atr14):
    """The exit for a DIP-BUY belongs BELOW the dip you're being told to buy. Normally
    the recent swing low IS below the dip, so use it. But when price has fallen below its
    20-day and the dip level falls back to the (far lower) 50-day, the swing low can sit
    ABOVE the dip — and pairing that as the exit tells the user to buy below their own
    stop (audit #3, 2026-07-17). In that case drop the exit to ~1.5x ATR below the dip so
    buy > exit always. For the normal case this returns the swing low unchanged (no
    regression)."""
    if swing_low is not None and dip is not None and swing_low < dip:
        return swing_low
    if dip is not None and atr14:
        return round(dip - 1.5 * atr14, 2)
    return round(dip * 0.97, 2) if dip is not None else swing_low


def _floored_stop(entry, structural, atr14, min_atrs=1.0):
    """A usable exit sits strictly BELOW the entry and — for a real risk figure — at least
    `min_atrs` x ATR away. A stop inside the stock's normal daily swing is noise, not a
    stop: it gets hit by chance and inflates reward:risk (audit #5/#6, 2026-07-17). Use the
    structural level (swing low / dip stop) when it's comfortably below; otherwise fall back
    to a ~1.5x-ATR volatility stop (also covers a fresh-low bar where the structural level
    sits at/above the entry). min_atrs=0 = "just below the entry" (the hold-line for wait
    names, where no position is being sized)."""
    if not entry:
        return structural
    if atr14:
        max_stop = entry - min_atrs * atr14          # closest a stop may sit to the entry
        if structural is not None and structural < max_stop:
            return structural
        return round(entry - max(min_atrs, 1.5) * atr14, 2)
    if structural is not None and structural < entry:
        return structural
    return round(entry * 0.97, 2)


def _cell(tag, color, headline, subline, paragraph, buy_level, action, stop=None):
    # `stop` = the exit that PAIRS with this cell's buy_level, reconciled so buy > stop.
    # build_plain_read reads it back for lines.stop / the ladder / reward:risk, so the
    # action prose, the chart lines and the R:R can never quote different exits (#3).
    return {"tag": tag, "color": color, "headline": headline, "subline": subline,
            "paragraph": paragraph, "buy_level": buy_level, "action": action, "stop": stop}


def _cell_leader_resting(c):
    stop = _floored_stop(c["price"], c["swing_low"], c["atr14"])
    return _cell("buy", "green", "Looks buyable",
                 "A leader, resting at a calmer spot.",
                 _para_buy(c["name"], c["stock_6m"], c["regime"]),
                 c["price"], _buy_now_action(c["price"], stop, c["currency"]),
                 stop=stop)


def _cell_leader_stretched(c):
    dip = _dip_below(c["price"], c["ma10"], c["ma20"], c["ma50"])
    stop = _floored_stop(dip, _dip_stop(dip, c["swing_low"], c["atr14"]), c["atr14"])
    return _cell("wait", "amber", "Strong — but don't chase it here",
                 "A real leader, but it has run up. Better to wait.",
                 _para_wait(c["name"], c["stock_6m"], c["pct_1d"], c["near_high"],
                            c["extended"], c["regime"]),
                 dip, _buy_dip_action(dip, stop, c["currency"]), stop=stop)


def _below_ma20(c) -> bool:
    """True only when we KNOW price is under its 20-day line (unknown -> False, so the
    prose never claims 'below its short-term line' without the number to back it)."""
    return (c.get("price") is not None and c.get("ma20") is not None
            and c["price"] < c["ma20"])


def _cell_leader_sliding(c):
    # Still SLIDING — below its short-term trend with RS fading, OR a >4% down day
    # TODAY. Not a calm "resting" pullback yet, so not a buy-NOW. JLaw: buy the dip
    # when it STEADIES / reclaims, don't catch it mid-fall. (Milder cousin of deep_fade.)
    stop = _floored_stop(c["price"], c["swing_low"], c["atr14"], min_atrs=0.0)
    subline = ("A leader, but it just had a sharp drop. Let it settle and turn back up first."
               if c.get("shock_earlier") else
               "A leader, but it's still falling right now. Let it settle and turn back up first.")
    return _cell("wait", "amber", "Pulling back — wait for it to steady",
                 subline,
                 _para_settle(c["name"], c["stock_6m"], c["regime"],
                              below_short=_below_ma20(c), lagging=(c["ex_1m"] or 0) < 0),
                 None, _steady_action(c["price"], stop, c["currency"]), stop=stop)


def _cell_reclaim(c):
    # BELOW its 50-day line but not actively sliding/deep-faded. JLaw's core rule: below
    # the 50-day, WAIT for it to reclaim before buying, whatever RS is doing (audit #2).
    stop = _floored_stop(c["price"], c["swing_low"], c["atr14"], min_atrs=0.0)
    d = c.get("days_below_50")
    if d is not None and 1 <= d <= 3:
        # RECLAIM WINDOW, early days (2026-07-18): a 1-3 day slip under the 50-day is
        # often reclaimed quickly — same wait verdict, softer read. Day 7+ never reaches
        # this cell (the reclaim-window rule routes it to the weak tier).
        headline = "Just slipped below its 50-day — give it a few days"
        subline = ("A short slip under the line, %s so far. These often get reclaimed "
                   "quickly — wait for it to climb back above before buying."
                   % ("1 day" if d == 1 else f"{d} days"))
    else:
        headline = "Below its 50-day line — wait for it to reclaim"
        subline = "It has slipped under its 50-day line. Wait for it to climb back above before buying."
    return _cell("wait", "amber", headline, subline,
                 _para_settle(c["name"], c["stock_6m"], c["regime"],
                              below_short=_below_ma20(c), lagging=(c["ex_1m"] or 0) < 0),
                 None, _reclaim_action(c["price"], stop, c["currency"]), stop=stop)


def _cell_emerging_shaky(c):
    # An early turn having a SHARP DOWN DAY (or, if the axes ever loosen, sliding) —
    # a starter-buy on a big red day would contradict "buy when it steadies".
    stop = _floored_stop(c["price"], c["swing_low"], c["atr14"], min_atrs=0.0)
    return _cell("wait", "amber", "Early turn — but let it settle first",
                 "Starting to turn up, but it's had a sharp down day. Wait for it to steady.",
                 _para_emerging(c["name"], c["stock_6m"], c["ex_1m"], c["regime"],
                                chased="it's had a sharp down day"),
                 None, _steady_action(c["price"], stop, c["currency"]), stop=stop)


def _cell_leader_deepfade(c):
    stop = _floored_stop(c["price"], c["swing_low"], c["atr14"], min_atrs=0.0)
    return _cell("wait", "amber", "Pulled back hard — let it steady first",
                 "A real leader, but it has dropped a lot and is losing its lead. Wait for it to turn back up.",
                 _para_broke(c["name"], c["stock_6m"], c["pct_from_high"], c["regime"]),
                 None, _steady_action(c["price"], stop, c["currency"]), stop=stop)


def _cell_emerging_starter(c):
    stop = _floored_stop(c["price"], c["tight_stop"] or c["swing_low"], c["atr14"])
    return _cell("emerging", "amber", "Early — just turning up",
                 "Reclaiming its trend and starting to beat the market. Early-stage, so higher risk.",
                 _para_emerging(c["name"], c["stock_6m"], c["ex_1m"], c["regime"], chased=False),
                 c["price"], _emerging_action(c["price"], stop, c["currency"]), stop=stop)


def _cell_emerging_chased(c):
    dip = _dip_below(c["price"], c["ma10"], c["ma20"], c["ma50"])
    stop = _floored_stop(dip, _dip_stop(dip, c["swing_low"], c["atr14"]), c["atr14"])
    # say WHY it's a chase — "the jump" wording on a name that never jumped (it was
    # merely near its highs) confused readers (audit finding, 2026-07-11).
    why = ("it just jumped" if (c["pct_1d"] or 0) > 4 else
           "it's right near its recent highs" if c["near_high"] else
           "it has run up quickly")
    return _cell("wait", "amber", "Gaining strength — but don't chase it here",
                 f"Turning up and beating the market lately, but {why}. Wait for a pullback.",
                 _para_emerging(c["name"], c["stock_6m"], c["ex_1m"], c["regime"], chased=why),
                 dip, _buy_dip_action(dip, stop, c["currency"]), stop=stop)


def _cell_weak(c):
    # A weak name that has steadied short-term (back above its 20-day AND not lagging the
    # market this month — the MSFT case) is still weak, but "it is falling right now" would
    # contradict the engine's own numbers. Verdict unchanged; only the tense is honest.
    falling_now = _below_ma20(c) or (c["ex_1m"] or 0) < 0
    if c["above200"] is False:
        # genuinely below its long-term (200-day) trend -> the harsher red "avoid".
        tag, color = "avoid", "red"
        headline = "Weak — best to avoid"
        subline = ("It is falling and lagging the market." if falling_now else
                   "It is far below its old levels and lagging the market.")
    else:
        # above the 200-day, OR unknown (young name, no 200-day yet — audit M4): the
        # softer amber "getting weaker", not red.
        tag, color = "weak", "amber"
        headline = "Getting weaker — not a good buy"
        subline = ("It was strong before. Now it is going down." if falling_now else
                   "It was strong before. It is still well below its old levels.")
    # the exit line must sit BELOW the current price — a weak name printing a fresh low
    # today would otherwise show an exit at/above price (audit #6). min_atrs=0: no position
    # is being sized here, so just keep it a real level strictly below.
    stop = _floored_stop(c["price"], c["swing_low"], c["atr14"], min_atrs=0.0)
    return _cell(tag, color, headline, subline,
                 _para_weak(c["name"], c["stock_6m"], c["ex_1m"], c["regime"],
                            falling_now=falling_now),
                 None, _exit_action(stop, c["currency"]), stop=stop)


def _cell_mixed(c):
    return _cell("wait", "amber", "Not a clear leader right now",
                 "Mixed signals. There are stronger names.",
                 _para_mixed(c["name"], c["regime"]),
                 None, {"type": "none",
                        "rows": [{"icon": "minus", "color": "muted",
                                  "text": "Nothing to do — there are stronger stocks to look at."}],
                        "note": ""}, stop=None)


# The verdict matrix: (tier, phase) -> one complete, internally-consistent package.
# NOTES on the collapsed rows:
#  - weak and mixed ignore the phase: a weak name gets the exit line whatever today's
#    bar did (a bounce in a weak trend is not a setup), and "no edge" needs no nuance.
#  - emerging × sliding / deep_fade are UNREACHABLE by construction (both phases
#    require a FALLING RS line; the emerging tier requires a RISING one). They map to
#    the starter cell so a future loosening of either axis fails safe (amber, small).
_CELLS = {
    ("leader", "resting"):       _cell_leader_resting,
    ("leader", "stretched"):     _cell_leader_stretched,
    ("leader", "below_trend"):   _cell_reclaim,
    ("leader", "sliding"):       _cell_leader_sliding,
    ("leader", "deep_fade"):     _cell_leader_deepfade,
    ("emerging", "resting"):     _cell_emerging_starter,
    ("emerging", "stretched"):   _cell_emerging_chased,
    ("emerging", "below_trend"): _cell_reclaim,
    ("emerging", "sliding"):     _cell_emerging_shaky,
    ("emerging", "deep_fade"):   _cell_emerging_shaky,
    ("weak", "resting"):         _cell_weak,
    ("weak", "stretched"):       _cell_weak,
    ("weak", "below_trend"):     _cell_weak,
    ("weak", "sliding"):         _cell_weak,
    ("weak", "deep_fade"):       _cell_weak,
    ("mixed", "resting"):        _cell_mixed,
    ("mixed", "stretched"):      _cell_mixed,
    ("mixed", "below_trend"):    _cell_mixed,
    ("mixed", "sliding"):        _cell_mixed,
    ("mixed", "deep_fade"):      _cell_mixed,
}


def _supports(price, ma10, ma20, ma50, ma200, swing_low, currency):
    """The pull-back zone: nearby supports BELOW the current price where buyers tend to
    step in — the moving-average lines + the recent low — clustered into a buy-on-dip
    band and listed one by one with their values (Sanat shows the stack, not one level).

    We keep only levels below the price (a support you've already broken above is where
    a dip could find footing), de-dup near-identical ones, then cluster the ones stacked
    together at the top into the zone; deeper levels are still listed. None if nothing
    sits below the price (rare for a leader — it would be at/under all its averages)."""
    cand = [("10-day line", ma10), ("20-day line", ma20), ("50-day line", ma50),
            ("200-day line", ma200), ("recent low", swing_low)]
    # the nearest ROUND NUMBER below the price — a level both beginners and big money
    # watch (the reference app showed e.g. "round number — 900" in its pull-back zone).
    if price and price > 0:
        step = 10 if price < 250 else (50 if price < 1000 else (100 if price < 5000 else 500))
        rn = int(price // step) * step
        if rn >= price:
            rn -= step
        if rn > 0:
            cand.append(("round number", float(rn)))
    below = [(lab, v) for lab, v in cand
             if v is not None and price is not None and 0 < v < price]
    if not below:
        return None
    below.sort(key=lambda x: x[1], reverse=True)          # nearest support first

    # drop levels within 0.5% of one already kept (same line twice) — keep the nearer.
    kept = []
    for lab, v in below:
        if not any(abs(v - pv) / price < 0.005 for _, pv in kept):
            kept.append((lab, v))
    below = kept

    # cluster the stacked supports at the top: each within ~6% of the previous one.
    cluster = [below[0]]
    for lab, v in below[1:]:
        if v >= cluster[-1][1] * 0.94:
            cluster.append((lab, v))
        else:
            break

    items = [{"label": lab, "value_str": _money(v, currency)} for lab, v in below]
    zone = {"low": cluster[-1][1], "high": cluster[0][1],
            "low_str": _money(cluster[-1][1], currency),
            "high_str": _money(cluster[0][1], currency),
            "single": len(cluster) == 1}
    return {"zone": zone, "items": items}


def _news_lens(tag, news, big_move, name):
    """Turn a recent-news sentiment score into a plain 'News check' that nudges what the
    reader should DO — the way the JLaw skill let news move the call. Returns None when
    there's no usable sentiment (no key / no coverage / neutral gap), so the price read
    just stands. Never changes `tag`; carries its own stance/colour for a separate banner.

      stance: caution  (news argues AGAINST the price read — lean wait)  -> amber/red
              confirm  (news SUPPORTS an up-move — looks real)           -> green
              reinforce(news CONFIRMS weakness — the fall has a reason)   -> red
              info     (news is mixed, or disagrees with a weak price)    -> grey
    """
    if not news or not news.get("have"):
        return None
    label, score = news.get("label", "mixed"), news.get("score", 0.0)
    neg = score <= -0.15
    pos = score >= 0.15
    gap_bit = " It also made a sharp move recently, so this is likely news-driven." if big_move else ""

    if tag in ("buy", "wait", "emerging") and neg:
        stance, color = "caution", "amber"
        text = (f"Recent news on {name} is {label}.{gap_bit} A dip on bad news can be real "
                f"damage, not a calm pullback — better to let it steady and prove itself "
                f"before buying, even though the price still looks strong.")
    elif tag in ("buy", "wait", "emerging") and pos:
        stance, color = "confirm", "green"
        priced = " Some of the good news may already be in the price." if tag == "wait" else ""
        text = (f"Recent news on {name} is {label}, which backs up the move — it looks real, "
                f"not just noise.{priced}")
    elif tag in ("weak", "avoid") and neg:
        stance, color = "reinforce", "red"
        text = (f"Recent news is {label} too — the weakness has a reason behind it, so treat "
                f"the fall as real, not a quick dip to buy.")
    elif tag in ("weak", "avoid") and pos:
        stance, color = "info", "muted"
        text = (f"Oddly, recent news is {label} even though the price is weak — the market "
                f"isn't buying the story yet. Wait for the price to actually turn up.")
    else:
        stance, color = "info", "muted"
        text = (f"Recent news is {label} — nothing that changes the read here; let the price "
                f"do the talking.")
    return {"have": True, "label": label, "score": score, "stance": stance,
            "color": color, "text": text}


def _patterns(last_candle, recent_gaps, above50, strong_rs, regime, pct_1d, tag,
              vol_ratio=None):
    """Plain-language 'chart signals' — the JLaw price-action edges the daily snapshot can
    compute UNAMBIGUOUSLY: the last bar's shape (long body / long tail), a recent gap
    (buyable-gap-up / gap-down), and relative strength while the market is soft. These are
    INFORMATIONAL and DO NOT change the verdict (like the News check) — they just tell the
    reader what the chart is doing. Two-candle patterns (engulfing) need the prior bar, which
    the snapshot doesn't expose, so they're intentionally left out. Returns at most 2, ranked.
    """
    lc = last_candle or {}
    body = lc.get("body_pct_of_range") or 0
    lw = lc.get("lower_wick_pct") or 0
    uw = lc.get("upper_wick_pct") or 0
    green = lc.get("color") == "green"
    p1 = pct_1d or 0
    out = []   # (priority, label, text, kind)

    # --- most recent meaningful gap ---
    if recent_gaps:
        g = recent_gaps[-1]
        gp = g.get("gap_pct") or 0
        when = g.get("date") or ""
        if g.get("dir") == "up" and gp >= 3 and above50 and tag not in ("weak", "avoid"):
            out.append((5, "Gapped up",
                        f"It jumped up ~{round(gp)}% recently and is holding above its 50-day line — a "
                        f"'buyable gap-up' style move (a classic entry edge). Big gaps are usually news, "
                        f"so check what drove it."))
        elif g.get("dir") == "down" and gp <= -3:
            out.append((5, "Gapped down",
                        f"It dropped ~{round(abs(gp))}% in one gap recently — usually news-driven; let it "
                        f"steady and check the reason before assuming a calm dip."))

    # --- relative strength while the market is only so-so / weak ---
    if regime in ("Neutral", "Risk-Off") and strong_rs and above50 and tag not in ("weak", "avoid"):
        out.append((4, "Holding up in a soft market",
                    "It's staying strong while the broader market is only so-so — that relative "
                    "strength is exactly what marks out a leader during a pullback."))

    # --- last-bar shape (pick the clearest one) ---
    # The big-body claims ("strong buying/heavy selling") need VOLUME behind them —
    # a wide bar on quiet volume is noise, and "heavy selling" next to the volume
    # check's own "quiet selling" contradicted itself (audit finding, 2026-07-11).
    quiet_vol = vol_ratio is not None and vol_ratio < 1.0
    if lw >= 45 and body <= 45:
        out.append((3, "Long lower tail",
                    "The last bar dipped but closed back near its high — buyers stepped in on the "
                    "weakness (a shakeout / reversal look)."))
    elif uw >= 45 and body <= 45:
        out.append((3, "Long upper tail",
                    "The last bar pushed up but got sold back down — sellers rejected the highs, so "
                    "don't chase it here."))
    elif body >= 65 and green and p1 > 0 and not quiet_vol:
        out.append((2, "Big green bar",
                    "A wide, full-bodied up day — strong buying and conviction behind the move."))
    elif body >= 65 and not green and p1 < 0 and not quiet_vol:
        out.append((2, "Big red bar",
                    "A wide, full-bodied down day — heavy selling; wait for it to steady before "
                    "trusting a bounce."))

    out.sort(key=lambda x: x[0], reverse=True)
    good = {"Gapped up", "Holding up in a soft market", "Long lower tail", "Big green bar"}
    return [{"label": lab, "text": txt, "kind": "good" if lab in good else "caution"}
            for _, lab, txt in out[:2]] or None


def _detail(currency, tag, over_extended, extended, vol_ratio, rs_rising, ex_1m, ex_6m,
            pct_1d, price, target_val, target_kind, buy_level, stop, atr=None,
            live_vol=False):
    """The read's inline detail: a target plus three plain 'setup' checks. Each check
    is THREE-STATE — good / watch / bad — not a pass/fail tick, because some factors
    (notably volume) are context-dependent, not simply good or bad.

    VOLUME is DIRECTION-AWARE (JLaw: volume only means something in the direction of
    the move). Heavy volume while price rises = buyers/conviction = GOOD (a breakout);
    heavy volume while price falls = sellers/distribution = BAD; a quiet dip = a calm,
    healthy pullback = GOOD. So heavy volume is only a warning when the stock is DOWN.
    """
    heavy = vol_ratio is not None and vol_ratio >= 1.3
    quiet = vol_ratio is not None and vol_ratio < 1.0
    d1 = (pct_1d or 0)
    up, down = d1 > 0, d1 < 0
    # live_vol: the ratio was time-adjusted ("vs the normal pace for this time of day") —
    # say so, it's the honest version of this check (Kite live OR the Yahoo session-adjust).
    tod = " for this time of day" if live_vol else ""

    # Same graded ATR scale as the verdict (4 = stretched, 7 = parabolic), so this dot
    # can never say "not over-extended" under a "don't chase — it has run up" verdict.
    if over_extended:
        c1 = {"state": "watch", "label": "Over-extended (parabolic) — risky"}
    elif extended:
        c1 = {"state": "watch", "label": "Stretched above its average — a dip is safer"}
    else:
        c1 = {"state": "good", "label": "Not over-extended"}

    if vol_ratio is None:
        # no honest volume reading yet (session barely open — audit H3). Don't imply "calm".
        c2 = {"state": "watch", "label": "Volume — no clear read yet today"}
    elif heavy and down:
        c2 = {"state": "bad", "label": f"Heavy selling{tod or ' right now'}"}
    elif heavy and up:
        c2 = {"state": "good", "label": f"Strong buying — heavy volume{tod}, price up"}
    elif heavy:
        # heavy volume on a FLAT close is churn with no direction — not "selling" (audit M3).
        c2 = {"state": "watch", "label": "Heavy volume, but the price went nowhere"}
    elif quiet and d1 < -4:
        # a >4% down day is not "calm" whatever the volume ratio says.
        c2 = {"state": "watch", "label": "Sharp down day — let it settle"}
    elif quiet:
        c2 = {"state": "good", "label": ("Selling is quiet for this time of day"
                                         if live_vol else "Calm pullback — quiet selling")}
    else:
        c2 = {"state": "good", "label": f"Trading is calm{tod}"}

    # Relative strength — judged over a MEANINGFUL horizon (6 months), not just the
    # RS line's recent wiggle, so it stays consistent with the "is it a leader?" verdict.
    # A laggard that's merely bouncing (RS up short-term but behind over 6 months, often
    # below its 200-day) is NOT "beating the market" — it's "lagging but turning up".
    ahead_6m = (ex_6m or 0) > 0
    improving = rs_rising or (ex_1m or 0) > 0
    if tag in ("weak", "avoid"):
        # a name we've called weak: describe the roll-over, don't flash green
        # "beating the market" off stale 6-month leadership.
        c3 = ({"state": "watch", "label": "Was a leader — now weakening"}
              if ahead_6m and (ex_1m or 0) >= 0
              else {"state": "bad", "label": "Falling behind the market"})
    elif ahead_6m:
        c3 = {"state": "good", "label": "Beating the market"}
    elif improving:
        c3 = {"state": "watch", "label": "Lagging — but turning up lately"}
    else:
        c3 = {"state": "bad", "label": "Falling behind the market"}

    if target_val:
        target = {"value_str": _money(target_val, currency),
                  "note": ("its recent high — room above" if target_kind == "recent"
                           else "its 1-year high — the next ceiling above")}
    else:
        target = {"value_str": None,
                  "note": "at its 1-year high — no ceiling above to measure against"}

    # Reward vs risk — the "is it worth getting in?" number. From the entry level
    # (buy zone), the stop (exit line) and the target (recent high):
    #   reward = target - entry,  risk = entry - stop,  ratio = reward / risk.
    # Only meaningful when there's a buy to size up (skip for weak/avoid).
    # entry = the buy level if there's a buy setup, else the current price (so any
    # non-weak stock still gets a reward:risk to judge). Skip only weak/avoid names.
    reward_risk = None
    entry = buy_level or (price if tag not in ("weak", "avoid") else None)
    if entry and stop and entry > stop:
        if target_val:
            # RISK FLOOR (2026-07-18, the LICI ₹1-risk case): a "not a clear leader"
            # page has no sized stop, so the ladder's exit falls back to the swing low —
            # which can hug the price (₹433 price / ₹432 exit → "16.7 to 1 — good").
            # Grade the reward against a risk of AT LEAST ~1 daily swing (same P8
            # principle the buy setups enforce), whatever line the ladder displays.
            risk = entry - stop
            if atr and risk < atr:
                risk = atr
            # threshold on the ROUNDED ratio the user actually sees: a raw 0.96 shows
            # as "1.0", and "1.0 — poor, you'd risk more than you could gain" reads
            # as a contradiction (audit finding, 2026-07-11).
            ratio = round((target_val - entry) / risk, 1)
            if ratio >= 2:
                st, note = "good", "good — you could gain more than you'd risk"
            elif ratio >= 1:
                st, note = "watch", "modest — the reward roughly matches the risk"
            else:
                st, note = "bad", "poor — you'd risk more than you could gain here"
            # HORIZON HONESTY (audit #5): when the target is the far 1-year high, the reward
            # is measured to a ceiling that may be months away while the risk is a near stop
            # — a big ratio here isn't a near-term promise. Say so rather than imply it.
            if target_kind == "year":
                note += " (measured to its 1-year high, which may be a way off)"
            reward_risk = {"ratio": ratio, "state": st, "note": note}
        else:
            reward_risk = {"ratio": None, "state": "watch",
                           "note": "can't be measured here — it's at its 1-year high, so there's no ceiling above to measure to"}

    return {"target": target, "checks": [c1, c2, c3], "reward_risk": reward_risk}


# --------------------------------------------------------------------------- paragraphs
def _market_phrase(regime: str) -> str:
    return {"Risk-On": "the market itself is healthy",
            "Neutral": "the market overall is just so-so",
            "Risk-Off": "the market overall is weak"}.get(regime, "the market is mixed")


def _six_phrase(stock_6m, default: str) -> str:
    """Sign-aware six-month phrase. A 'leader' is judged on EXCESS return, so in a down
    market a leader's own 6-month return can be negative — never print 'up about -12%'."""
    if not stock_6m:
        return default
    if stock_6m > 0:
        return f"up about {_pct(stock_6m)} in six months"
    return f"down about {_pct(abs(stock_6m))} in six months but holding up better than the market"


def _para_buy(name, stock_6m, regime):
    up = _six_phrase(stock_6m, "stronger than the market")
    return (f"{name} is one of the stronger stocks around — {up}, ahead of the market, and "
            f"{_market_phrase(regime)}. It has paused and pulled back to a calmer level, "
            f"which is a lower-risk spot to step in.")


def _para_riskoff(name, stock_6m):
    up = _six_phrase(stock_6m, "stronger than most stocks")
    return (f"{name} is {up} and holding up better than most — but the market overall is "
            f"weak right now, and most stocks fall when the market falls. Even a strong "
            f"stock is a risky buy in a weak market. Let the market steady first.")


def _para_wait(name, stock_6m, pct_1d, near_high, extended, regime):
    up = _six_phrase(stock_6m, "well ahead of the market")
    why = []
    if pct_1d > 4:
        why.append(f"today it jumped about {_pct(pct_1d)}")
    if near_high:
        why.append("it is close to its highest price in a year")
    if extended and not near_high:
        why.append("it has run up well above its recent average")
    tail = " and ".join(why) if why else "it has run up a lot"
    return (f"{name} is one of the stronger stocks around — {up}, and {_market_phrase(regime)}. "
            f"But {tail}. Buying right after a big run like this is risky.")


def _para_weak(name, stock_6m, ex_1m, regime, falling_now=True):
    # falling_now=False (fidelity fix 2026-07-18): a long-broken name that has steadied
    # short-term (above its 20-day, not lagging this month — the MSFT case) must not be
    # told "lately it has been falling more than the market"; the weakness is months-old.
    if not falling_now:
        return (f"{name} fell hard over the past months and is still well below the levels "
                f"it used to hold, lagging the market over the longer run. It has steadied "
                f"a little lately, but it has not won back the ground that matters. This is "
                f"real weakness, not a small dip.")
    return (f"{name} went up earlier, but lately it has been falling — and falling more than "
            f"the market. It is now below the levels it had been holding. This is real "
            f"weakness, not a small dip.")


def _para_mixed(name, regime):
    return (f"{name} is not clearly strong or clearly weak right now — the signals are mixed. "
            f"There are cleaner, stronger stocks to put your money and attention on.")


def _para_broke(name, stock_6m, pct_from_high, regime):
    dd = f"about {_pct(abs(pct_from_high))} below its high" if pct_from_high else "well off its high"
    return (f"{name} was a strong leader, but it has pulled back hard — {dd} — and it is now "
            f"lagging the market instead of leading it. A drop this deep is often driven by news. "
            f"Rather than buying the dip right away, it is safer to wait for it to stop falling and "
            f"turn back up first.")


def _para_settle(name, stock_6m, regime, below_short=True, lagging=True):
    up = _six_phrase(stock_6m, "a market leader")
    # Say only what the numbers show (fidelity fix 2026-07-18): the sliding phase can be
    # entered off a single sharp down day while the stock is still ABOVE its short-term
    # line and ahead of the market (the SEZL case) — don't assert clauses that aren't true.
    bits = []
    if below_short:
        bits.append("below its short-term line")
    if lagging:
        bits.append("slipping behind the market for the moment")
    middle = ("it's drifting lower, " + " and ".join(bits)) if bits \
        else "it's just had a sharp drop"
    return (f"{name} is {up} and still one of the stronger names — but right now {middle}. "
            f"That's not a calm, buyable pause yet. Better to wait for it to stop going down and "
            f"turn back up before stepping in.")


def _para_emerging(name, stock_6m, ex_1m, regime, chased):
    """chased = falsy (calm starter) or the WHY-string for the don't-chase variant."""
    lead = (f"{name} was lagging the market, but it has started to turn up — reclaiming its "
            f"trend and beating the market lately, with {_market_phrase(regime)}. This is an "
            f"early move: real, but not yet a proven leader, so it carries more risk.")
    tail = (f" But {chased}, so it's better to wait for a calmer spot than to chase."
            if chased else " If it keeps following through, it could become a new leader.")
    return lead + tail


# --------------------------------------------------------------------------- action boxes
def _buy_now_action(price, swing_low, currency):
    rows = [{"icon": "check", "color": "green",
             "text": f"Good spot to buy around {_money(price, currency)}."}]
    note = ""
    if swing_low:
        note = (f"Your exit line is {_money(swing_low, currency)} — "
                f"sell if it ends a day below that.")
    return {"type": "buy", "number": _money(price, currency), "rows": rows, "note": note}


def _emerging_action(price, swing_low, currency):
    rows = [{"icon": "check", "color": "amber",
             "text": f"An early setup — a small starter around {_money(price, currency)} is one way to play it."}]
    note = "Early-stage, so keep it small — it isn't a confirmed leader yet."
    if swing_low:
        note = (f"Keep it tight — exit line {_money(swing_low, currency)} (sell if it ends a day "
                f"below). Early-stage, so size small; it isn't a confirmed leader yet.")
    return {"type": "buy", "number": _money(price, currency), "rows": rows, "note": note}


def _riskoff_action(swing_low, currency):
    rows = [
        {"icon": "hand", "color": "amber",
         "text": "Right now → wait. The market itself is weak — a risky time for new buys."},
        {"icon": "up", "color": "green",
         "text": "Market steadies and this stock holds its level → then it's worth a look."},
    ]
    note = ""
    if swing_low:
        note = (f"Already own it? Your exit line is {_money(swing_low, currency)} — "
                f"sell if it ends a day below that.")
    return {"type": "wait", "number": None, "rows": rows, "note": note}


def _steady_action(price, swing_low, currency):
    rows = [
        {"icon": "hand", "color": "amber",
         "text": "Right now → wait. It has fallen hard; let it stop going down first."},
        {"icon": "up", "color": "green",
         "text": "Once it steadies and turns back up → that's a safer spot to buy."},
    ]
    note = ""
    if swing_low:
        note = (f"If you do step in, your exit line is {_money(swing_low, currency)} — "
                f"sell if it ends a day below that.")
    return {"type": "wait", "number": None, "rows": rows, "note": note}


def _reclaim_action(price, swing_low, currency):
    rows = [
        {"icon": "hand", "color": "amber",
         "text": "Right now → wait. It's under its 50-day line — not a buy yet."},
        {"icon": "up", "color": "green",
         "text": "Climbs back above its 50-day and holds → then it's worth a look."},
    ]
    note = ""
    if swing_low:
        note = (f"Already own it? Your exit line is {_money(swing_low, currency)} — "
                f"sell if it ends a day below that.")
    return {"type": "wait", "number": None, "rows": rows, "note": note}


def _buy_dip_action(dip_level, stop, currency):
    # `stop` is the reconciled dip-buy exit (below the dip), NOT the raw swing low (#3).
    rows = [
        {"icon": "hand", "color": "amber", "text": "Right now → wait. Don't chase the jump."},
        {"icon": "down", "color": "green",
         "text": f"Dips back to about {_money(dip_level, currency)} and steadies → good spot to buy."},
    ]
    note = ""
    if stop:
        note = (f"If you buy the dip, your exit line is {_money(stop, currency)} — "
                f"sell if it ends a day below that.")
    return {"type": "wait", "number": _money(dip_level, currency), "rows": rows, "note": note}


def _exit_action(swing_low, currency):
    line = _money(swing_low, currency)
    rows = [
        {"icon": "up", "color": "green", "text": f"Stays above {line} → keep it. A small drop is okay."},
        {"icon": "down", "color": "red", "text": f"Ends a day below {line} → sell it."},
    ]
    return {"type": "exit", "number": line, "rows": rows,
            "note": "Don't own it? Do nothing — just skip it for now."}
