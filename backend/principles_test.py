# -*- coding: utf-8 -*-
"""PRINCIPLES TEST — JLaw's rules written as hard assertions over synthetic reads.
Run after ANY engine change: `python backend/principles_test.py` (exit 1 = a rule
broke, and it names the stock + rule). This is the loud safety net: it makes it
impossible to silently undo one fix while making another.

Rules asserted (each maps to an audit finding or a JLaw principle):
  P1  never GREEN ("buy") when the stock is AT/above its 52-week high      (#1)
  P2  never GREEN ("buy") when the stock is below its 50-day line          (#2, JLaw core)
  P3  the buy level is ALWAYS above the exit line                          (#3)
  P4  a weak/avoid name NEVER shows a buy zone                             (coherence)
  P5  the exit is always below the current price                          (coherence)
  P6  reward:risk, when shown, is positive and its label matches its value (coherence)
  P7  a displayed price string never contains NaN/None                     (data hygiene)
  P8  a BUY setup's risk (entry-exit) is >= ~1x the daily swing (ATR)       (#5/#6)
  P10 never GREEN ("buy") within 3 sessions of a >4% down day     (NTAP, 17-Jul article)
  P11 >6 days below the 50-day unreclaimed reads weak/avoid; a 1-3 day slip
      does NOT read weak                                    (reclaim window, 2026-07-18)
  P12 R:R is never graded off a risk smaller than ~1x ATR, even on watch-line
      exits with no buy setup                          (LICI 16.7:1 case, 2026-07-18)
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.plain_read import build_plain_read


def bundle(*, price, ma10, ma20, ma50, ma200, swing_low, swing_high, high_52w,
           rs="rising", ex1=5.0, ex3=20.0, ex6=40.0, pct1d=0.5, atr=2.0,
           currency="USD", vol=0.9, regime="Neutral",
           days_below_50=None, worst3=None):
    pv = lambda m: round((price / m - 1) * 100, 2) if m else None
    return {
        "resolved": {"name": "Test Co", "symbol": "TEST"},
        "broad_market": {"regime": regime},
        "features": {
            "currency": currency, "last_close": price, "pct_change_1d": pct1d,
            "fifty_two_week": {"high": high_52w, "low": price * 0.4,
                               "pct_from_high": round((price / high_52w - 1) * 100, 2)},
            "daily": {
                "moving_averages": {
                    "ma10": {"value": ma10, "price_vs_ma_pct": pv(ma10), "slope": "rising"},
                    "ma20": {"value": ma20, "price_vs_ma_pct": pv(ma20), "slope": "rising"},
                    "ma50": {"value": ma50, "price_vs_ma_pct": pv(ma50), "slope": "rising"},
                    "ma200": {"value": ma200, "price_vs_ma_pct": pv(ma200), "slope": "rising"}},
                "atr14": atr, "ma_stack": "mixed",
                "swing": {"swing_low": swing_low, "swing_high": swing_high},
                "volume": {"ratio_vs_avg50": vol}, "recent_gaps": [],
                "trend_memory": {"days_below_50": days_below_50,
                                 "worst_drop_3d": worst3},
                "last_candle": {"color": "green", "body_pct_of_range": 40,
                                "upper_wick_pct": 30, "lower_wick_pct": 30}},
            "relative_strength": {
                "rs_line_slope": rs,
                "stock_vs_index_1m": {"excess_pct": ex1, "stock_pct": ex1},
                "stock_vs_index_3m": {"excess_pct": ex3, "stock_pct": ex3},
                "stock_vs_index_6m": {"excess_pct": ex6, "stock_pct": ex6}},
        }}


def num(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").lstrip("$₹£€").strip())
    except Exception:
        return None


# A grid of scenarios spanning every tier × position. Each is (label, bundle-kwargs).
def grid():
    P = 100.0
    S = []
    # leaders at various positions vs the 52w high (P1/P2 territory)
    for off in (0.0, -0.4, -2.0, -4.9, -8.0, -15.0, -25.0):
        hi = P / (1 + off / 100.0)
        S.append((f"leader off-high {off}%",
                  dict(price=P, ma10=P*0.99, ma20=P*0.98, ma50=P*0.95, ma200=P*0.8,
                       swing_low=P*0.96, swing_high=hi, high_52w=hi,
                       rs="rising", ex1=5, ex3=20, ex6=40, atr=2.0, pct1d=0.5)))
    # leader BELOW its 50-day, RS rising (the #2 case) at several depths
    for below in (2.0, 5.0, 10.0, 18.0):
        S.append((f"leader {below}% below 50-day, RS rising",
                  dict(price=P, ma10=P*1.01, ma20=P*1.02, ma50=P*(1+below/100),
                       ma200=P*0.75, swing_low=P*0.94, swing_high=P*1.25, high_52w=P*1.25,
                       rs="rising", ex1=2, ex3=20, ex6=40, atr=2.0, pct1d=0.5)))
    # emerging below its 50-day (early turn not yet reclaimed)
    S.append(("emerging below 50-day (above 200, RS rising)",
              dict(price=P, ma10=P*1.01, ma20=P*1.02, ma50=P*1.05, ma200=P*0.9,
                   swing_low=P*0.95, swing_high=P*1.3, high_52w=P*1.3,
                   rs="rising", ex1=3, ex3=5, ex6=1, atr=2.0)))
    # stretched leader below its 20-day (the #3 dip-below-stop case)
    S.append(("stretched leader, price under 20-day, ma50 far below",
              dict(price=88.0, ma10=89, ma20=90.0, ma50=75.0, ma200=60.0,
                   swing_low=82.0, swing_high=91.0, high_52w=95.0, atr=2.0,
                   rs="rising", ex1=5, ex3=20, ex6=40)))
    # low-priced stock (the #4 decimals case)
    S.append(("low-priced $3.47 buyable",
              dict(price=3.47, ma10=3.4, ma20=3.3, ma50=3.1, ma200=2.5,
                   swing_low=3.02, swing_high=4.2, high_52w=4.3, atr=0.12,
                   rs="rising", ex1=5, ex3=20, ex6=40)))
    S.append(("LSE 387p buyable (GBp)",
              dict(price=387.0, ma10=380, ma20=375, ma50=360, ma200=300,
                   swing_low=361.0, swing_high=420.0, high_52w=430.0, currency="GBp",
                   atr=8.0, rs="rising", ex1=5, ex3=20, ex6=40)))
    # structural weak (buy-zone must be absent)
    S.append(("structural weak (below 50 & 200, RS falling, ex6 -47)",
              dict(price=90.0, ma10=92, ma20=95, ma50=100.0, ma200=113.0,
                   swing_low=85.0, swing_high=120.0, high_52w=140.0,
                   rs="falling", ex1=-2, ex3=35, ex6=-47, atr=2.0)))
    # emerging starter (valid: reclaimed 20 & 50, RS rising) — must stay buyable
    S.append(("valid emerging starter (above 20 & 50, RS rising, below 200)",
              dict(price=100.0, ma10=99, ma20=98, ma50=97, ma200=110.0,
                   swing_low=96.0, swing_high=112.0, high_52w=120.0,
                   rs="rising", ex1=3, ex3=6, ex6=2, atr=2.0)))
    # healthy resting leader (dipped to 20-day, above 50) — must stay buyable
    S.append(("healthy leader resting on 20-day (above 50)",
              dict(price=100.0, ma10=101, ma20=100.5, ma50=94, ma200=80.0,
                   swing_low=97.0, swing_high=112.0, high_52w=112.0,
                   rs="rising", ex1=5, ex3=20, ex6=40, atr=2.0, pct1d=0.5)))
    # M4: a YOUNG name (< 200 bars -> no 200-day line, ma200=None) that is weak must read
    # amber "weak", NOT red "avoid" — we don't KNOW it's below its long-term trend.
    S.append(("young weak (no 200-day, below 50 & 20, RS falling, ex6 -30)",
              dict(price=100.0, ma10=102, ma20=103, ma50=105, ma200=None,
                   swing_low=94.0, swing_high=120.0, high_52w=120.0,
                   rs="falling", ex1=-3, ex3=-10, ex6=-30, atr=2.0)))
    S.append(("young strong (no 200-day, above 50 & 20, RS rising)",
              dict(price=100.0, ma10=99, ma20=98, ma50=96, ma200=None,
                   swing_low=95.0, swing_high=115.0, high_52w=115.0,
                   rs="rising", ex1=3, ex3=15, ex6=30, atr=2.0)))
    # P10: the NTAP case — a textbook resting leader TODAY, but a -7% shock 2 days ago.
    S.append(("resting leader with a -7% day 2 sessions back (P10 shock gate)",
              dict(price=100.0, ma10=101, ma20=100.5, ma50=94, ma200=80.0,
                   swing_low=97.0, swing_high=112.0, high_52w=120.0,
                   rs="rising", ex1=5, ex3=20, ex6=40, atr=2.0, pct1d=-1.5,
                   worst3=-7.1)))
    # P11: reclaim window — day 8 below the 50-day = firmly weak; day 2 = soft wait.
    S.append(("leader 8 days below its 50-day, unreclaimed (P11 firm)",
              dict(price=100.0, ma10=100.5, ma20=101.0, ma50=104.0, ma200=90.0,
                   swing_low=94.0, swing_high=120.0, high_52w=125.0,
                   rs="rising", ex1=1, ex3=15, ex6=30, atr=2.0, pct1d=0.3,
                   days_below_50=8, worst3=-1.5)))
    S.append(("leader 2 days below its 50-day (P11 soft slip, must stay wait)",
              dict(price=100.0, ma10=100.5, ma20=101.0, ma50=102.0, ma200=85.0,
                   swing_low=95.0, swing_high=118.0, high_52w=122.0,
                   rs="rising", ex1=2, ex3=18, ex6=35, atr=2.0, pct1d=0.3,
                   days_below_50=2, worst3=-1.8)))
    # P12: the LICI case — a mixed name whose swing low HUGS the price. The naive
    # ratio is (110-100)/0.3 = 33:1 "good"; the ATR floor grades it (110-100)/2 = 5.
    S.append(("mixed name, swing low 0.3 below price (P12 R:R risk floor)",
              dict(price=100.0, ma10=95.0, ma20=94.0, ma50=92.0, ma200=85.0,
                   swing_low=99.7, swing_high=110.0, high_52w=115.0,
                   rs="falling", ex1=-1, ex3=-1, ex6=1, atr=2.0, pct1d=0.2)))
    return S


fails = []
buys_seen = 0
for label, kw in grid():
    r = build_plain_read(bundle(**kw))
    v = r.get("verdict") or {}
    tag = v.get("tag")
    L = r.get("lines") or {}
    dt = r.get("detail") or {}
    sp = r.get("supports") or {}
    price = r.get("price")
    hi = kw["high_52w"]
    stop, buy = L.get("stop"), L.get("buy")
    rr = dt.get("reward_risk") or {}

    def fail(rule, msg):
        fails.append((label, rule, msg))

    if tag == "buy":
        buys_seen += 1
        # P1 — never buy at/above the 52w high
        if price >= hi * 0.999:
            fail("P1", f"BUY at/above 52w high (price {price} vs high {hi})")
        # P2 — never buy below the 50-day
        ma50 = kw["ma50"]
        if ma50 and price < ma50:
            fail("P2", f"BUY below the 50-day (price {price} vs ma50 {ma50})")
    # P3 — buy must be above exit
    if buy is not None and stop is not None and buy <= stop:
        fail("P3", f"buy {buy} <= exit {stop}")
    # P8 — a BUY setup's risk must be >= ~1x ATR (no coin-flip stop inside the wobble)
    if buy is not None and stop is not None:
        atr = kw.get("atr")
        if atr and (buy - stop) < 0.9 * atr:
            fail("P8", f"risk {round(buy-stop,2)} < ~1x ATR ({atr}) — stop inside the daily swing")
    # P4 — weak/avoid never shows a buy zone
    if tag in ("weak", "avoid") and sp.get("zone"):
        fail("P4", "weak/avoid shows a buy zone")
    # P9 — a young name (no 200-day line) is never the harsher red "avoid" (M4)
    if kw.get("ma200") is None and tag == "avoid":
        fail("P9", "young name (no 200-day) tagged red 'avoid' — should be amber 'weak'")
    # P10 — never a green buy within 3 sessions of a >4% down day (shock gate)
    w3 = kw.get("worst3")
    if w3 is not None and w3 < -4 and tag == "buy":
        fail("P10", f"BUY {w3}% shock within the last 3 sessions — must wait for it to settle")
    # P11 — the reclaim window: >6 days below the 50-day = firmly weak; 1-3 days = a
    # soft wait, never weak (JLaw gives ~4-6 trading days to reclaim)
    db = kw.get("days_below_50")
    if db is not None and db > 6 and tag not in ("weak", "avoid"):
        fail("P11", f"{db} days below the 50-day unreclaimed but tag is '{tag}' (want weak/avoid)")
    if db is not None and 1 <= db <= 3 and tag in ("weak", "avoid") and (kw.get("ex1") or 0) >= 0:
        fail("P11", f"a {db}-day slip below the 50-day on a strong name tagged '{tag}' — too harsh")
    # P12 — R:R never graded off a sub-ATR risk when there's no buy setup (the exit
    # is a watch-line that can hug the price; the displayed ratio must use >= ~1 ATR)
    if rr.get("ratio") is not None and buy is None and kw.get("atr") and price:
        tgt = kw.get("swing_high")
        if tgt and tgt > price:
            cap = (tgt - price) / (0.9 * kw["atr"])
            if rr["ratio"] > cap:
                fail("P12", f"R:R {rr['ratio']} implies risk < ~1x ATR (cap ~{round(cap,1)})")
    # P5 — exit below price
    if stop is not None and price is not None and stop >= price:
        fail("P5", f"exit {stop} >= price {price}")
    # P6 — R:R positive + label matches
    r0 = rr.get("ratio")
    if r0 is not None:
        if r0 <= 0:
            fail("P6", f"R:R {r0} <= 0")
        want = "good" if r0 >= 2 else ("watch" if r0 >= 1 else "bad")
        if rr.get("state") != want:
            fail("P6", f"R:R {r0} labelled '{rr.get('state')}' (want '{want}')")
    # P7 — no NaN/None in displayed strings
    for s in (r.get("price_str"), (r.get("action") or {}).get("number"),
              (r.get("action") or {}).get("note")):
        if s and ("nan" in str(s).lower() or "none" in str(s).lower()):
            fail("P7", f"NaN/None in a displayed string: {s!r}")

for label, kw in grid():
    pass

if fails:
    print(f"PRINCIPLES TEST: {len(fails)} FAILURE(S)\n")
    for label, rule, msg in fails:
        print(f"  FAIL [{rule}]  {label}\n        {msg}")
    sys.exit(1)
print(f"PRINCIPLES TEST: PASS  ({len(grid())} scenarios, {buys_seen} buy verdicts, all rules hold)")
