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
    """Plain price string, rounded to whole units (beginners don't need paise/cents).
    London (LSE) quotes come in PENCE (currency 'GBp'), so convert to pounds."""
    if v is None or v != v:          # None or NaN
        return "—"
    if currency == "GBp":
        v = v / 100.0
    s = _sym(currency)
    return f"{s}{round(v):,}"


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
    above200 = (v_ma200 or 0) > 0
    strong_rs = (ex_3m or 0) > 0 and (ex_6m or 0) > 0           # beating the market 3m & 6m
    near_high = (pct_from_high or -99) > -5                    # within 5% of the 1-year high
    just_popped = pct_1d > 4
    weak_now = (not above20 and not above50) and ((ex_1m or 0) < 0 or rs_falling)

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

    # --------------------------------------------------------------- classify
    buy_level = None   # the price level the detail "buy it if…" line refers to
    if weak_now:
        if above200:
            tag, color = "weak", "amber"
            headline = "Getting weaker — not a good buy"
            subline = "It was strong before. Now it is going down."
        else:
            tag, color = "avoid", "red"
            headline = "Weak — best to avoid"
            subline = "It is falling and lagging the market."
        paragraph = _para_weak(name, stock_6m, ex_1m, regime)
        action = _exit_action(swing_low, currency)

    elif strong_rs and above200:
        if deep_fade:
            tag, color = "wait", "amber"
            headline = "Pulled back hard — let it steady first"
            subline = "A real leader, but it has dropped a lot and is losing its lead. Wait for it to turn back up."
            paragraph = _para_broke(name, stock_6m, pct_from_high, regime)
            buy_level = None
            action = _steady_action(price, swing_low, currency)
        elif not above20 and rs_falling:
            # A leader that is still SLIDING below its short-term trend (below the 20-day) with
            # its RS line fading — not a calm, "resting" pullback yet, so not a buy-NOW. JLaw:
            # buy the dip when it STEADIES / reclaims, don't catch it mid-fall. (Milder cousin of
            # deep_fade — the drawdown isn't deep, but it hasn't stopped going down.)
            # Checked BEFORE the don't-chase branch: a one-day +4% bounce (just_popped) or
            # being near its high must NOT flip a still-sliding leader back to "buy the dip".
            tag, color = "wait", "amber"
            headline = "Pulling back — wait for it to steady"
            subline = "A leader, but it's still sliding below its short-term line. Let it settle and turn back up first."
            paragraph = _para_settle(name, stock_6m, regime)
            buy_level = None
            action = _steady_action(price, swing_low, currency)
        elif extended or near_high or just_popped:
            tag, color = "wait", "amber"
            headline = "Strong — but don't chase it here"
            subline = "A real leader, but it has run up. Better to wait."
            paragraph = _para_wait(name, stock_6m, pct_1d, near_high, extended, regime)
            # the dip-to-buy level must sit BELOW the current price — the nearest
            # support beneath it (20-day, else 50-day, else 10-day, else ~3% down).
            # Prevents nonsense like "wait for a dip to 282" when price is already 278.
            dip = (ma20 if (ma20 and ma20 < price) else
                   ma50v if (ma50v and ma50v < price) else
                   ma10 if (ma10 and ma10 < price) else
                   round(price * 0.97, 2))
            buy_level = dip
            action = _buy_dip_action(dip, swing_low, currency)
        else:
            tag, color = "buy", "green"
            headline = "Looks buyable"
            subline = "A leader, resting at a calmer spot."
            paragraph = _para_buy(name, stock_6m, regime)
            buy_level = price
            action = _buy_now_action(price, swing_low, currency)

    elif rs_rising and (
            (above200 and ((ex_1m or 0) > 0 or (ex_3m or 0) > 0))
            or (above50 and above20)):
        # EMERGING / gaining strength (JLaw's "early leader / just turning up"): the RS
        # line is turning UP and the stock is reclaiming its trend — but it is NOT yet an
        # established 3-&-6-month leader. A real move, but earlier-stage and higher risk.
        # Two ways in: (a) an intact long uptrend (above the 200-day) that's turning up, or
        # (b) an EARLY REPAIR that has reclaimed BOTH its 20- and 50-day lines with RS
        # rising even while still below the 200-day (Stage 1->2 turnaround). This is the
        # read that used to wrongly land on "not a clear leader" for fresh momentum /
        # turnaround names (APP, NOW, FIG, HOOD, etc.) that just reclaimed their trend.
        if extended or near_high or just_popped:
            tag, color = "wait", "amber"
            headline = "Gaining strength — but don't chase the jump"
            subline = "Turning up and beating the market lately, but it just ran. Wait for a pullback."
            paragraph = _para_emerging(name, stock_6m, ex_1m, regime, chased=True)
            dip = (ma20 if (ma20 and ma20 < price) else
                   ma50v if (ma50v and ma50v < price) else
                   ma10 if (ma10 and ma10 < price) else
                   round(price * 0.97, 2))
            buy_level = dip
            action = _buy_dip_action(dip, swing_low, currency)
        else:
            tag, color = "emerging", "amber"
            headline = "Early — just turning up"
            subline = "Reclaiming its trend and starting to beat the market. Early-stage, so higher risk."
            paragraph = _para_emerging(name, stock_6m, ex_1m, regime, chased=False)
            buy_level = price
            action = _emerging_action(price, swing_low, currency)

    else:
        tag, color = "wait", "amber"
        headline = "Not a clear leader right now"
        subline = "Mixed signals. There are stronger names."
        paragraph = _para_mixed(name, regime)
        action = {"type": "none",
                  "rows": [{"icon": "minus", "color": "muted",
                            "text": "Nothing to do — there are stronger stocks to look at."}],
                  "note": ""}

    # MARKET GATE — in a Risk-Off market a fresh buy is a bad bet even on a great stock
    # (JLaw: don't fight the market). Downgrade ANY buy-now — established leader OR
    # emerging starter — to a wait. Headline, paragraph, action box and chart buy-line
    # all move TOGETHER here (fix 2026-07-11: the old gate rewrote only the headline,
    # leaving a "good spot to buy" action box under a "go slow" banner).
    if regime == "Risk-Off" and tag in ("buy", "emerging"):
        tag, color = "wait", "amber"
        headline = "Strong, but the market is weak"
        subline = "Good stock, risky time. Go slow."
        paragraph = _para_riskoff(name, stock_6m)
        buy_level = None
        action = _riskoff_action(swing_low, currency)

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
    signals = _patterns(last_candle, recent_gaps, above50, strong_rs, regime, pct_1d, tag)

    return {
        "ok": True,
        "symbol": symbol,
        "name": name,
        "price": price,
        "price_str": _money(price, currency),
        "currency": currency,
        "pct_1d": round(pct_1d, 1),
        "verdict": {"tag": tag, "color": color, "headline": headline, "subline": subline},
        "paragraph": paragraph,
        "action": action,
        "detail": _detail(currency, tag, over_extended, extended, vol_ratio, rs_rising,
                          ex_1m, ex_6m, pct_1d, price, swing_high, buy_level, swing_low),
        "supports": supports,
        "news": news_lens,
        "signals": signals,
        "lines": {"swing_high": swing_high, "swing_low": swing_low, "buy": buy_level},
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
    zone = {"low_str": _money(cluster[-1][1], currency),
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


def _patterns(last_candle, recent_gaps, above50, strong_rs, regime, pct_1d, tag):
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
                        f"'buyable gap-up' style move (a JLaw entry edge). Big gaps are usually news, "
                        f"so check what drove it."))
        elif g.get("dir") == "down" and gp <= -3:
            out.append((5, "Gapped down",
                        f"It dropped ~{round(abs(gp))}% in one gap recently — usually news-driven; let it "
                        f"steady and check the reason before assuming a calm dip."))

    # --- relative strength while the market is only so-so / weak ---
    if regime in ("Neutral", "Risk-Off") and strong_rs and above50 and tag not in ("weak", "avoid"):
        out.append((4, "Holding up in a soft market",
                    "It's staying strong while the broader market is only so-so — that relative "
                    "strength is exactly what JLaw looks for during a pullback."))

    # --- last-bar shape (pick the clearest one) ---
    if lw >= 45 and body <= 45:
        out.append((3, "Long lower tail",
                    "The last bar dipped but closed back near its high — buyers stepped in on the "
                    "weakness (a shakeout / reversal look)."))
    elif uw >= 45 and body <= 45:
        out.append((3, "Long upper tail",
                    "The last bar pushed up but got sold back down — sellers rejected the highs, so "
                    "don't chase it here."))
    elif body >= 65 and green and p1 > 0:
        out.append((2, "Big green bar",
                    "A wide, full-bodied up day — strong buying and conviction behind the move."))
    elif body >= 65 and not green and p1 < 0:
        out.append((2, "Big red bar",
                    "A wide, full-bodied down day — heavy selling; wait for it to steady before "
                    "trusting a bounce."))

    out.sort(key=lambda x: x[0], reverse=True)
    good = {"Gapped up", "Holding up in a soft market", "Long lower tail", "Big green bar"}
    return [{"label": lab, "text": txt, "kind": "good" if lab in good else "caution"}
            for _, lab, txt in out[:2]] or None


def _detail(currency, tag, over_extended, extended, vol_ratio, rs_rising, ex_1m, ex_6m,
            pct_1d, price, swing_high, buy_level, stop):
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
    up = (pct_1d or 0) > 0

    # Same graded ATR scale as the verdict (4 = stretched, 7 = parabolic), so this dot
    # can never say "not over-extended" under a "don't chase — it has run up" verdict.
    if over_extended:
        c1 = {"state": "watch", "label": "Over-extended (parabolic) — risky"}
    elif extended:
        c1 = {"state": "watch", "label": "Stretched above its average — a dip is safer"}
    else:
        c1 = {"state": "good", "label": "Not over-extended"}

    if heavy and not up:
        c2 = {"state": "bad", "label": "Heavy selling right now"}
    elif heavy and up:
        c2 = {"state": "good", "label": "Strong buying — heavy volume, price up"}
    elif quiet:
        c2 = {"state": "good", "label": "Calm pullback — quiet selling"}
    else:
        c2 = {"state": "good", "label": "Trading is calm"}

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

    if swing_high and price and swing_high > price * 1.02:
        target = {"value_str": _money(swing_high, currency), "note": "its recent high — room above"}
    else:
        target = {"value_str": None,
                  "note": "already near its 1-year high — limited room above right now"}

    # Reward vs risk — the "is it worth getting in?" number. From the entry level
    # (buy zone), the stop (safety line) and the target (recent high):
    #   reward = target - entry,  risk = entry - stop,  ratio = reward / risk.
    # Only meaningful when there's a buy to size up (skip for weak/avoid).
    # entry = the buy level if there's a buy setup, else the current price (so any
    # non-weak stock still gets a reward:risk to judge). Skip only weak/avoid names.
    reward_risk = None
    entry = buy_level or (price if tag not in ("weak", "avoid") else None)
    if entry and stop and entry > stop:
        # only define a ratio if there's real room above the CURRENT price — matches
        # the "Where it could go" box (avoids "no room above" + a positive ratio).
        if swing_high and price and swing_high > price * 1.02:
            ratio = (swing_high - entry) / (entry - stop)
            if ratio >= 2:
                st, note = "good", "good — you could gain more than you'd risk"
            elif ratio >= 1:
                st, note = "watch", "modest — the reward roughly matches the risk"
            else:
                st, note = "bad", "poor — you'd risk more than you could gain here"
            reward_risk = {"ratio": round(ratio, 1), "state": st, "note": note}
        else:
            reward_risk = {"ratio": None, "state": "watch",
                           "note": "can't be measured here — it's near its high, so there's no target above to measure against"}

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


def _para_weak(name, stock_6m, ex_1m, regime):
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


def _para_settle(name, stock_6m, regime):
    up = _six_phrase(stock_6m, "a market leader")
    return (f"{name} is {up} and still one of the stronger names — but right now it's drifting "
            f"lower, below its short-term line, and slipping behind the market for the moment. "
            f"That's not a calm, buyable pause yet. Better to wait for it to stop going down and "
            f"turn back up before stepping in.")


def _para_emerging(name, stock_6m, ex_1m, regime, chased):
    lead = (f"{name} was lagging the market, but it has started to turn up — reclaiming its "
            f"trend and beating the market lately, with {_market_phrase(regime)}. This is an "
            f"early move: real, but not yet a proven leader, so it carries more risk.")
    tail = (" It just jumped, though, so it's better to wait for it to settle than to chase."
            if chased else " If it keeps following through, it could become a new leader.")
    return lead + tail


# --------------------------------------------------------------------------- action boxes
def _buy_now_action(price, swing_low, currency):
    rows = [{"icon": "check", "color": "green",
             "text": f"Good spot to buy around {_money(price, currency)}."}]
    note = ""
    if swing_low:
        note = (f"Your safety line is {_money(swing_low, currency)} — "
                f"sell if it ends a day below that.")
    return {"type": "buy", "number": _money(price, currency), "rows": rows, "note": note}


def _emerging_action(price, swing_low, currency):
    rows = [{"icon": "check", "color": "amber",
             "text": f"An early setup — a small starter around {_money(price, currency)} is one way to play it."}]
    note = "Early-stage, so keep it small — it isn't a confirmed leader yet."
    if swing_low:
        note = (f"Keep it tight — safety line {_money(swing_low, currency)} (sell if it ends a day "
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
        note = (f"Already own it? Your safety line is {_money(swing_low, currency)} — "
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
        note = (f"If you do step in, your safety line is {_money(swing_low, currency)} — "
                f"sell if it ends a day below that.")
    return {"type": "wait", "number": None, "rows": rows, "note": note}


def _buy_dip_action(dip_level, swing_low, currency):
    rows = [
        {"icon": "hand", "color": "amber", "text": "Right now → wait. Don't chase the jump."},
        {"icon": "down", "color": "green",
         "text": f"Dips back to about {_money(dip_level, currency)} and steadies → good spot to buy."},
    ]
    note = ""
    if swing_low:
        note = (f"If you buy, your safety line is {_money(swing_low, currency)} — "
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
